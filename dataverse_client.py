"""Slimmed Dataverse client for fetching conversation transcripts.

Copied from evals project, stripped to only fetch_transcripts + resolve_bot_guid.
"""

import asyncio
import re
from datetime import datetime, timezone

import httpx
import msal
from loguru import logger

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

_ODATA_HEADERS = {
    "Accept": "application/json",
    "OData-MaxVersion": "4.0",
    "OData-Version": "4.0",
}


class DataverseClient:
    def __init__(
        self,
        org_url: str,
        tenant_id: str,
        client_id: str,
        client_secret: str = "",
        _prefetched_token: str = "",
    ) -> None:
        self.org_url = org_url.rstrip("/")
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self._token: str | None = _prefetched_token or None

    async def _get_token(self) -> str:
        if self._token:
            return self._token

        scope = f"{self.org_url}/.default"
        authority = f"https://login.microsoftonline.com/{self.tenant_id}"

        app = msal.ConfidentialClientApplication(
            self.client_id,
            authority=authority,
            client_credential=self.client_secret,
        )
        result = await asyncio.to_thread(app.acquire_token_for_client, scopes=[scope])

        if "access_token" not in result:
            error = result.get("error_description", result.get("error", "Unknown error"))
            raise RuntimeError(f"Dataverse token acquisition failed: {error}")

        logger.info("Dataverse token acquired")
        return result["access_token"]

    async def resolve_bot_guid(self, bot_identifier: str) -> str:
        """Return bot GUID, resolving from schema name if needed."""
        if _UUID_RE.match(bot_identifier):
            return bot_identifier

        token = await self._get_token()
        url = f"{self.org_url}/api/data/v9.2/bots?$filter=schemaname eq '{bot_identifier}'&$select=botid,name"
        headers = {"Authorization": f"Bearer {token}", **_ODATA_HEADERS}

        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=headers, timeout=30)

        if resp.status_code == 403:
            logger.warning("403 on bots table for '{}' — falling back to auto-detect", bot_identifier)
            return await self._auto_detect_bot_guid()

        resp.raise_for_status()

        bots = resp.json().get("value", [])
        if not bots:
            raise RuntimeError(f"No bot found with schemaname '{bot_identifier}' in Dataverse")

        bot_id = bots[0]["botid"]
        logger.info("Resolved '{}' → bot GUID {}", bot_identifier, bot_id)
        return bot_id

    async def _auto_detect_bot_guid(self) -> str:
        """Detect bot GUID by sampling recent transcripts."""
        token = await self._get_token()
        url = (
            f"{self.org_url}/api/data/v9.2/conversationtranscripts"
            f"?$top=5&$orderby=createdon desc"
            f"&$select=_bot_conversationtranscriptid_value"
        )
        headers = {"Authorization": f"Bearer {token}", **_ODATA_HEADERS}

        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=headers, timeout=30)

        if resp.status_code == 403:
            raise RuntimeError(
                "Cannot resolve bot GUID: both the bots table and conversationtranscripts "
                "returned 403. Provide the bot UUID directly."
            )

        resp.raise_for_status()

        records = resp.json().get("value", [])
        guids = {
            r["_bot_conversationtranscriptid_value"] for r in records if r.get("_bot_conversationtranscriptid_value")
        }

        if len(guids) == 1:
            guid = guids.pop()
            logger.warning("Auto-detected bot GUID {} from transcripts", guid)
            return guid

        if not guids:
            raise RuntimeError("Cannot auto-detect bot GUID: no recent transcripts found.")

        raise RuntimeError(f"Multiple bots found in transcripts ({guids}). Provide the bot UUID directly.")

    async def fetch_transcript_by_id(self, conversation_id: str) -> dict:
        """Fetch a single transcript by its primary key (conversation ID)."""
        token = await self._get_token()
        url = f"{self.org_url}/api/data/v9.2/conversationtranscripts({conversation_id})"
        headers = {"Authorization": f"Bearer {token}", **_ODATA_HEADERS}

        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=headers, timeout=30)

        if resp.status_code == 404:
            raise RuntimeError(
                f"No transcript found with ID '{conversation_id}'. Check the conversation ID and try again."
            )
        resp.raise_for_status()
        return resp.json()

    async def fetch_bot_config(self, bot_guid: str) -> dict:
        """Fetch a single bot record by GUID."""
        token = await self._get_token()
        url = f"{self.org_url}/api/data/v9.2/bots({bot_guid})?$select=botid,name,schemaname,configuration"
        headers = {"Authorization": f"Bearer {token}", **_ODATA_HEADERS}

        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=headers, timeout=30)

        if resp.status_code == 403:
            raise RuntimeError("Access denied. Your account needs read access to the bots table in Dataverse.")
        if resp.status_code == 404:
            raise RuntimeError(f"No bot found with ID '{bot_guid}'.")
        resp.raise_for_status()
        return resp.json()

    async def fetch_bot_components(self, bot_guid: str) -> list[dict]:
        """Fetch all botcomponents for a bot, handling pagination.

        Tries direct _parentbotid_value lookup first; falls back to the
        many-to-many bot_botcomponent navigation property when that returns 0.
        """
        token = await self._get_token()
        headers = {"Authorization": f"Bearer {token}", **_ODATA_HEADERS}

        # --- Attempt 1: direct lookup on _parentbotid_value ---
        url: str | None = (
            f"{self.org_url}/api/data/v9.2/botcomponents"
            f"?$filter=_parentbotid_value eq '{bot_guid}'"
            f"&$select=botcomponentid,componenttype,content,schemaname,name"
        )
        logger.debug("OData component URL (direct): {}", url)
        all_records: list[dict] = []
        all_records = await self._paginated_get(url, headers)

        if all_records:
            logger.info(f"Fetched {len(all_records)} bot component(s) via direct lookup")
            all_records = await self._enrich_component_content(all_records, headers)
            return all_records

        # --- Attempt 2: M:N navigation property (bot_botcomponent) ---
        logger.info("Direct lookup returned 0 components — trying M:N navigation property")
        url = (
            f"{self.org_url}/api/data/v9.2/bots({bot_guid})/bot_botcomponent"
            f"?$select=botcomponentid,componenttype,content,schemaname,name"
        )
        logger.debug("OData component URL (M:N nav): {}", url)
        all_records = await self._paginated_get(url, headers)

        logger.info(f"Fetched {len(all_records)} bot component(s) via M:N navigation")
        all_records = await self._enrich_component_content(all_records, headers)
        return all_records

    async def _paginated_get(self, url: str | None, headers: dict) -> list[dict]:
        """Execute a paginated OData GET, following @odata.nextLink."""
        all_records: list[dict] = []
        async with httpx.AsyncClient() as client:
            while url:
                resp = await client.get(url, headers=headers, timeout=60)

                if resp.status_code == 403:
                    raise RuntimeError(
                        "Access denied. Your account needs read access to the botcomponents table in Dataverse."
                    )
                resp.raise_for_status()

                data = resp.json()
                all_records.extend(data.get("value", []))
                url = data.get("@odata.nextLink")
        return all_records

    async def _enrich_component_content(self, records: list[dict], headers: dict) -> list[dict]:
        """Fetch content individually if collection query returned empty content.

        Dataverse OData omits large text/memo columns from $filter queries.
        Probes the first component without $select to discover available columns,
        then auto-detects the correct data column if 'content' is null.
        """
        if not records:
            return records

        has_content = any((r.get("content") or "") for r in records)
        if has_content:
            return records

        logger.warning(
            "All {} component records have empty content — fetching individually",
            len(records),
        )

        # --- Probe first component without $select to discover available columns ---
        first_id = next(
            (r["botcomponentid"] for r in records if r.get("botcomponentid")),
            None,
        )
        content_field = "content"  # default
        drop_select = False
        if first_id:
            probe_url = f"{self.org_url}/api/data/v9.2/botcomponents({first_id})"
            async with httpx.AsyncClient() as client:
                probe = await client.get(probe_url, headers=headers, timeout=30)
            if probe.status_code == 200:
                probe_data = probe.json()
                non_null_keys = [k for k, v in probe_data.items() if v is not None and not k.startswith("@")]
                logger.debug(
                    "Probe component (no $select) — non-null keys: {}",
                    non_null_keys,
                )
                # Check if content is now populated without $select
                if probe_data.get("content"):
                    logger.info("Content available without $select — fetching all without $select")
                    content_field = "content"
                    drop_select = True
                else:
                    # Look for alternative data columns
                    for candidate in ("data", "componentdefinition", "definition"):
                        if probe_data.get(candidate):
                            logger.info(
                                "Found component data in '{}' column instead of 'content'",
                                candidate,
                            )
                            content_field = candidate
                            break
                    else:
                        logger.warning(
                            "Probe: content still null even without $select. Non-null keys: {}",
                            non_null_keys,
                        )

        # --- Fetch all components individually ---
        async with httpx.AsyncClient() as client:
            for record in records:
                comp_id = record.get("botcomponentid", "")
                if not comp_id:
                    continue
                # Drop $select if probe showed content is available without it,
                # otherwise select the discovered content field
                if drop_select:
                    url = f"{self.org_url}/api/data/v9.2/botcomponents({comp_id})"
                else:
                    url = f"{self.org_url}/api/data/v9.2/botcomponents({comp_id})?$select={content_field}"
                resp = await client.get(url, headers=headers, timeout=30)
                if resp.status_code == 200:
                    value = resp.json().get(content_field, "")
                    record["content"] = value or ""
                else:
                    logger.warning(
                        "Individual fetch for {} returned status {}",
                        comp_id,
                        resp.status_code,
                    )

        enriched = sum(1 for r in records if r.get("content"))
        logger.info("Enriched {}/{} components with content", enriched, len(records))
        return records

    async def fetch_transcripts(
        self,
        bot_guid: str,
        since: datetime,
        top: int = 100,
    ) -> list[dict]:
        """Fetch conversation transcripts for a bot since a given datetime."""
        bot_guid = await self.resolve_bot_guid(bot_guid)
        token = await self._get_token()
        since_str = since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        url = (
            f"{self.org_url}/api/data/v9.2/conversationtranscripts"
            f"?$filter=_bot_conversationtranscriptid_value eq '{bot_guid}'"
            f" and createdon gt {since_str}"
            f"&$top={top}"
            f"&$orderby=createdon desc"
        )
        headers = {"Authorization": f"Bearer {token}", **_ODATA_HEADERS}

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, timeout=30)
            response.raise_for_status()

        data = response.json()
        records = data.get("value", [])
        logger.info(f"Fetched {len(records)} transcript(s) from Dataverse")
        return records
