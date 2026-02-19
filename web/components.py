import reflex as rx

from web.mermaid import render_segment
from web.state import State

UPLOAD_ID = "file_upload"


def login_form() -> rx.Component:
    return rx.card(
        rx.form(
            rx.vstack(
                rx.heading("Agent Analyser", size="5", text_align="center", width="100%"),
                rx.text("Sign in to continue", size="2", color_scheme="gray", text_align="center", width="100%"),
                rx.separator(),
                rx.input(
                    placeholder="Username",
                    value=State.username,
                    on_change=State.set_username,
                    width="100%",
                ),
                rx.input(
                    placeholder="Password",
                    type="password",
                    value=State.password,
                    on_change=State.set_password,
                    width="100%",
                ),
                rx.cond(
                    State.auth_error != "",
                    rx.callout(
                        State.auth_error,
                        icon="triangle_alert",
                        color_scheme="red",
                        width="100%",
                    ),
                ),
                rx.button(
                    "Sign In",
                    type="submit",
                    width="100%",
                    size="3",
                ),
                spacing="4",
                width="100%",
            ),
            on_submit=lambda _: State.login(),
            reset_on_submit=False,
        ),
        width="400px",
    )


def navbar() -> rx.Component:
    return rx.hstack(
        rx.heading("Agent Analyser", size="4"),
        rx.spacer(),
        rx.text(State.username, size="2", color_scheme="gray"),
        rx.button(
            "Logout",
            variant="ghost",
            size="2",
            on_click=State.logout,
        ),
        width="100%",
        padding="16px 24px",
        border_bottom="1px solid var(--gray-a5)",
        align="center",
    )


def upload_form() -> rx.Component:
    return rx.center(
        rx.card(
            rx.vstack(
                rx.heading("Upload Bot Export", size="4"),
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
                ),
                rx.upload(
                    rx.vstack(
                        rx.icon("upload", size=40, color="var(--gray-a9)"),
                        rx.text("Drag & drop files here or click to browse", size="2", color_scheme="gray"),
                        rx.cond(
                            State.upload_type == "bot_zip",
                            rx.text("Upload a .zip bot export", size="1", color_scheme="gray"),
                            rx.cond(
                                State.upload_type == "bot_files",
                                rx.text("Upload botContent.yml + dialog.json", size="1", color_scheme="gray"),
                                rx.text("Upload a transcript .json file", size="1", color_scheme="gray"),
                            ),
                        ),
                        align="center",
                        spacing="2",
                    ),
                    id=UPLOAD_ID,
                    border="2px dashed var(--gray-a6)",
                    border_radius="var(--radius-3)",
                    padding="40px 24px",
                    width="100%",
                    cursor="pointer",
                    multiple=True,
                ),
                rx.foreach(
                    rx.selected_files(UPLOAD_ID),
                    lambda f: rx.text(f, size="1", color_scheme="gray"),
                ),
                rx.cond(
                    State.upload_error != "",
                    rx.callout(
                        State.upload_error,
                        icon="triangle_alert",
                        color_scheme="red",
                        width="100%",
                    ),
                ),
                rx.button(
                    rx.cond(
                        State.is_processing,
                        rx.hstack(rx.spinner(size="1"), rx.text("Analysing..."), align="center", spacing="2"),
                        rx.text("Analyse"),
                    ),
                    on_click=State.handle_upload(rx.upload_files(upload_id=UPLOAD_ID)),
                    width="100%",
                    size="3",
                    disabled=State.is_processing,
                ),
                spacing="4",
                width="100%",
            ),
            max_width="600px",
            width="100%",
        ),
        width="100%",
        padding="40px 24px",
    )


def report_viewer() -> rx.Component:
    return rx.box(
        rx.hstack(
            rx.heading(State.report_title, size="4"),
            rx.spacer(),
            rx.button(
                rx.icon("download", size=16),
                "Download .md",
                variant="outline",
                size="2",
                on_click=State.download_report,
            ),
            rx.button(
                rx.icon("plus", size=16),
                "New Upload",
                variant="soft",
                size="2",
                on_click=State.new_upload,
            ),
            width="100%",
            align="center",
            padding_bottom="16px",
        ),
        rx.separator(),
        rx.box(
            rx.foreach(State.report_segments, render_segment),
            padding_top="16px",
        ),
        max_width="1200px",
        width="100%",
        padding="24px",
        margin="0 auto",
    )


