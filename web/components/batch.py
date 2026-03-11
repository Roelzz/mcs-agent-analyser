import reflex as rx

from web.components.common import _MONO
from web.mermaid import render_segment
from web.state import State
from web.state._batch import BATCH_UPLOAD_ID


def batch_form() -> rx.Component:
    return rx.center(
        rx.vstack(
            # Heading
            rx.vstack(
                rx.heading(
                    "Batch Analytics",
                    size="7",
                    font_family=_MONO,
                    font_weight="600",
                    color="var(--gray-12)",
                    letter_spacing="-0.5px",
                ),
                rx.text(
                    "Upload multiple transcripts to see aggregate patterns",
                    size="2",
                    color="var(--gray-a9)",
                    text_align="center",
                ),
                spacing="2",
                align="center",
            ),
            # Upload card
            rx.box(
                rx.vstack(
                    rx.upload(
                        rx.vstack(
                            rx.box(
                                rx.icon("bar-chart-3", size=28, color="var(--green-9)"),
                                padding="14px",
                                background="var(--green-a3)",
                                border_radius="50%",
                                border="1px solid var(--green-a5)",
                                display="inline-flex",
                            ),
                            rx.text(
                                "Drag & drop transcript files",
                                size="3",
                                color="var(--gray-11)",
                                font_weight="500",
                            ),
                            rx.text(
                                "Multiple .json transcript files",
                                size="2",
                                color="var(--gray-a8)",
                            ),
                            align="center",
                            spacing="3",
                        ),
                        id=BATCH_UPLOAD_ID,
                        border="1.5px dashed var(--green-a6)",
                        border_radius="12px",
                        padding="48px 32px",
                        width="100%",
                        cursor="pointer",
                        multiple=True,
                        accept={".json": ["application/json"]},
                        background="var(--green-a1)",
                        transition="all 0.15s ease",
                    ),
                    rx.foreach(
                        rx.selected_files(BATCH_UPLOAD_ID),
                        lambda f: rx.hstack(
                            rx.icon("file", size=12, color="var(--green-9)"),
                            rx.text(f, size="1", color="var(--gray-a9)"),
                            spacing="1",
                            align="center",
                        ),
                    ),
                    rx.cond(
                        State.batch_error != "",
                        rx.callout(
                            State.batch_error,
                            icon="triangle_alert",
                            color_scheme="red",
                            size="1",
                            width="100%",
                        ),
                    ),
                    rx.button(
                        rx.cond(
                            State.batch_is_processing,
                            rx.hstack(
                                rx.spinner(size="1"),
                                rx.text(f"Processing {State.batch_count} transcripts..."),
                                align="center",
                                spacing="2",
                            ),
                            rx.hstack(
                                rx.icon("zap", size=15),
                                rx.text("Analyse Batch"),
                                align="center",
                                spacing="2",
                            ),
                        ),
                        on_click=State.handle_batch_upload(rx.upload_files(upload_id=BATCH_UPLOAD_ID)),
                        width="100%",
                        size="3",
                        color_scheme="green",
                        disabled=State.batch_is_processing,
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
            # Summary cards (shown when report is ready)
            rx.cond(
                State.batch_report_md != "",
                rx.vstack(
                    rx.hstack(
                        rx.button(
                            rx.hstack(
                                rx.icon("trash-2", size=14),
                                rx.text("Clear"),
                                spacing="2",
                                align="center",
                            ),
                            on_click=State.clear_batch,
                            variant="outline",
                            color_scheme="gray",
                            size="2",
                            cursor="pointer",
                        ),
                        justify="end",
                        width="100%",
                    ),
                    rx.box(
                        rx.foreach(State.batch_segments, render_segment),
                        width="100%",
                        max_width="960px",
                    ),
                    spacing="4",
                    width="100%",
                    max_width="960px",
                    align="center",
                ),
            ),
            spacing="6",
            align="center",
            width="100%",
        ),
        width="100%",
        padding="64px 24px",
        min_height="calc(100vh - 54px)",
    )
