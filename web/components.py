import reflex as rx

from web.mermaid import render_segment
from web.state import State

UPLOAD_ID = "file_upload"
_MONO = "JetBrains Mono, monospace"
_BODY = "Outfit, sans-serif"


def login_form() -> rx.Component:
    return rx.card(
        rx.form(
            rx.vstack(
                # Icon badge
                rx.box(
                    rx.icon("scan-search", size=24, color="var(--green-9)"),
                    padding="12px",
                    background="var(--green-a3)",
                    border_radius="10px",
                    border="1px solid var(--green-a5)",
                    display="inline-flex",
                    align_self="center",
                ),
                rx.vstack(
                    rx.heading(
                        "Agent Analyser",
                        size="6",
                        font_family=_MONO,
                        font_weight="600",
                        letter_spacing="-0.5px",
                        color="var(--gray-12)",
                    ),
                    rx.text(
                        "Copilot Studio Intelligence",
                        size="2",
                        color="var(--gray-a9)",
                        font_family=_BODY,
                    ),
                    spacing="1",
                    align="center",
                    width="100%",
                ),
                rx.separator(size="4"),
                rx.input(
                    placeholder="Username",
                    value=State.username,
                    on_change=State.set_username,
                    width="100%",
                    size="3",
                ),
                rx.input(
                    placeholder="Password",
                    type="password",
                    value=State.password,
                    on_change=State.set_password,
                    width="100%",
                    size="3",
                ),
                rx.cond(
                    State.auth_error != "",
                    rx.callout(
                        State.auth_error,
                        icon="triangle_alert",
                        color_scheme="red",
                        size="1",
                        width="100%",
                    ),
                ),
                rx.button(
                    "Sign In",
                    type="submit",
                    width="100%",
                    size="3",
                    color_scheme="green",
                    font_weight="500",
                    cursor="pointer",
                ),
                spacing="4",
                width="100%",
                align="center",
            ),
            on_submit=lambda _: State.login(),
            reset_on_submit=False,
        ),
        # Community counter badge — shared with GitHub README
        rx.image(
            src="https://komarev.com/ghpvc/?username=Roelzz&label=Community%20Views&color=0e75b6&style=flat",
            alt="Community Views",
            height="20px",
            margin_top="12px",
            opacity="0.6",
        ),
        width="380px",
        padding="32px",
        background="var(--gray-a2)",
        border="1px solid var(--gray-a4)",
        box_shadow=rx.color_mode_cond(
            "0 0 0 1px rgba(34,197,94,0.15), 0 8px 24px rgba(0,0,0,0.1)",
            "0 0 0 1px var(--green-a3), 0 24px 48px rgba(0,0,0,0.5)",
        ),
        border_radius="16px",
    )


def _nav_link(icon_name: str, label: str, href: str) -> rx.Component:
    is_active = State.router.page.path == href
    return rx.link(
        rx.hstack(
            rx.icon(icon_name, size=14, color=rx.cond(is_active, "var(--green-9)", "var(--gray-a9)")),
            rx.text(
                label,
                size="2",
                color=rx.cond(is_active, "var(--green-11)", "var(--gray-a9)"),
                font_weight=rx.cond(is_active, "500", "400"),
            ),
            spacing="1",
            align="center",
        ),
        href=href,
        underline="none",
    )


def navbar() -> rx.Component:
    return rx.hstack(
        # Logo
        rx.link(
            rx.hstack(
                rx.icon("scan-search", size=17, color="var(--green-9)"),
                rx.text(
                    "Agent Analyser",
                    size="3",
                    font_family=_MONO,
                    font_weight="600",
                    color="var(--gray-12)",
                    letter_spacing="-0.3px",
                ),
                align="center",
                spacing="2",
            ),
            href="/dashboard",
            underline="none",
        ),
        # Nav links
        rx.hstack(
            _nav_link("layout-dashboard", "Dashboard", "/dashboard"),
            _nav_link("upload", "Upload", "/upload"),
            _nav_link("database", "Dataverse", "/import"),
            _nav_link("wrench", "Solution Tools", "/tools"),
            rx.cond(
                State.has_report,
                _nav_link("file-text", "Report", "/analysis"),
            ),
            spacing="4",
            align="center",
        ),
        # Counter badge
        rx.hstack(
            rx.text(State.cat_emoji, font_size="18px"),
            rx.text(
                State.analyses_count,
                font_family=_MONO,
                font_weight="600",
                color="var(--amber-11)",
                class_name=rx.cond(State.counter_animating, "counter-pop", ""),
            ),
            rx.text(
                State.cat_title,
                size="1",
                color="var(--gray-a8)",
                font_family=_BODY,
            ),
            rx.cond(
                State.milestone_reached,
                rx.text(
                    "\U0001f389 NEW RANK!",
                    size="1",
                    color="var(--amber-9)",
                    font_weight="600",
                    class_name="milestone-flash",
                ),
            ),
            align="center",
            spacing="2",
            padding="4px 12px",
            background="var(--amber-a2)",
            border="1px solid var(--amber-a4)",
            border_radius="20px",
        ),
        rx.spacer(),
        # Right side
        rx.hstack(
            rx.box(
                rx.text(
                    State.username,
                    size="1",
                    color="var(--green-11)",
                    font_family=_MONO,
                ),
                padding="4px 10px",
                background="var(--green-a3)",
                border="1px solid var(--green-a5)",
                border_radius="20px",
            ),
            rx.color_mode.button(size="2", variant="ghost", color_scheme="gray"),
            rx.button(
                "Logout",
                variant="ghost",
                size="2",
                color_scheme="gray",
                on_click=State.logout,
                cursor="pointer",
            ),
            align="center",
            spacing="3",
        ),
        width="100%",
        padding="13px 28px",
        border_bottom="1px solid var(--gray-a4)",
        background=rx.color_mode_cond(
            "rgba(255, 255, 255, 0.75)",  # light
            "rgba(12, 14, 20, 0.75)",  # dark
        ),
        backdrop_filter="blur(12px)",
        align="center",
        position="sticky",
        top="0",
        z_index="100",
    )


def _dashboard_card(icon_name: str, title: str, description: str, href: str) -> rx.Component:
    return rx.link(
        rx.vstack(
            rx.box(
                rx.icon(icon_name, size=24, color="var(--green-9)"),
                padding="12px",
                background="var(--green-a3)",
                border_radius="10px",
                border="1px solid var(--green-a5)",
                display="inline-flex",
            ),
            rx.text(title, size="4", font_weight="500", color="var(--gray-12)"),
            rx.text(description, size="2", color="var(--gray-a9)", line_height="1.5"),
            spacing="3",
            padding="24px",
            background="var(--gray-a2)",
            border="1px solid var(--gray-a4)",
            border_radius="16px",
            width="280px",
            min_height="180px",
            _hover={
                "border_color": "var(--green-a6)",
                "background": "var(--gray-a3)",
            },
            transition="all 0.15s ease",
        ),
        href=href,
        underline="none",
    )


