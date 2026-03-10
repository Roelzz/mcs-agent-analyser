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


def navbar() -> rx.Component:
    return rx.hstack(
        # Logo
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
        # Nav links
        rx.hstack(
            rx.link(
                rx.hstack(
                    rx.icon("upload", size=14, color="var(--gray-a9)"),
                    rx.text("Upload", size="2", color="var(--gray-a9)"),
                    spacing="1",
                    align="center",
                ),
                href="/upload",
                underline="none",
            ),
            rx.link(
                rx.hstack(
                    rx.icon("database", size=14, color="var(--gray-a9)"),
                    rx.text("Dataverse", size="2", color="var(--gray-a9)"),
                    spacing="1",
                    align="center",
                ),
                href="/import",
                underline="none",
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
            "rgba(255, 255, 255, 0.75)",   # light
            "rgba(12, 14, 20, 0.75)",      # dark
        ),
        backdrop_filter="blur(12px)",
        align="center",
        position="sticky",
        top="0",
        z_index="100",
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
                                rx.text("Analysing..."),
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
                                rx.text("Analysing..."),
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
                rx.button(
                    rx.icon("download", size=14),
                    rx.text("Download"),
                    variant="outline",
                    size="2",
                    color_scheme="gray",
                    on_click=State.download_report,
                    cursor="pointer",
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
                    State.dv_is_connected,
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
                        rx.text("New Upload"),
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
                        rx.text("Analysing..."),
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
