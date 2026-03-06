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
                    rx.icon("scan-search", size=24, color="var(--cyan-9)"),
                    padding="12px",
                    background="var(--cyan-a3)",
                    border_radius="10px",
                    border="1px solid var(--cyan-a5)",
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
                    color_scheme="cyan",
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
        width="380px",
        padding="32px",
        background="var(--gray-a2)",
        border="1px solid var(--gray-a4)",
        box_shadow=rx.color_mode_cond(
            "0 0 0 1px rgba(34,211,238,0.15), 0 8px 24px rgba(0,0,0,0.1)",
            "0 0 0 1px var(--cyan-a3), 0 24px 48px rgba(0,0,0,0.5)",
        ),
        border_radius="16px",
    )


def navbar() -> rx.Component:
    return rx.hstack(
        # Logo
        rx.hstack(
            rx.icon("scan-search", size=17, color="var(--cyan-9)"),
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
        rx.spacer(),
        # Right side
        rx.hstack(
            rx.box(
                rx.text(
                    State.username,
                    size="1",
                    color="var(--cyan-11)",
                    font_family=_MONO,
                ),
                padding="4px 10px",
                background="var(--cyan-a3)",
                border="1px solid var(--cyan-a5)",
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
        background="rgba(12, 14, 20, 0.75)",
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
                    rx.select(
                        ["Bot Export (.zip)", "Bot Export (individual files)", "Transcript (.json)"],
                        value=rx.cond(
                            State.upload_type == "bot_zip",
                            "Bot Export (.zip)",
                            rx.cond(
                                State.upload_type == "bot_files",
                                "Bot Export (individual files)",
                                "Transcript (.json)",
                            ),
                        ),
                        on_change=State.set_upload_type,
                        width="100%",
                        size="3",
                    ),
                    rx.upload(
                        rx.vstack(
                            rx.box(
                                rx.icon("upload", size=28, color="var(--cyan-9)"),
                                padding="14px",
                                background="var(--cyan-a3)",
                                border_radius="50%",
                                border="1px solid var(--cyan-a5)",
                                display="inline-flex",
                            ),
                            rx.text(
                                "Drag & drop or click to browse",
                                size="3",
                                color="var(--gray-11)",
                                font_weight="500",
                            ),
                            rx.cond(
                                State.upload_type == "bot_zip",
                                rx.text(".zip bot export", size="2", color="var(--gray-a8)"),
                                rx.cond(
                                    State.upload_type == "bot_files",
                                    rx.text("botContent.yml + dialog.json", size="2", color="var(--gray-a8)"),
                                    rx.text(".json transcript", size="2", color="var(--gray-a8)"),
                                ),
                            ),
                            align="center",
                            spacing="3",
                        ),
                        id=UPLOAD_ID,
                        border="1.5px dashed var(--cyan-a6)",
                        border_radius="12px",
                        padding="48px 32px",
                        width="100%",
                        cursor="pointer",
                        multiple=True,
                        background="var(--cyan-a1)",
                        transition="all 0.15s ease",
                    ),
                    rx.foreach(
                        rx.selected_files(UPLOAD_ID),
                        lambda f: rx.hstack(
                            rx.icon("file", size=12, color="var(--cyan-9)"),
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
                        color_scheme="cyan",
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
                    color="var(--cyan-11)",
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
                rx.button(
                    rx.icon("plus", size=14),
                    rx.text("New Upload"),
                    variant="soft",
                    size="2",
                    color_scheme="cyan",
                    on_click=State.new_upload,
                    cursor="pointer",
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
