import reflex as rx

from web.components.common import _MONO
from web.mermaid import render_segment
from web.state import State


def _finding_row(finding: dict) -> rx.Component:
    """Render a single custom rule finding with colored badges."""
    return rx.box(
        rx.hstack(
            rx.badge(
                finding["severity"],
                color_scheme=rx.match(
                    finding["severity"],
                    ("warning", "amber"),
                    ("fail", "red"),
                    ("info", "blue"),
                    ("pass", "green"),
                    "gray",
                ),
                variant="soft",
                size="1",
            ),
            rx.badge(finding["category"], color_scheme="gray", variant="outline", size="1"),
            rx.text(finding["rule_id"], size="2", font_weight="500", color="var(--gray-12)", font_family=_MONO),
            rx.text(finding["detail"], size="1", color="var(--gray-a9)", flex="1"),
            width="100%",
            align="center",
            spacing="2",
        ),
        padding="10px 12px",
        border_bottom="1px solid var(--gray-a3)",
        _hover={"background": "var(--gray-a2)"},
    )


def _custom_findings_section() -> rx.Component:
    """Render custom rule findings with styled badges, matching rules page design."""
    return rx.cond(
        State.has_custom_findings,
        rx.box(
            rx.hstack(
                rx.icon("shield-check", size=16, color="var(--green-9)"),
                rx.text("Custom Rules", size="3", font_weight="500", color="var(--gray-12)"),
                rx.badge(
                    State.report_custom_findings.length().to(str),  # type: ignore[union-attr]
                    color_scheme="green",
                    variant="soft",
                    size="1",
                ),
                align="center",
                spacing="2",
            ),
            rx.box(
                rx.foreach(State.report_custom_findings, _finding_row),
                width="100%",
                border="1px solid var(--gray-a4)",
                border_radius="8px",
                overflow="hidden",
                margin_top="8px",
            ),
            padding_top="24px",
            padding_bottom="8px",
        ),
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
        # Custom rule findings (styled, after markdown report)
        _custom_findings_section(),
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
