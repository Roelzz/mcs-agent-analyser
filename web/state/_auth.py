import reflex as rx

from web.state._base import _clear_bot_profile, _load_users


class AuthMixin(rx.State, mixin=True):
    """Authentication vars and handlers."""

    # Auth vars
    username: str = ""
    password: str = ""
    is_authenticated: bool = False
    auth_error: str = ""

    # Explicit setters (auto-setters deprecated in 0.8.9)
    @rx.event
    def set_username(self, value: str):
        self.username = value

    @rx.event
    def set_password(self, value: str):
        self.password = value

    # --- Auth handlers ---

    @rx.event
    def login(self):
        users = _load_users()
        if not users:
            self.auth_error = "No users configured. Set USERS env var."
            return
        if users.get(self.username) == self.password:
            self.is_authenticated = True
            self.auth_error = ""
            return rx.redirect("/dashboard")
        self.auth_error = "Invalid username or password."

    @rx.event
    def logout(self):
        self.username = ""
        self.password = ""
        self.is_authenticated = False
        self.auth_error = ""
        self.report_markdown = ""  # type: ignore[attr-defined]
        self.report_title = ""  # type: ignore[attr-defined]
        self.report_source = ""  # type: ignore[attr-defined]
        self.upload_error = ""  # type: ignore[attr-defined]
        self.is_processing = False  # type: ignore[attr-defined]
        self.bot_profile_json = ""  # type: ignore[attr-defined]
        _clear_bot_profile()
        self.lint_report_markdown = ""  # type: ignore[attr-defined]
        self.is_linting = False  # type: ignore[attr-defined]
        self.lint_error = ""  # type: ignore[attr-defined]
        # Clear Dataverse state
        self.dv_org_url = ""  # type: ignore[attr-defined]
        self.dv_tenant_id = ""  # type: ignore[attr-defined]
        self.dv_client_id = "04b07795-8ddb-461a-bbee-02f9e1bf7b46"  # type: ignore[attr-defined]
        self.dv_bot_identifier = ""  # type: ignore[attr-defined]
        self.dv_since_date = ""  # type: ignore[attr-defined]
        self.dv_top_n = 50  # type: ignore[attr-defined]
        self.dv_device_code = ""  # type: ignore[attr-defined]
        self.dv_device_code_url = ""  # type: ignore[attr-defined]
        self.dv_is_authenticating = False  # type: ignore[attr-defined]
        self.dv_auth_error = ""  # type: ignore[attr-defined]
        self.dv_is_connected = False  # type: ignore[attr-defined]
        self.dv_token = ""  # type: ignore[attr-defined]
        self.dv_is_fetching = False  # type: ignore[attr-defined]
        self.dv_fetch_error = ""  # type: ignore[attr-defined]
        self.dv_transcripts = []  # type: ignore[attr-defined]
        self.dv_transcript_contents = {}  # type: ignore[attr-defined]
        self.dv_import_processing = False  # type: ignore[attr-defined]
        self.dv_import_error = ""  # type: ignore[attr-defined]
        self.dv_session_details_paste = ""  # type: ignore[attr-defined]
        self.dv_autofill_error = ""  # type: ignore[attr-defined]
        self.dv_conversation_id = ""  # type: ignore[attr-defined]
        self.dv_single_fetch_error = ""  # type: ignore[attr-defined]
        self.dv_single_fetching = False  # type: ignore[attr-defined]
        self.dv_bot_analysing = False  # type: ignore[attr-defined]
        self.dv_bot_analyse_error = ""  # type: ignore[attr-defined]
        self.dv_schema_lookup = {}  # type: ignore[attr-defined]
        # Clear solution tools state
        self.sol_zip_bytes = b""  # type: ignore[attr-defined]
        self.sol_zip_name = ""  # type: ignore[attr-defined]
        self.sol_active_tab = "check"  # type: ignore[attr-defined]
        self.sol_check_results = []  # type: ignore[attr-defined]
        self.sol_check_error = ""  # type: ignore[attr-defined]
        self.sol_check_agent_name = ""  # type: ignore[attr-defined]
        self.sol_check_solution_name = ""  # type: ignore[attr-defined]
        self.sol_check_pass = 0  # type: ignore[attr-defined]
        self.sol_check_warn = 0  # type: ignore[attr-defined]
        self.sol_check_fail = 0  # type: ignore[attr-defined]
        self.sol_check_info = 0  # type: ignore[attr-defined]
        self.sol_check_active_category = "All"  # type: ignore[attr-defined]
        self.sol_validate_results = []  # type: ignore[attr-defined]
        self.sol_validate_error = ""  # type: ignore[attr-defined]
        self.sol_validate_model_display = ""  # type: ignore[attr-defined]
        self.sol_validate_best_practices_md = ""  # type: ignore[attr-defined]
        self.sol_deps_segments = []  # type: ignore[attr-defined]
        self.sol_deps_error = ""  # type: ignore[attr-defined]
        self.sol_rename_new_agent = ""  # type: ignore[attr-defined]
        self.sol_rename_new_solution = ""  # type: ignore[attr-defined]
        self.sol_rename_result_bytes = b""  # type: ignore[attr-defined]
        self.sol_rename_result = {}  # type: ignore[attr-defined]
        self.sol_rename_error = ""  # type: ignore[attr-defined]
        self.sol_detected_info = {}  # type: ignore[attr-defined]
        return rx.redirect("/")

    async def check_auth(self):
        if not self.is_authenticated:
            return rx.redirect("/")
        await self._refresh_community_count()  # type: ignore[attr-defined]

    def check_already_authed(self):
        if self.is_authenticated:
            return rx.redirect("/dashboard")

    async def check_analysis_page(self):
        if not self.is_authenticated:
            return rx.redirect("/")
        if not self.report_markdown:  # type: ignore[attr-defined]
            return rx.redirect("/dashboard")
        await self._refresh_community_count()  # type: ignore[attr-defined]