def dashboard_cards() -> rx.Component:
    return rx.center(
        rx.hstack(
            _dashboard_card(
                "upload",
                "Upload & Analyse",
                "Upload a bot export (.zip) or paste a conversation transcript (.json)",
                "/upload",
            ),
            _dashboard_card(
                "database",
                "Dataverse Import",
                "Connect to Dataverse and fetch transcripts live from your environment",
                "/import",
            ),
            _dashboard_card(
                "wrench",
                "Solution Tools",
                "Check, validate, rename, and inspect solution exports",
                "/tools",
            ),
            spacing="5",
            flex_wrap="wrap",
            justify="center",
        ),
        width="100%",
        padding_top="80px",
        padding_x="24px",
    )


def upload_form() -> rx.Component:
    return rx.center(
        rx.vstack(
            # Heading
            rx.vstack(
                rx.heading(
                    "Upload & Analyse",
                    size="7",
                    font_family=_MONO,
                    font_weight="600",
                    color="var(--gray-12)",
                    letter_spacing="-0.5px",
                ),
                rx.text(
                    "Drop a Copilot Studio bot export or conversation transcript",
                    size="2",
                    color="var(--gray-a9)",
                    text_align="center",
                ),
                spacing="2",
                align="center",
            ),
            # Onboarding hints
            rx.hstack(
                rx.box(
                    rx.hstack(
                        rx.icon("package", size=16, color="var(--green-9)"),
                        rx.vstack(
                            rx.text("Bot Export (.zip)", size="2", font_weight="500", color="var(--gray-12)"),
                            rx.text("Export from Copilot Studio", size="1", color="var(--gray-a9)"),
                            spacing="1",
                        ),
                        spacing="3",
                        align="center",
                    ),
                    padding="12px 16px",
                    background="var(--gray-a2)",
                    border="1px solid var(--gray-a4)",
                    border_radius="10px",
                    flex="1",
                ),
                rx.box(
                    rx.hstack(
                        rx.icon("database", size=16, color="var(--green-9)"),
                        rx.vstack(
                            rx.text("Dataverse Import", size="2", font_weight="500", color="var(--gray-12)"),
                            rx.text("Connect for live analysis", size="1", color="var(--gray-a9)"),
                            spacing="1",
                        ),
                        spacing="3",
                        align="center",
                    ),
                    padding="12px 16px",
                    background="var(--gray-a2)",
                    border="1px solid var(--gray-a4)",
                    border_radius="10px",
                    flex="1",
                    cursor="pointer",
                    on_click=rx.redirect("/import"),
                ),
                spacing="3",
                width="100%",
            ),
            # Card
            rx.box(
                rx.vstack(
                    rx.upload(
                        rx.vstack(
                            rx.box(
                                rx.icon("upload", size=28, color="var(--green-9)"),
                                padding="14px",
                                background="var(--green-a3)",
                                border_radius="50%",
                                border="1px solid var(--green-a5)",
                                display="inline-flex",
                            ),
                            rx.text(
                                "Drag & drop or click to browse",
                                size="3",
                                color="var(--gray-11)",
                                font_weight="500",
                            ),
                            rx.text(
                                ".zip bot export, botContent.yml + dialog.json, or .json transcript",
                                size="2",
                                color="var(--gray-a8)",
                            ),
                            align="center",
                            spacing="3",
                        ),
                        id=UPLOAD_ID,
                        border="1.5px dashed var(--green-a6)",
                        border_radius="12px",
                        padding="48px 32px",
                        width="100%",
                        cursor="pointer",
                        multiple=True,
                        background="var(--green-a1)",
                        transition="all 0.15s ease",
                    ),
                    rx.foreach(
                        rx.selected_files(UPLOAD_ID),
                        lambda f: rx.hstack(
                            rx.icon("file", size=12, color="var(--green-9)"),
                            rx.text(f, size="1", color="var(--gray-a9)"),
                            spacing="1",
                            align="center",
                        ),
                    ),
                    rx.cond(
                        State.upload_error != "",
                        rx.callout(
                            State.upload_error,
                            icon="triangle_alert",
                            color_scheme="red",
                            size="1",
                            width="100%",
                        ),
                    ),
                    rx.button(
                        rx.cond(
                            State.is_processing,
                            rx.hstack(
                                rx.spinner(size="1"),
                                rx.text(rx.cond(State.upload_stage != "", State.upload_stage, "Analysing...")),
                                align="center",
                                spacing="2",
                            ),
                            rx.hstack(
                                rx.icon("zap", size=15),
                                rx.text("Analyse"),
                                align="center",
                                spacing="2",
                            ),
                        ),
                        on_click=State.handle_upload(rx.upload_files(upload_id=UPLOAD_ID)),
                        width="100%",
                        size="3",
                        color_scheme="green",
                        disabled=State.is_processing,
                        cursor="pointer",
                        font_weight="500",
                    ),
                    # Divider
                    rx.hstack(
                        rx.separator(size="4", color_scheme="gray"),
                        rx.text("or", size="2", color="var(--gray-a8)", white_space="nowrap"),
                        rx.separator(size="4", color_scheme="gray"),
                        width="100%",
                        align="center",
                        spacing="3",
                    ),
                    # Paste section
                    rx.text_area(
                        placeholder="Paste raw transcript JSON...",
                        value=State.paste_json,
                        on_change=State.set_paste_json,
                        width="100%",
                        min_height="120px",
                        font_family=_MONO,
                        size="2",
                    ),
                    rx.button(
                        rx.cond(
                            State.is_processing,
                            rx.hstack(
                                rx.spinner(size="1"),
                                rx.text(rx.cond(State.upload_stage != "", State.upload_stage, "Analysing...")),
                                align="center",
                                spacing="2",
                            ),
                            rx.hstack(
                                rx.icon("clipboard-paste", size=15),
                                rx.text("Paste & Analyse"),
                                align="center",
                                spacing="2",
                            ),
                        ),
                        on_click=State.handle_paste_submit,
                        width="100%",
                        size="3",
                        color_scheme="green",
                        variant="outline",
                        disabled=State.is_processing,
                        cursor="pointer",
                        font_weight="500",
                    ),
                    spacing="4",
                    width="100%",
                ),
                padding="28px",
                background="var(--gray-a2)",
                border="1px solid var(--gray-a4)",
                border_radius="16px",
                max_width="560px",
                width="100%",
                box_shadow="0 8px 32px rgba(0,0,0,0.35)",
            ),
            spacing="6",
            align="center",
            width="100%",
        ),
        width="100%",
        padding="64px 24px",
        min_height="calc(100vh - 54px)",
    )


