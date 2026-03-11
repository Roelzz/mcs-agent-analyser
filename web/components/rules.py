import reflex as rx

from web.components.common import _MONO
from web.state import State

RULES_UPLOAD_ID = "rules_upload"


def _rule_row(rule: dict) -> rx.Component:
    return rx.box(
        rx.hstack(
            rx.badge(
                rule["severity"],
                color_scheme=rx.match(
                    rule["severity"],
                    ("warning", "amber"),
                    ("fail", "red"),
                    ("info", "blue"),
                    "gray",
                ),
                variant="soft",
                size="1",
            ),
            rx.badge(rule["category"], color_scheme="gray", variant="outline", size="1"),
            rx.text(rule["rule_id"], size="2", font_weight="500", color="var(--gray-12)", font_family=_MONO),
            rx.text(rule["message"], size="1", color="var(--gray-a9)", flex="1"),
            width="100%",
            align="center",
            spacing="2",
        ),
        padding="10px 12px",
        border_bottom="1px solid var(--gray-a3)",
        _hover={"background": "var(--gray-a2)"},
    )


def rules_editor() -> rx.Component:
    return rx.center(
        rx.vstack(
            rx.vstack(
                rx.heading(
                    "Custom Rules",
                    size="7",
                    font_family=_MONO,
                    font_weight="600",
                    color="var(--gray-12)",
                    letter_spacing="-0.5px",
                ),
                rx.text(
                    "Define YAML-based rules to evaluate against agent profiles during solution checks",
                    size="2",
                    color="var(--gray-a9)",
                    text_align="center",
                ),
                spacing="2",
                align="center",
            ),
            rx.box(
                rx.vstack(
                    # Header with count badge
                    rx.hstack(
                        rx.icon("shield-check", size=16, color="var(--green-9)"),
                        rx.text("Rules Editor", size="3", font_weight="500", color="var(--gray-12)"),
                        rx.cond(
                            State.rules_count > 0,
                            rx.badge(
                                State.rules_count.to(str),
                                color_scheme="green",
                                variant="soft",
                                size="1",
                            ),
                        ),
                        rx.spacer(),
                        rx.hstack(
                            rx.upload(
                                rx.button(
                                    rx.hstack(
                                        rx.icon("upload", size=14),
                                        rx.text("Upload YAML"),
                                        align="center",
                                        spacing="2",
                                    ),
                                    variant="outline",
                                    color_scheme="green",
                                    size="1",
                                    cursor="pointer",
                                ),
                                id=RULES_UPLOAD_ID,
                                multiple=False,
                                accept={".yaml": ["text/yaml"], ".yml": ["text/yaml", "application/x-yaml"]},
                                no_drag=True,
                            ),
                            rx.button(
                                "Apply",
                                on_click=State.handle_rules_upload(rx.upload_files(upload_id=RULES_UPLOAD_ID)),
                                variant="solid",
                                color_scheme="green",
                                size="1",
                                cursor="pointer",
                            ),
                            rx.button(
                                rx.hstack(rx.icon("trash-2", size=14), rx.text("Clear"), align="center", spacing="2"),
                                on_click=State.clear_rules,
                                variant="outline",
                                color_scheme="gray",
                                size="1",
                                cursor="pointer",
                            ),
                            spacing="2",
                            align="center",
                        ),
                        width="100%",
                        align="center",
                        spacing="2",
                    ),
                    # YAML text area
                    rx.text_area(
                        value=State.custom_rules_yaml,
                        on_change=State.update_rules_yaml,
                        placeholder='rules:\n  - rule_id: CUSTOM001\n    severity: warning\n    category: Security\n    message: "Application Insights must be configured"\n    condition:\n      field: "app_insights"\n      operator: not_exists',
                        width="100%",
                        min_height="200px",
                        font_family=_MONO,
                        size="2",
                    ),
                    # Error display
                    rx.cond(
                        State.rules_parse_error != "",
                        rx.callout(
                            State.rules_parse_error,
                            icon="triangle_alert",
                            color_scheme="red",
                            size="1",
                            width="100%",
                        ),
                    ),
                    # Parsed rules table
                    rx.cond(
                        State.rules_count > 0,
                        rx.vstack(
                            rx.text("Parsed Rules", size="2", font_weight="500", color="var(--gray-11)"),
                            rx.box(
                                rx.foreach(State.custom_rules_parsed, _rule_row),
                                width="100%",
                                border="1px solid var(--gray-a4)",
                                border_radius="8px",
                                overflow="hidden",
                            ),
                            spacing="2",
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
