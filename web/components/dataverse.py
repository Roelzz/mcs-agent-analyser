import reflex as rx

from web.components.common import _MONO
from web.state import State


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
                                "A license that includes Dataverse access — Copilot Studio, Power Apps Premium, or Dynamics 365 Enterprise",
                            ),
                            rx.el.li(
                                "Conversation transcripts enabled on your copilot — in Copilot Studio go to ",
                                rx.text.strong("Settings → Agent → Conversation transcripts"),
                                " and toggle it on. Transcripts are off by default and ",
                                rx.text.strong("do not backfill"),
                                " — only conversations after enabling are captured. "
                                "Transcripts appear ~30 minutes after a conversation ends.",
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
                                "Your session details (Tenant ID, Instance URL, Copilot ID) — find them in Copilot Studio under ",
                                rx.text.strong("Settings (gear icon) → Session details"),
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
                        "Security roles",
                        size="2",
                        font_weight="600",
                        color="var(--gray-12)",
                    ),
                    rx.box(
                        rx.el.ul(
                            rx.el.li(
                                rx.text.strong("System Administrator"),
                                " — full access to all tables by default",
                            ),
                            rx.el.li(
                                rx.text.strong("Bot Transcript Viewer"),
                                " — read-only access to transcripts (can be assigned by your admin)",
                            ),
                            rx.el.li(
                                "For custom roles: ask your admin to add Read privilege on ",
                                rx.code("Bot"),
                                ", ",
                                rx.code("BotComponent"),
                                ", and ",
                                rx.code("ConversationTranscript"),
                                " tables",
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
                                "By default, this tool uses the Microsoft Azure CLI client ID — no app registration needed for most tenants",
                            ),
                            rx.el.li(
                                "If your tenant blocks external client IDs (Conditional Access), you'll need to register your own app in Entra ID — see the README for step-by-step instructions",
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
                    rx.text(
                        "Troubleshooting",
                        size="2",
                        font_weight="600",
                        color="var(--gray-12)",
                    ),
                    rx.box(
                        rx.el.ul(
                            rx.el.li(
                                rx.text.strong("403 error"),
                                " — missing Read permission on Dataverse tables. Ask your admin for the right security role.",
                            ),
                            rx.el.li(
                                rx.text.strong("Empty transcript list"),
                                " — transcripts not enabled, or conversations are too recent (wait ~30 min).",
                            ),
                            rx.el.li(
                                rx.text.strong("Auth error / AADSTS65002"),
                                " — your tenant may block the default client ID. Register your own app (see README).",
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
        rx.checkbox(
            checked=transcript["selected"],
            on_change=lambda _val: State.dv_toggle_select(transcript["id"]),
            size="1",
            color_scheme="green",
        ),
        rx.text(
            transcript["created_on"],
            size="2",
            font_family=_MONO,
            color="var(--gray-11)",
            min_width="90px",
        ),
        rx.text(
            transcript["short_id"],
            size="1",
            font_family=_MONO,
            color="var(--gray-a8)",
            min_width="75px",
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
        # Batch error
        rx.cond(
            State.dv_batch_error != "",
            rx.callout(
                State.dv_batch_error,
                icon="triangle_alert",
                color_scheme="red",
                size="1",
                width="100%",
            ),
        ),
        # Batch processing spinner
        rx.cond(
            State.dv_batch_processing,
            rx.center(
                rx.hstack(
                    rx.spinner(size="2"),
                    rx.text("Running batch analysis...", size="2", color="var(--gray-a9)"),
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
                    rx.checkbox(
                        checked=State.dv_all_selected,
                        on_change=lambda _val: State.dv_toggle_select_all(),
                        size="1",
                        color_scheme="green",
                    ),
                    rx.text("Date", size="1", color="var(--gray-a8)", font_weight="500", min_width="90px"),
                    rx.text("ID", size="1", color="var(--gray-a8)", font_weight="500", min_width="75px"),
                    rx.text("Preview", size="1", color="var(--gray-a8)", font_weight="500", flex="1"),
                    rx.text("Acts", size="1", color="var(--gray-a8)", font_weight="500"),
                    rx.box(width="28px"),  # spacer for action column
                    width="100%",
                    padding="4px 12px",
                    spacing="3",
                ),
                # Batch action bar
                rx.cond(
                    State.dv_has_selection,
                    rx.hstack(
                        rx.text(
                            State.dv_selected_count.to(str) + " selected",
                            size="2",
                            font_weight="500",
                            color="var(--green-11)",
                        ),
                        rx.spacer(),
                        rx.button(
                            rx.cond(
                                State.dv_batch_processing,
                                rx.hstack(
                                    rx.spinner(size="1"),
                                    rx.text("Processing..."),
                                    align="center",
                                    spacing="2",
                                ),
                                rx.hstack(
                                    rx.icon("bar-chart-3", size=14),
                                    rx.text("Run Batch Analysis"),
                                    align="center",
                                    spacing="2",
                                ),
                            ),
                            on_click=State.dv_run_batch_analysis,
                            size="2",
                            color_scheme="green",
                            disabled=State.dv_batch_processing,
                            cursor="pointer",
                        ),
                        width="100%",
                        padding="8px 12px",
                        align="center",
                        background="var(--green-a2)",
                        border_bottom="1px solid var(--gray-a3)",
                    ),
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