def report_viewer() -> rx.Component:
    return rx.box(
        # Header
        rx.hstack(
            rx.vstack(
                rx.text(
                    "Analysis Report",
                    size="1",
                    font_family=_MONO,
                    color="var(--green-11)",
                    letter_spacing="0.08em",
                    text_transform="uppercase",
                ),
                rx.heading(
                    State.report_title,
                    size="5",
                    font_family=_MONO,
                    font_weight="600",
                    color="var(--gray-12)",
                    letter_spacing="-0.3px",
                ),
                spacing="1",
                align="start",
            ),
            rx.spacer(),
            rx.hstack(
                rx.menu.root(
                    rx.menu.trigger(
                        rx.button(
                            rx.icon("download", size=14),
                            rx.text("Download"),
                            rx.icon("chevron-down", size=12),
                            variant="outline",
                            size="2",
                            color_scheme="gray",
                            cursor="pointer",
                        ),
                    ),
                    rx.menu.content(
                        rx.menu.item(
                            rx.hstack(
                                rx.icon("file-text", size=14),
                                rx.text("Markdown (.md)"),
                                align="center",
                                spacing="2",
                            ),
                            on_click=State.download_report,
                        ),
                        rx.menu.item(
                            rx.hstack(
                                rx.icon("globe", size=14),
                                rx.text("HTML (.html)"),
                                align="center",
                                spacing="2",
                            ),
                            on_click=State.download_report_html,
                        ),
                        rx.menu.item(
                            rx.hstack(
                                rx.icon("printer", size=14),
                                rx.text("Print to PDF"),
                                align="center",
                                spacing="2",
                            ),
                            on_click=State.download_report_pdf,
                        ),
                    ),
                ),
                rx.button(
                    rx.icon("copy", size=14),
                    rx.text("Copy"),
                    variant="outline",
                    size="2",
                    color_scheme="gray",
                    cursor="pointer",
                    on_click=State.copy_report_to_clipboard,
                ),
                rx.cond(
                    State.can_lint,
                    rx.button(
                        rx.cond(
                            State.is_linting,
                            rx.hstack(
                                rx.spinner(size="1"),
                                rx.text("Linting..."),
                                align="center",
                                spacing="2",
                            ),
                            rx.hstack(
                                rx.icon("scan-search", size=14),
                                rx.text("Instruction Lint"),
                                align="center",
                                spacing="2",
                            ),
                        ),
                        variant="outline",
                        color_scheme="amber",
                        size="2",
                        on_click=State.run_lint,
                        disabled=State.is_linting,
                        cursor="pointer",
                    ),
                ),
                rx.cond(
                    State.report_source == "import",
                    rx.button(
                        rx.icon("arrow-left", size=14),
                        rx.text("Back to Dataverse"),
                        variant="soft",
                        size="2",
                        color_scheme="green",
                        on_click=State.dv_back_to_list,
                        cursor="pointer",
                    ),
                    rx.button(
                        rx.icon("plus", size=14),
                        rx.text("New Analysis"),
                        variant="soft",
                        size="2",
                        color_scheme="green",
                        on_click=State.new_upload,
                        cursor="pointer",
                    ),
                ),
                spacing="2",
                align="center",
            ),
            width="100%",
            align="center",
            padding_bottom="20px",
        ),
        rx.cond(
            State.lint_error != "",
            rx.callout(
                State.lint_error,
                icon="triangle_alert",
                color_scheme="red",
                size="1",
                width="100%",
                margin_bottom="16px",
            ),
        ),
        rx.separator(),
        rx.box(
            rx.foreach(State.report_segments, render_segment),
            padding_top="24px",
        ),
        rx.cond(
            State.has_lint_report,
            rx.box(
                rx.box(rx.separator(), margin_top="32px"),
                rx.hstack(
                    rx.hstack(
                        rx.icon("scan-search", size=16, color="var(--amber-9)"),
                        rx.heading(
                            "Instruction Lint Report",
                            size="4",
                            font_family=_MONO,
                            color="var(--gray-12)",
                        ),
                        align="center",
                        spacing="2",
                    ),
                    rx.spacer(),
                    rx.hstack(
                        rx.button(
                            rx.icon("download", size=14),
                            rx.text("Download Lint"),
                            variant="outline",
                            size="2",
                            color_scheme="amber",
                            on_click=State.download_lint_report,
                            cursor="pointer",
                        ),
                        rx.button(
                            rx.icon("x", size=14),
                            rx.text("Dismiss"),
                            variant="ghost",
                            size="2",
                            color_scheme="gray",
                            on_click=State.clear_lint,
                            cursor="pointer",
                        ),
                        spacing="2",
                    ),
                    width="100%",
                    align="center",
                    padding_top="20px",
                    padding_bottom="16px",
                ),
                rx.box(
                    rx.foreach(State.lint_report_segments, render_segment),
                ),
            ),
        ),
        id="report-content",
        max_width="1400px",
        width="100%",
        padding="28px 32px",
        margin="0 auto",
    )


def _dv_field(label: str, helper: str, placeholder: str, value, on_change, **kwargs) -> rx.Component:
    """Reusable Dataverse form field with label and helper text."""
    return rx.vstack(
        rx.text(label, size="2", font_weight="500", color="var(--gray-11)"),
        rx.input(
            placeholder=placeholder,
            value=value,
            on_change=on_change,
            width="100%",
            size="2",
            font_family=_MONO,
            **kwargs,
        ),
        rx.text(helper, size="1", color="var(--gray-a8)"),
        spacing="1",
        width="100%",
    )


