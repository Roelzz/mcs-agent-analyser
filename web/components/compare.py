"""Bot comparison UI component."""

import reflex as rx

from web.components.common import _MONO
from web.mermaid import render_segment
from web.state import State
from web.state._compare import COMPARE_A_ID, COMPARE_B_ID


def _upload_zone(label: str, upload_id: str, bot_name: str, handler) -> rx.Component:
    return rx.vstack(
        rx.text(label, size="3", font_weight="500", color="var(--gray-12)", font_family=_MONO),
        rx.upload(
            rx.vstack(
                rx.box(
                    rx.icon("upload", size=22, color="var(--green-9)"),
                    padding="10px",
                    background="var(--green-a3)",
                    border_radius="50%",
                    border="1px solid var(--green-a5)",
                    display="inline-flex",
                ),
                rx.text("Drop .zip bot export", size="2", color="var(--gray-11)", font_weight="500"),
                rx.text("or click to browse", size="1", color="var(--gray-a8)"),
                align="center",
                spacing="2",
            ),
            id=upload_id,
            border="1.5px dashed var(--green-a6)",
            border_radius="12px",
            padding="32px 16px",
            width="100%",
            cursor="pointer",
            background="var(--green-a1)",
            transition="all 0.15s ease",
            multiple=False,
        ),
        rx.button(
            rx.hstack(rx.icon("upload", size=14), rx.text("Upload"), align="center", spacing="2"),
            on_click=handler(rx.upload_files(upload_id=upload_id)),
            width="100%",
            size="2",
            color_scheme="green",
            variant="outline",
            cursor="pointer",
        ),
        rx.cond(
            bot_name != "",
            rx.hstack(
                rx.icon("check-circle", size=14, color="var(--green-9)"),
                rx.text(bot_name, size="2", color="var(--green-11)", font_family=_MONO),
                spacing="2",
                align="center",
            ),
        ),
        spacing="3",
        flex="1",
        min_width="240px",
    )


def compare_form() -> rx.Component:
    return rx.center(
        rx.vstack(
            # Heading
            rx.vstack(
                rx.heading(
                    "Bot Comparison",
                    size="7",
                    font_family=_MONO,
                    font_weight="600",
                    color="var(--gray-12)",
                    letter_spacing="-0.5px",
                ),
                rx.text(
                    "Upload two bot exports to see what changed between them",
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
                    # Side-by-side upload zones
                    rx.hstack(
                        _upload_zone("Bot A", COMPARE_A_ID, State.compare_a_name, State.handle_compare_a_upload),
                        rx.icon("arrow-right", size=20, color="var(--gray-a7)"),
                        _upload_zone("Bot B", COMPARE_B_ID, State.compare_b_name, State.handle_compare_b_upload),
                        spacing="4",
                        width="100%",
                        align="start",
                        flex_wrap="wrap",
                    ),
                    # Error
                    rx.cond(
                        State.compare_error != "",
                        rx.callout(
                            State.compare_error,
                            icon="triangle_alert",
                            color_scheme="red",
                            size="1",
                            width="100%",
                        ),
                    ),
                    # Actions
                    rx.hstack(
                        rx.button(
                            rx.cond(
                                State.is_comparing,
                                rx.hstack(rx.spinner(size="1"), rx.text("Comparing..."), align="center", spacing="2"),
                                rx.hstack(
                                    rx.icon("git-compare", size=15),
                                    rx.text("Compare"),
                                    align="center",
                                    spacing="2",
                                ),
                            ),
                            on_click=State.run_comparison,
                            size="3",
                            color_scheme="green",
                            disabled=(State.compare_a_name == "") | (State.compare_b_name == "") | State.is_comparing,
                            cursor="pointer",
                            font_weight="500",
                            flex="1",
                        ),
                        rx.button(
                            rx.hstack(
                                rx.icon("trash-2", size=14),
                                rx.text("Clear"),
                                align="center",
                                spacing="2",
                            ),
                            on_click=State.clear_comparison,
                            size="3",
                            variant="outline",
                            color_scheme="gray",
                            cursor="pointer",
                        ),
                        width="100%",
                        spacing="3",
                    ),
                    spacing="4",
                    width="100%",
                ),
                padding="28px",
                background="var(--gray-a2)",
                border="1px solid var(--gray-a4)",
                border_radius="16px",
                max_width="700px",
                width="100%",
                box_shadow="0 8px 32px rgba(0,0,0,0.35)",
            ),
            # Result
            rx.cond(
                State.compare_result_md != "",
                rx.box(
                    rx.foreach(State.compare_segments, render_segment),
                    max_width="1400px",
                    width="100%",
                    padding="28px 32px",
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
