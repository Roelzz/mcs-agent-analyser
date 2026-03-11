import reflex as rx

from web.components.common import UPLOAD_ID, _MONO
from web.state import State


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