def import_connection_form() -> rx.Component:
    return rx.vstack(
        # Session details autofill
        rx.callout(
            "Paste your Copilot Studio session details to auto-fill. "
            "Find them under Settings (gear icon) → Session details.",
            icon="info",
            color_scheme="green",
            size="1",
            width="100%",
        ),
        # Prerequisites info (collapsed by default)
        rx.accordion.root(
            rx.accordion.item(
                header="Prerequisites & Permissions",
                content=rx.vstack(
                    rx.text(
                        "What you need",
                        size="2",
                        font_weight="600",
                        color="var(--gray-12)",
                    ),
                    rx.box(
                        rx.el.ul(
                            rx.el.li(
                                "Conversation transcripts enabled on your copilot — in Copilot Studio go to ",
                                rx.text.strong("Settings → Agent → Conversation transcripts"),
                                " and toggle it on. Transcripts are off by default for new bots.",
                            ),
                            rx.el.li(
                                "Read access to the ",
                                rx.code("conversationtranscripts"),
                                " table for transcript analysis, and ",
                                rx.code("bots"),
                                " + ",
                                rx.code("botcomponents"),
                                " tables for full bot analysis",
                            ),
                            rx.el.li(
                                "Your session details (Tenant ID, Instance URL, Copilot ID) from Copilot Studio Settings",
                            ),
                            style={
                                "padding_left": "20px",
                                "margin": "0",
                                "font_size": "13px",
                                "color": "var(--gray-11)",
                                "line_height": "1.7",
                            },
                        ),
                    ),
                    rx.text(
                        "How to check / get access",
                        size="2",
                        font_weight="600",
                        color="var(--gray-12)",
                    ),
                    rx.box(
                        rx.el.ul(
                            rx.el.li(
                                "System Administrator and System Customizer roles have access by default",
                            ),
                            rx.el.li(
                                "For other roles: ask your admin to add Read privilege on ",
                                rx.code("ConversationTranscript"),
                                ", ",
                                rx.code("Bot"),
                                ", and ",
                                rx.code("BotComponent"),
                                " entities",
                            ),
                            rx.el.li(
                                "If you get a 403 error after connecting, this is the permission you're missing",
                            ),
                            style={
                                "padding_left": "20px",
                                "margin": "0",
                                "font_size": "13px",
                                "color": "var(--gray-11)",
                                "line_height": "1.7",
                            },
                        ),
                    ),
                    rx.text(
                        "Authentication",
                        size="2",
                        font_weight="600",
                        color="var(--gray-12)",
                    ),
                    rx.box(
                        rx.el.ul(
                            rx.el.li(
                                "This tool uses device code auth — any user with a Microsoft Entra account in the tenant can sign in, no app registration required",
                            ),
                            rx.el.li(
                                "The token is delegated, so your Dataverse security role determines what you can read",
                            ),
                            style={
                                "padding_left": "20px",
                                "margin": "0",
                                "font_size": "13px",
                                "color": "var(--gray-11)",
                                "line_height": "1.7",
                            },
                        ),
                    ),
                    spacing="2",
                    padding="4px 0",
                ),
            ),
            collapsible=True,
            width="100%",
            variant="ghost",
            color_scheme="gray",
        ),
        rx.text_area(
            placeholder="Paste session details here...\n\nTenant ID: xxxxxxxx-...\nInstance url: https://...\nCopilot Id: xxxxxxxx-...",
            value=State.dv_session_details_paste,
            on_change=State.set_dv_session_details_paste,
            width="100%",
            min_height="100px",
            font_family=_MONO,
            size="2",
        ),
        rx.button(
            rx.hstack(
                rx.icon("clipboard-paste", size=15),
                rx.text("Auto-fill"),
                align="center",
                spacing="2",
            ),
            on_click=State.dv_autofill_from_session_details,
            width="100%",
            size="2",
            color_scheme="green",
            variant="outline",
            cursor="pointer",
            font_weight="500",
        ),
        rx.cond(
            State.dv_autofill_error != "",
            rx.callout(
                State.dv_autofill_error,
                icon="triangle_alert",
                color_scheme="amber",
                size="1",
                width="100%",
            ),
        ),
        rx.hstack(
            rx.separator(size="4", color_scheme="gray"),
            rx.text("or fill in manually", size="2", color="var(--gray-a8)", white_space="nowrap"),
            rx.separator(size="4", color_scheme="gray"),
            width="100%",
            align="center",
            spacing="3",
        ),
        _dv_field(
            "Environment URL",
            "Copilot Studio → Settings (gear icon) → Session details → Instance url",
            "https://yourorg.crm4.dynamics.com",
            State.dv_org_url,
            State.set_dv_org_url,
        ),
        _dv_field(
            "Tenant ID",
            "Copilot Studio → Settings (gear icon) → Session details → Tenant ID",
            "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
            State.dv_tenant_id,
            State.set_dv_tenant_id,
        ),
        _dv_field(
            "Client ID",
            "Microsoft CLI client ID (default works for device code auth). Change only if using a custom app registration.",
            "04b07795-8ddb-461a-bbee-02f9e1bf7b46",
            State.dv_client_id,
            State.set_dv_client_id,
        ),
        _dv_field(
            "Bot Identifier",
            "Copilot Studio → Settings (gear icon) → Session details → Copilot Id",
            "cr123_agentName or UUID",
            State.dv_bot_identifier,
            State.set_dv_bot_identifier,
        ),
        rx.hstack(
            rx.vstack(
                rx.text("Since Date", size="2", font_weight="500", color="var(--gray-11)"),
                rx.input(
                    type="date",
                    value=State.dv_since_date,
                    on_change=State.set_dv_since_date,
                    width="100%",
                    size="2",
                    font_family=_MONO,
                ),
                rx.text("Fetch transcripts created after this date", size="1", color="var(--gray-a8)"),
                spacing="1",
                flex="1",
            ),
            rx.vstack(
                rx.text("Top N", size="2", font_weight="500", color="var(--gray-11)"),
                rx.input(
                    type="number",
                    value=State.dv_top_n.to(str),
                    on_change=State.set_dv_top_n,
                    width="100%",
                    size="2",
                    font_family=_MONO,
                ),
                rx.text("Maximum number of transcripts to fetch", size="1", color="var(--gray-a8)"),
                spacing="1",
                flex="1",
            ),
            width="100%",
            spacing="4",
        ),
        # Auth error
        rx.cond(
            State.dv_auth_error != "",
            rx.callout(
                State.dv_auth_error,
                icon="triangle_alert",
                color_scheme="red",
                size="1",
                width="100%",
            ),
        ),
        # Device code display
        rx.cond(
            State.dv_show_device_code,
            rx.callout(
                rx.vstack(
                    rx.text("Enter this code to authenticate:", size="2"),
                    rx.text(
                        State.dv_device_code,
                        font_family=_MONO,
                        font_size="24px",
                        font_weight="600",
                        color="var(--green-11)",
                        letter_spacing="2px",
                    ),
                    rx.link(
                        rx.hstack(
                            rx.icon("external-link", size=14),
                            rx.text("Open Microsoft login page", size="2"),
                            spacing="1",
                            align="center",
                        ),
                        href=State.dv_device_code_url,
                        is_external=True,
                        color="var(--green-9)",
                    ),
                    spacing="2",
                    align="center",
                    width="100%",
                ),
                icon="key",
                color_scheme="green",
                size="2",
                width="100%",
            ),
        ),
        # Connect button
        rx.button(
            rx.cond(
                State.dv_is_authenticating,
                rx.hstack(
                    rx.spinner(size="1"),
                    rx.text("Authenticating..."),
                    align="center",
                    spacing="2",
                ),
                rx.hstack(
                    rx.icon("plug", size=15),
                    rx.text("Connect to Dataverse"),
                    align="center",
                    spacing="2",
                ),
            ),
            on_click=State.start_device_flow,
            width="100%",
            size="3",
            color_scheme="green",
            disabled=State.dv_is_authenticating,
            cursor="pointer",
            font_weight="500",
        ),
        spacing="4",
        width="100%",
    )


