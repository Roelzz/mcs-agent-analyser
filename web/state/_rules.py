import os
from pathlib import Path

import reflex as rx
from loguru import logger

from custom_rules import load_rules_yaml


class RulesMixin(rx.State, mixin=True):
    """Custom rules editor state."""

    custom_rules_yaml: str = ""
    custom_rules_parsed: list[dict] = []
    _custom_rules_dicts: list[dict] = []  # full model_dump for checker integration
    rules_parse_error: str = ""
    rules_count: int = 0

    @rx.event
    def on_load_rules_page(self):
        """Load rules on first visit (env var → bundled defaults)."""
        self.check_auth()  # type: ignore[attr-defined]
        if self.custom_rules_yaml:
            return
        rules_file = os.getenv("CUSTOM_RULES_FILE", "")
        if not rules_file:
            default = Path(__file__).resolve().parent.parent.parent / "data" / "default_rules.yaml"
            if default.is_file():
                rules_file = str(default)
        if rules_file:
            try:
                text = Path(rules_file).read_text(encoding="utf-8")
                self.custom_rules_yaml = text
                self._reparse_rules()
            except Exception as e:
                logger.warning(f"Failed to load rules file {rules_file}: {e}")
                self.rules_parse_error = f"Failed to load {rules_file}: {e}"

    @rx.event
    async def handle_rules_upload(self, files: list[rx.UploadFile]):
        if not files:
            return
        upload_file = files[0]
        data = await upload_file.read()
        if not data:
            return
        text = data.decode("utf-8")
        self.custom_rules_yaml = text
        self._reparse_rules()

    @rx.event
    def update_rules_yaml(self, text: str):
        self.custom_rules_yaml = text
        self._reparse_rules()

    @rx.event
    def clear_rules(self):
        self.custom_rules_yaml = ""
        self.custom_rules_parsed = []
        self._custom_rules_dicts = []
        self.rules_parse_error = ""
        self.rules_count = 0

    def _reparse_rules(self):
        """Parse the current YAML text and update parsed rules / error."""
        if not self.custom_rules_yaml.strip():
            self.custom_rules_parsed = []
            self._custom_rules_dicts = []
            self.rules_parse_error = ""
            self.rules_count = 0
            return
        try:
            rules = load_rules_yaml(self.custom_rules_yaml)
            self.custom_rules_parsed = [
                {
                    "rule_id": r.rule_id,
                    "severity": r.severity,
                    "category": r.category,
                    "message": r.message,
                }
                for r in rules
            ]
            self._custom_rules_dicts = [r.model_dump() for r in rules]
            self.rules_count = len(rules)
            self.rules_parse_error = ""
        except ValueError as e:
            self.rules_parse_error = str(e)
            self.custom_rules_parsed = []
            self._custom_rules_dicts = []
            self.rules_count = 0

    def get_custom_rules(self) -> list[dict]:
        """Return pre-parsed custom rules dicts.

        Auto-load priority:
        1. Already-parsed rules (from rules page or previous auto-load)
        2. CUSTOM_RULES_FILE env var
        3. data/default_rules.yaml (bundled defaults)
        """
        if not self._custom_rules_dicts and not self.custom_rules_yaml:
            rules_path = os.getenv("CUSTOM_RULES_FILE", "")
            if not rules_path:
                # Fallback to bundled default rules
                default = Path(__file__).resolve().parent.parent.parent / "data" / "default_rules.yaml"
                if default.is_file():
                    rules_path = str(default)
            if rules_path:
                path = Path(rules_path)
                if path.is_file():
                    try:
                        self.custom_rules_yaml = path.read_text(encoding="utf-8")
                        self._reparse_rules()
                        logger.info(
                            "Auto-loaded {} custom rules from {}",
                            len(self._custom_rules_dicts),
                            rules_path,
                        )
                    except Exception as e:
                        logger.warning(
                            "Failed to auto-load custom rules from {}: {}",
                            rules_path,
                            e,
                        )
        return self._custom_rules_dicts
