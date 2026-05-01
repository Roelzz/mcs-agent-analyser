import reflex as rx

from web.components.common import _MONO
from web.mermaid import render_segment
from web.state import State


def _audit_mode_checkbox(item: dict) -> rx.Component:
    """One row inside the Audit options popover. Disabled (with a
    tooltip) when the audit's required inputs aren't available — e.g.
    transcript audits when no `dialog.json` was uploaded."""
    return rx.tooltip(
        rx.box(
            rx.hstack(
                rx.checkbox(
                    checked=item["selected"],
                    disabled=~item["enabled"],
                    on_change=State.toggle_lint_audit(item["id"]),
                ),
                rx.vstack(
                    rx.text(
                        item["name"],
                        size="2",
                        font_weight="600",
                        color=rx.cond(item["enabled"], "var(--gray-12)", "var(--gray-a8)"),
                    ),
                    rx.text(
                        item["description"],
                        size="1",
                        color="var(--gray-a9)",
                        line_height="1.4",
                    ),
                    spacing="1",
                    align="start",
                    flex="1",
                ),
                spacing="2",
                align="start",
                width="100%",
            ),
            padding="6px 4px",
            opacity=rx.cond(item["enabled"], "1", "0.55"),
            cursor=rx.cond(item["enabled"], "pointer", "not-allowed"),
        ),
        content=rx.cond(item["enabled"], item["description"], item["reason"]),
    )


def _audit_options_popover() -> rx.Component:
    """Disclosure popover that exposes opt-in audit modes + a custom
    prompt. Triggers a parallel run of every selected mode plus the
    custom prompt (when non-empty) via `State.run_lint_audits`."""
    return rx.popover.root(
        rx.popover.trigger(
            rx.button(
                rx.icon("sliders-horizontal", size=14),
                rx.text("Audit options"),
                rx.text(
                    "(",
                    State.lint_selected_count.to(str),
                    ")",
                    color="var(--amber-11)",
                    font_family=_MONO,
                    size="1",
                ),
                variant="soft",
                color_scheme="amber",
                size="2",
                cursor="pointer",
            ),
        ),
        rx.popover.content(
            rx.vstack(
                rx.text(
                    "Audit modes",
                    size="2",
                    font_weight="700",
                    color="var(--gray-12)",
                ),
                rx.text(
                    "Each selected audit costs one LLM call. The Static "
                    "Config audit is the default; everything else is opt-in.",
                    size="1",
                    color="var(--gray-a9)",
                    line_height="1.4",
                ),
                rx.divider(margin_y="6px"),
                rx.foreach(State.lint_mode_availability, _audit_mode_checkbox),
                rx.divider(margin_y="6px"),
                rx.text(
                    "Custom prompt (optional)",
                    size="2",
                    font_weight="600",
                    color="var(--gray-12)",
                ),
                rx.text_area(
                    value=State.lint_custom_prompt,
                    on_change=State.set_lint_custom_prompt,
                    placeholder="e.g. Was the bot polite to the user? Cite specific messages.",
                    size="2",
                    rows="3",
                    width="100%",
                ),
                rx.hstack(
                    rx.button(
                        "Reset selection",
                        variant="ghost",
                        size="1",
                        color_scheme="gray",
                        on_click=State.reset_lint_selection,
                    ),
                    rx.spacer(),
                    rx.popover.close(
                        rx.button(
                            rx.cond(
                                State.is_linting,
                                rx.hstack(
                                    rx.spinner(size="1"),
                                    rx.text("Running..."),
                                    align="center",
                                    spacing="2",
                                ),
                                rx.hstack(
                                    rx.icon("play", size=12),
                                    rx.text("Run selected"),
                                    align="center",
                                    spacing="2",
                                ),
                            ),
                            size="2",
                            color_scheme="amber",
                            on_click=State.run_lint_audits,
                            disabled=State.is_linting,
                            cursor="pointer",
                        ),
                    ),
                    spacing="2",
                    align="center",
                    width="100%",
                ),
                spacing="2",
                align="start",
                width="100%",
            ),
            width="420px",
            max_width="92vw",
            padding="14px",
        ),
    )


def _audit_section_card(section: dict) -> rx.Component:
    """One audit's result rendered as a collapsible card. Failures
    surface as an inline callout instead of crashing the whole run."""
    return rx.box(
        rx.accordion.root(
            rx.accordion.item(
                header=rx.hstack(
                    rx.icon("scan-search", size=14, color="var(--amber-9)"),
                    rx.text(
                        section["name"],
                        size="3",
                        font_weight="700",
                        color="var(--gray-12)",
                        font_family=_MONO,
                    ),
                    rx.spacer(),
                    rx.cond(
                        section["error"] != "",
                        rx.badge("Failed", color_scheme="red", variant="soft", size="1"),
                        rx.cond(
                            section["model_used"] != "",
                            rx.badge(
                                section["model_used"],
                                color_scheme="amber",
                                variant="soft",
                                size="1",
                                font_family=_MONO,
                            ),
                        ),
                    ),
                    align="center",
                    width="100%",
                ),
                content=rx.box(
                    rx.cond(
                        section["error"] != "",
                        rx.callout(
                            section["error"],
                            icon="triangle_alert",
                            color_scheme="red",
                            size="1",
                            margin_y="8px",
                        ),
                        rx.box(
                            rx.foreach(
                                section["segments"].to(list[dict[str, str]]),  # type: ignore[union-attr]
                                render_segment,
                            ),
                            padding_top="8px",
                        ),
                    ),
                ),
                value="open",
            ),
            type="single",
            collapsible=True,
            default_value="open",
            width="100%",
        ),
        border="1px solid var(--gray-a4)",
        border_radius="10px",
        padding="10px 14px",
        margin_top="12px",
        background="var(--gray-a2)",
    )


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
                    "Document Analysis",
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
                    rx.hstack(
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
                        _audit_options_popover(),
                        spacing="2",
                        align="center",
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
        # Report top (heading, TL;DR, quick wins, trigger overlaps)
        rx.box(
            rx.foreach(State.report_segments_top, render_segment),
            padding_top="24px",
        ),
        # Custom rule findings (styled badges, between quick wins and AI config)
        _custom_findings_section(),
        # Report bottom (AI config, security, bot profile, inventories, etc.)
        rx.box(
            rx.foreach(State.report_segments_bottom, render_segment),
        ),
        rx.cond(
            State.has_lint_report,
            rx.box(
                rx.box(rx.separator(), margin_top="32px"),
                rx.hstack(
                    rx.hstack(
                        rx.icon("scan-search", size=16, color="var(--amber-9)"),
                        rx.heading(
                            "Audit Report",
                            size="4",
                            font_family=_MONO,
                            color="var(--gray-12)",
                        ),
                        rx.badge(
                            State.lint_audit_results.length().to(str),  # type: ignore[union-attr]
                            color_scheme="amber",
                            variant="soft",
                            size="1",
                        ),
                        align="center",
                        spacing="2",
                    ),
                    rx.spacer(),
                    rx.hstack(
                        rx.button(
                            rx.icon("download", size=14),
                            rx.text("Download Audit"),
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
                rx.foreach(State.lint_audit_results, _audit_section_card),
            ),
        ),
        id="report-content",
        max_width="1400px",
        width="100%",
        padding="28px 32px",
        margin="0 auto",
    )