def _transcript_row(transcript: dict) -> rx.Component:
    return rx.hstack(
        rx.text(
            transcript["created_on"],
            size="2",
            font_family=_MONO,
            color="var(--gray-11)",
            min_width="90px",
        ),
        rx.text(
            transcript["preview"],
            size="2",
            color="var(--gray-a9)",
            flex="1",
            overflow="hidden",
            text_overflow="ellipsis",
            white_space="nowrap",
        ),
        rx.badge(
            transcript["activity_count"].to(str),
            color_scheme="gray",
            variant="soft",
            size="1",
        ),
        rx.icon_button(
            rx.icon("zap", size=14),
            size="1",
            color_scheme="green",
            variant="soft",
            cursor="pointer",
            on_click=State.dv_analyse_transcript(transcript["id"]),
        ),
        width="100%",
        padding="8px 12px",
        border_bottom="1px solid var(--gray-a3)",
        align="center",
        spacing="3",
        _hover={"background": "var(--gray-a2)"},
    )


def import_transcript_list() -> rx.Component:
    return rx.vstack(
        # Connected header
        rx.hstack(
            rx.badge(
                rx.hstack(
                    rx.icon("check-circle", size=12),
                    rx.text("Connected", size="1"),
                    spacing="1",
                    align="center",
                ),
                color_scheme="green",
                variant="soft",
            ),
            rx.spacer(),
            rx.button(
                rx.cond(
                    State.dv_bot_analysing,
                    rx.hstack(
                        rx.spinner(size="1"),
                        rx.text(rx.cond(State.upload_stage != "", State.upload_stage, "Analysing...")),
                        align="center",
                        spacing="2",
                    ),
                    rx.hstack(
                        rx.icon("bot", size=14),
                        rx.text("Analyse Bot"),
                        spacing="2",
                        align="center",
                    ),
                ),
                on_click=State.dv_analyse_bot,
                size="2",
                color_scheme="amber",
                disabled=State.dv_bot_analysing,
                cursor="pointer",
            ),
            rx.button(
                rx.hstack(
                    rx.icon("refresh-cw", size=14),
                    rx.text("Fetch Transcripts"),
                    spacing="2",
                    align="center",
                ),
                on_click=State.dv_fetch_transcripts,
                size="2",
                color_scheme="green",
                disabled=State.dv_is_fetching,
                cursor="pointer",
            ),
            rx.button(
                rx.hstack(
                    rx.icon("unplug", size=14),
                    rx.text("Disconnect"),
                    spacing="2",
                    align="center",
                ),
                on_click=State.dv_disconnect,
                size="2",
                color_scheme="gray",
                variant="outline",
                cursor="pointer",
            ),
            width="100%",
            align="center",
        ),
        # Bot analysis error
        rx.cond(
            State.dv_bot_analyse_error != "",
            rx.callout(
                State.dv_bot_analyse_error,
                icon="triangle_alert",
                color_scheme="red",
                size="1",
                width="100%",
            ),
        ),
        # Bot identifier + filters (still editable when connected)
        _dv_field(
            "Bot Identifier",
            "Copilot Studio → Settings (gear icon) → Session details → Copilot Id",
            "cr123_agentName or UUID",
            State.dv_bot_identifier,
            State.set_dv_bot_identifier,
        ),
        rx.hstack(
            rx.vstack(
                rx.text("Since Date", size="2", font_weight="500", color="var(--gray-11)"),
                rx.input(
                    type="date",
                    value=State.dv_since_date,
                    on_change=State.set_dv_since_date,
                    width="100%",
                    size="2",
                    font_family=_MONO,
                ),
                spacing="1",
                flex="1",
            ),
            rx.vstack(
                rx.text("Top N", size="2", font_weight="500", color="var(--gray-11)"),
                rx.input(
                    type="number",
                    value=State.dv_top_n.to(str),
                    on_change=State.set_dv_top_n,
                    width="100%",
                    size="2",
                    font_family=_MONO,
                ),
                spacing="1",
                flex="1",
            ),
            width="100%",
            spacing="4",
        ),
        # Direct conversation lookup
        rx.separator(size="4"),
        rx.vstack(
            rx.text(
                "Direct Conversation Lookup",
                size="3",
                font_weight="600",
                color="var(--gray-12)",
            ),
            rx.text(
                "Type /debug conversationid in any Copilot Studio chat to get the ID",
                size="1",
                color="var(--gray-a8)",
            ),
            rx.hstack(
                rx.input(
                    placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
                    value=State.dv_conversation_id,
                    on_change=State.set_dv_conversation_id,
                    flex="1",
                    size="2",
                    font_family=_MONO,
                ),
                rx.button(
                    rx.cond(
                        State.dv_single_fetching,
                        rx.hstack(
                            rx.spinner(size="1"),
                            rx.text("Fetching..."),
                            align="center",
                            spacing="2",
                        ),
                        rx.hstack(
                            rx.icon("zap", size=14),
                            rx.text("Fetch & Analyse"),
                            align="center",
                            spacing="2",
                        ),
                    ),
                    on_click=State.dv_fetch_and_analyse_by_id,
                    size="2",
                    color_scheme="green",
                    disabled=State.dv_single_fetching,
                    cursor="pointer",
                ),
                width="100%",
                spacing="2",
            ),
            rx.cond(
                State.dv_single_fetch_error != "",
                rx.callout(
                    State.dv_single_fetch_error,
                    icon="triangle_alert",
                    color_scheme="red",
                    size="1",
                    width="100%",
                ),
            ),
            spacing="2",
            width="100%",
        ),
        rx.separator(size="4"),
        # Fetch error
        rx.cond(
            State.dv_fetch_error != "",
            rx.callout(
                State.dv_fetch_error,
                icon="triangle_alert",
                color_scheme="red",
                size="1",
                width="100%",
            ),
        ),
        # Import error
        rx.cond(
            State.dv_import_error != "",
            rx.callout(
                State.dv_import_error,
                icon="triangle_alert",
                color_scheme="red",
                size="1",
                width="100%",
            ),
        ),
        # Loading spinner
        rx.cond(
            State.dv_is_fetching,
            rx.center(
                rx.hstack(
                    rx.spinner(size="2"),
                    rx.text("Fetching transcripts...", size="2", color="var(--gray-a9)"),
                    spacing="2",
                    align="center",
                ),
                width="100%",
                padding="24px",
            ),
        ),
        # Processing spinner
        rx.cond(
            State.dv_import_processing,
            rx.center(
                rx.hstack(
                    rx.spinner(size="2"),
                    rx.text("Analysing transcript...", size="2", color="var(--gray-a9)"),
                    spacing="2",
                    align="center",
                ),
                width="100%",
                padding="24px",
            ),
        ),
        # Transcript list
        rx.cond(
            State.dv_has_transcripts,
            rx.box(
                # Header row
                rx.hstack(
                    rx.text("Date", size="1", color="var(--gray-a8)", font_weight="500", min_width="90px"),
                    rx.text("Preview", size="1", color="var(--gray-a8)", font_weight="500", flex="1"),
                    rx.text("Acts", size="1", color="var(--gray-a8)", font_weight="500"),
                    rx.box(width="28px"),  # spacer for action column
                    width="100%",
                    padding="4px 12px",
                    spacing="3",
                ),
                rx.foreach(State.dv_transcripts, _transcript_row),
                width="100%",
                border="1px solid var(--gray-a4)",
                border_radius="8px",
                overflow="hidden",
            ),
        ),
        spacing="4",
        width="100%",
    )


def import_form() -> rx.Component:
    return rx.center(
        rx.vstack(
            # Heading
            rx.vstack(
                rx.heading(
                    "Dataverse Import",
                    size="7",
                    font_family=_MONO,
                    font_weight="600",
                    color="var(--gray-12)",
                    letter_spacing="-0.5px",
                ),
                rx.text(
                    "Connect to Dataverse and fetch conversation transcripts",
                    size="2",
                    color="var(--gray-a9)",
                    text_align="center",
                ),
                spacing="2",
                align="center",
            ),
            # Card
            rx.box(
                rx.cond(
                    State.dv_is_connected,
                    import_transcript_list(),
                    import_connection_form(),
                ),
                padding="28px",
                background="var(--gray-a2)",
                border="1px solid var(--gray-a4)",
                border_radius="16px",
                max_width="560px",
                width="100%",
                box_shadow="0 8px 32px rgba(0,0,0,0.35)",
            ),
            spacing="6",
            align="center",
            width="100%",
        ),
        width="100%",
        padding="64px 24px",
        min_height="calc(100vh - 54px)",
    )


# ── Solution Tools components ─────────────────────────────────────────────────

SOL_UPLOAD_ID = "sol_upload"


def _severity_badge(severity: str) -> rx.Component:
    return rx.badge(
        severity,
        color_scheme=rx.match(
            severity,
            ("pass", "green"),
            ("warning", "amber"),
            ("fail", "red"),
            ("info", "blue"),
            "gray",
        ),
        variant="soft",
        size="1",
    )


def _check_result_row(result: dict) -> rx.Component:
    return rx.box(
        rx.hstack(
            _severity_badge(result["severity"]),
            rx.badge(result["category"], color_scheme="gray", variant="outline", size="1"),
            rx.text(result["title"], size="2", font_weight="500", color="var(--gray-12)", flex="1"),
            width="100%",
            align="center",
            spacing="2",
        ),
        rx.text(result["detail"], size="1", color="var(--gray-a9)", padding_top="4px", padding_left="80px"),
        padding="10px 12px",
        border_bottom="1px solid var(--gray-a3)",
        _hover={"background": "var(--gray-a2)"},
    )


def _validate_result_row(result: dict) -> rx.Component:
    return rx.box(
        rx.hstack(
            _severity_badge(result["severity"]),
            rx.text(result["title"], size="2", font_weight="500", color="var(--gray-12)", flex="1"),
            width="100%",
            align="center",
            spacing="2",
        ),
        rx.text(result["detail"], size="1", color="var(--gray-a9)", padding_top="4px", padding_left="60px"),
        padding="10px 12px",
        border_bottom="1px solid var(--gray-a3)",
        _hover={"background": "var(--gray-a2)"},
    )


def _tab_button(label: str, tab_key: str) -> rx.Component:
    return rx.button(
        label,
        variant=rx.cond(State.sol_active_tab == tab_key, "solid", "outline"),
        color_scheme="green",
        size="2",
        on_click=State.set_sol_active_tab(tab_key),
        cursor="pointer",
    )


def _sol_check_tab() -> rx.Component:
    return rx.vstack(
        rx.cond(
            State.sol_check_error != "",
            rx.vstack(
                rx.callout(State.sol_check_error, icon="triangle_alert", color_scheme="red", size="1", width="100%"),
                rx.button(
                    rx.hstack(rx.icon("rotate-ccw", size=14), rx.text("Retry"), align="center", spacing="2"),
                    on_click=State.run_solution_check,
                    size="2",
                    variant="outline",
                    color_scheme="red",
                    cursor="pointer",
                ),
                spacing="2",
                width="100%",
            ),
        ),
        rx.cond(
            State.sol_is_checking,
            rx.center(
                rx.hstack(
                    rx.spinner(size="2"),
                    rx.text("Running checks...", size="2", color="var(--gray-a9)"),
                    spacing="2",
                    align="center",
                ),
                padding="24px",
                width="100%",
            ),
            rx.vstack(
                rx.cond(
                    State.sol_check_agent_name != "",
                    rx.hstack(
                        rx.icon("bot", size=16, color="var(--green-9)"),
                        rx.text(
                            State.sol_check_agent_name,
                            size="3",
                            font_weight="600",
                            color="var(--gray-12)",
                            font_family=_MONO,
                        ),
                        rx.text(" / ", size="2", color="var(--gray-a8)"),
                        rx.text(State.sol_check_solution_name, size="2", color="var(--gray-a9)", font_family=_MONO),
                        align="center",
                        spacing="2",
                    ),
                ),
                rx.hstack(
                    rx.badge(
                        rx.hstack(
                            rx.icon("check-circle", size=12), rx.text(State.sol_check_pass), spacing="1", align="center"
                        ),
                        color_scheme="green",
                        variant="soft",
                        size="2",
                    ),
                    rx.badge(
                        rx.hstack(
                            rx.icon("alert-triangle", size=12),
                            rx.text(State.sol_check_warn),
                            spacing="1",
                            align="center",
                        ),
                        color_scheme="amber",
                        variant="soft",
                        size="2",
                    ),
                    rx.badge(
                        rx.hstack(
                            rx.icon("x-circle", size=12), rx.text(State.sol_check_fail), spacing="1", align="center"
                        ),
                        color_scheme="red",
                        variant="soft",
                        size="2",
                    ),
                    rx.badge(
                        rx.hstack(rx.icon("info", size=12), rx.text(State.sol_check_info), spacing="1", align="center"),
                        color_scheme="blue",
                        variant="soft",
                        size="2",
                    ),
                    spacing="2",
                    align="center",
                ),
                rx.hstack(
                    rx.button(
                        "All",
                        variant=rx.cond(State.sol_check_active_category == "All", "solid", "outline"),
                        color_scheme="gray",
                        size="1",
                        on_click=State.set_sol_check_active_category("All"),
                        cursor="pointer",
                    ),
                    rx.button(
                        "Solution",
                        variant=rx.cond(State.sol_check_active_category == "Solution", "solid", "outline"),
                        color_scheme="gray",
                        size="1",
                        on_click=State.set_sol_check_active_category("Solution"),
                        cursor="pointer",
                    ),
                    rx.button(
                        "Agent",
                        variant=rx.cond(State.sol_check_active_category == "Agent", "solid", "outline"),
                        color_scheme="gray",
                        size="1",
                        on_click=State.set_sol_check_active_category("Agent"),
                        cursor="pointer",
                    ),
                    rx.button(
                        "Topics",
                        variant=rx.cond(State.sol_check_active_category == "Topics", "solid", "outline"),
                        color_scheme="gray",
                        size="1",
                        on_click=State.set_sol_check_active_category("Topics"),
                        cursor="pointer",
                    ),
                    rx.button(
                        "Knowledge",
                        variant=rx.cond(State.sol_check_active_category == "Knowledge", "solid", "outline"),
                        color_scheme="gray",
                        size="1",
                        on_click=State.set_sol_check_active_category("Knowledge"),
                        cursor="pointer",
                    ),
                    rx.button(
                        "Security",
                        variant=rx.cond(State.sol_check_active_category == "Security", "solid", "outline"),
                        color_scheme="gray",
                        size="1",
                        on_click=State.set_sol_check_active_category("Security"),
                        cursor="pointer",
                    ),
                    spacing="2",
                    flex_wrap="wrap",
                ),
                rx.box(
                    rx.foreach(State.sol_filtered_results, _check_result_row),
                    width="100%",
                    border="1px solid var(--gray-a4)",
                    border_radius="8px",
                    overflow="hidden",
                ),
                spacing="4",
                width="100%",
            ),
        ),
        spacing="4",
        width="100%",
    )


def _sol_validate_tab() -> rx.Component:
    return rx.vstack(
        rx.cond(
            State.sol_validate_error != "",
            rx.vstack(
                rx.callout(State.sol_validate_error, icon="triangle_alert", color_scheme="red", size="1", width="100%"),
                rx.button(
                    rx.hstack(rx.icon("rotate-ccw", size=14), rx.text("Retry"), align="center", spacing="2"),
                    on_click=State.run_solution_validate,
                    size="2",
                    variant="outline",
                    color_scheme="red",
                    cursor="pointer",
                ),
                spacing="2",
                width="100%",
            ),
        ),
        rx.cond(
            State.sol_is_validating,
            rx.center(
                rx.hstack(
                    rx.spinner(size="2"),
                    rx.text("Validating instructions...", size="2", color="var(--gray-a9)"),
                    spacing="2",
                    align="center",
                ),
                padding="24px",
                width="100%",
            ),
            rx.vstack(
                rx.cond(
                    State.sol_validate_model_display != "",
                    rx.hstack(
                        rx.icon("cpu", size=16, color="var(--green-9)"),
                        rx.text("Model: ", size="2", color="var(--gray-a9)"),
                        rx.text(
                            State.sol_validate_model_display,
                            size="2",
                            font_weight="600",
                            color="var(--gray-12)",
                            font_family=_MONO,
                        ),
                        align="center",
                        spacing="2",
                    ),
                ),
                rx.box(
                    rx.foreach(State.sol_validate_results, _validate_result_row),
                    width="100%",
                    border="1px solid var(--gray-a4)",
                    border_radius="8px",
                    overflow="hidden",
                ),
                rx.cond(
                    State.sol_validate_best_practices_md != "",
                    rx.box(
                        rx.heading(
                            "Best Practices", size="3", font_family=_MONO, color="var(--gray-12)", padding_bottom="8px"
                        ),
                        rx.foreach(State.sol_validate_bp_segments, render_segment),
                        padding_top="16px",
                    ),
                ),
                spacing="4",
                width="100%",
            ),
        ),
        spacing="4",
        width="100%",
    )


def _sol_deps_tab() -> rx.Component:
    return rx.vstack(
        rx.cond(
            State.sol_deps_error != "",
            rx.vstack(
                rx.callout(State.sol_deps_error, icon="triangle_alert", color_scheme="red", size="1", width="100%"),
                rx.button(
                    rx.hstack(rx.icon("rotate-ccw", size=14), rx.text("Retry"), align="center", spacing="2"),
                    on_click=State.run_deps_analysis,
                    size="2",
                    variant="outline",
                    color_scheme="red",
                    cursor="pointer",
                ),
                spacing="2",
                width="100%",
            ),
        ),
        rx.cond(
            State.sol_is_deps_analyzing,
            rx.center(
                rx.hstack(
                    rx.spinner(size="2"),
                    rx.text("Analysing dependencies...", size="2", color="var(--gray-a9)"),
                    spacing="2",
                    align="center",
                ),
                padding="24px",
                width="100%",
            ),
            rx.box(rx.foreach(State.sol_deps_segments, render_segment), width="100%"),
        ),
        spacing="4",
        width="100%",
    )


def _sol_rename_tab() -> rx.Component:
    return rx.vstack(
        rx.cond(
            State.sol_detected_info.length() > 0,  # type: ignore
            rx.callout(
                rx.vstack(
                    rx.text("Detected from solution:", size="2", font_weight="500"),
                    rx.text(
                        rx.text.strong("Agent: "),
                        State.sol_detected_info["bot_display_name"],
                        size="1",
                        color="var(--gray-a9)",
                    ),
                    rx.text(
                        rx.text.strong("Solution: "),
                        State.sol_detected_info["solution_unique_name"],
                        size="1",
                        color="var(--gray-a9)",
                    ),
                    spacing="1",
                ),
                icon="info",
                color_scheme="blue",
                size="1",
                width="100%",
            ),
        ),
        rx.vstack(
            rx.text("New Agent Name", size="2", font_weight="500", color="var(--gray-11)"),
            rx.input(
                placeholder="My Renamed Agent",
                value=State.sol_rename_new_agent,
                on_change=State.set_sol_rename_new_agent,
                width="100%",
                size="2",
                font_family=_MONO,
            ),
            rx.text("Display name for the agent", size="1", color="var(--gray-a8)"),
            spacing="1",
            width="100%",
        ),
        rx.vstack(
            rx.text("New Solution Name", size="2", font_weight="500", color="var(--gray-11)"),
            rx.input(
                placeholder="MyRenamedSolution",
                value=State.sol_rename_new_solution,
                on_change=State.set_sol_rename_new_solution,
                width="100%",
                size="2",
                font_family=_MONO,
            ),
            rx.text("PascalCase, letters/digits/underscores only (e.g. MyNewBot)", size="1", color="var(--gray-a8)"),
            spacing="1",
            width="100%",
        ),
        rx.cond(
            State.sol_rename_error != "",
            rx.vstack(
                rx.callout(State.sol_rename_error, icon="triangle_alert", color_scheme="red", size="1", width="100%"),
                rx.button(
                    rx.hstack(rx.icon("rotate-ccw", size=14), rx.text("Retry"), align="center", spacing="2"),
                    on_click=State.run_rename,
                    size="2",
                    variant="outline",
                    color_scheme="red",
                    cursor="pointer",
                ),
                spacing="2",
                width="100%",
            ),
        ),
        rx.button(
            rx.cond(
                State.sol_is_renaming,
                rx.hstack(rx.spinner(size="1"), rx.text("Renaming..."), align="center", spacing="2"),
                rx.hstack(rx.icon("pen-line", size=15), rx.text("Rename Solution"), align="center", spacing="2"),
            ),
            on_click=State.run_rename,
            width="100%",
            size="3",
            color_scheme="green",
            disabled=State.sol_is_renaming,
            cursor="pointer",
            font_weight="500",
        ),
        rx.cond(
            State.sol_rename_result.length() > 0,  # type: ignore
            rx.vstack(
                rx.callout(
                    rx.vstack(
                        rx.text("Rename complete!", size="2", font_weight="600", color="var(--green-11)"),
                        rx.text(
                            rx.text.strong("Agent: "),
                            State.sol_rename_result["old_agent_name"],
                            " -> ",
                            State.sol_rename_result["new_agent_name"],
                            size="1",
                        ),
                        rx.text(
                            rx.text.strong("Solution: "),
                            State.sol_rename_result["old_solution_name"],
                            " -> ",
                            State.sol_rename_result["new_solution_name"],
                            size="1",
                        ),
                        rx.text(
                            rx.text.strong("Files modified: "),
                            State.sol_rename_result["files_modified"].to(str),
                            " | Folders renamed: ",
                            State.sol_rename_result["folders_renamed"].to(str),
                            size="1",
                        ),
                        spacing="1",
                    ),
                    icon="check-circle",
                    color_scheme="green",
                    size="1",
                    width="100%",
                ),
                rx.button(
                    rx.hstack(
                        rx.icon("download", size=15), rx.text("Download Renamed ZIP"), align="center", spacing="2"
                    ),
                    on_click=State.download_renamed_zip,
                    width="100%",
                    size="3",
                    color_scheme="green",
                    variant="outline",
                    cursor="pointer",
                    font_weight="500",
                ),
                spacing="3",
                width="100%",
            ),
        ),
        spacing="4",
        width="100%",
    )


def solution_tools_form() -> rx.Component:
    return rx.center(
        rx.vstack(
            rx.vstack(
                rx.heading(
                    "Solution Tools",
                    size="7",
                    font_family=_MONO,
                    font_weight="600",
                    color="var(--gray-12)",
                    letter_spacing="-0.5px",
                ),
                rx.text(
                    "Check, validate, analyse dependencies, or rename a Power Platform solution ZIP",
                    size="2",
                    color="var(--gray-a9)",
                    text_align="center",
                ),
                spacing="2",
                align="center",
            ),
            rx.box(
                rx.vstack(
                    rx.cond(
                        State.sol_has_zip,
                        rx.hstack(
                            rx.icon("file-archive", size=16, color="var(--green-9)"),
                            rx.text(State.sol_zip_name, size="2", font_family=_MONO, color="var(--gray-11)", flex="1"),
                            rx.button(
                                rx.icon("x", size=14),
                                variant="ghost",
                                size="1",
                                color_scheme="gray",
                                on_click=State.sol_clear,
                                cursor="pointer",
                            ),
                            width="100%",
                            align="center",
                            padding="8px 12px",
                            background="var(--green-a2)",
                            border="1px solid var(--green-a5)",
                            border_radius="8px",
                        ),
                        rx.vstack(
                            rx.upload(
                                rx.vstack(
                                    rx.box(
                                        rx.icon("upload", size=28, color="var(--green-9)"),
                                        padding="14px",
                                        background="var(--green-a3)",
                                        border_radius="50%",
                                        border="1px solid var(--green-a5)",
                                        display="inline-flex",
                                    ),
                                    rx.text(
                                        "Drop a solution ZIP or click to browse",
                                        size="3",
                                        color="var(--gray-11)",
                                        font_weight="500",
                                    ),
                                    rx.text("Power Platform solution export (.zip)", size="2", color="var(--gray-a8)"),
                                    align="center",
                                    spacing="3",
                                ),
                                id=SOL_UPLOAD_ID,
                                border="1.5px dashed var(--green-a6)",
                                border_radius="12px",
                                padding="48px 32px",
                                width="100%",
                                cursor="pointer",
                                multiple=False,
                                accept={".zip": ["application/zip"]},
                                background="var(--green-a1)",
                                transition="all 0.15s ease",
                            ),
                            rx.button(
                                rx.hstack(
                                    rx.icon("zap", size=15), rx.text("Upload & Analyse"), align="center", spacing="2"
                                ),
                                on_click=State.handle_solution_upload(rx.upload_files(upload_id=SOL_UPLOAD_ID)),
                                width="100%",
                                size="3",
                                color_scheme="green",
                                cursor="pointer",
                                font_weight="500",
                            ),
                            spacing="4",
                            width="100%",
                        ),
                    ),
                    rx.cond(
                        State.sol_has_zip,
                        rx.vstack(
                            rx.separator(size="4"),
                            rx.hstack(
                                _tab_button("Check", "check"),
                                _tab_button("Validate", "validate"),
                                _tab_button("Dependencies", "deps"),
                                _tab_button("Rename", "rename"),
                                spacing="2",
                                flex_wrap="wrap",
                            ),
                            rx.match(
                                State.sol_active_tab,
                                ("check", _sol_check_tab()),
                                ("validate", _sol_validate_tab()),
                                ("deps", _sol_deps_tab()),
                                ("rename", _sol_rename_tab()),
                                _sol_check_tab(),
                            ),
                            spacing="4",
                            width="100%",
                        ),
                    ),
                    spacing="4",
                    width="100%",
                ),
                padding="28px",
                background="var(--gray-a2)",
                border="1px solid var(--gray-a4)",
                border_radius="16px",
                max_width="800px",
                width="100%",
                box_shadow="0 8px 32px rgba(0,0,0,0.35)",
            ),
            spacing="6",
            align="center",
            width="100%",
        ),
        width="100%",
        padding="64px 24px",
        min_height="calc(100vh - 54px)",
    )
