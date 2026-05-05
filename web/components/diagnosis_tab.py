"""Reflex components for the AgentRx-style Failure Diagnosis card.

Exposes a single public function `diagnosis_card()` that renders:
- header (run controls: judge model dropdown, offline toggle, redact toggle, Run button)
- result panel (KPIs, summary, evidence rows, canned recommendations)
- empty state

The card is mounted under the Quality tab in `dynamic_analysis.py`.
"""

from __future__ import annotations

import reflex as rx

from web.state._base import State


_MONO = "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace"
_SURFACE_BORDER = "var(--gray-a4)"
_PRIMARY = "var(--cyan-9)"


def _kpi(item: dict) -> rx.Component:
    tone = item.get("tone", "")
    return rx.box(
        rx.text(
            item["label"],
            font_size="11px",
            color="var(--gray-a9)",
            text_transform="uppercase",
            letter_spacing="0.05em",
            font_weight="600",
        ),
        rx.text(item["value"], font_size="20px", font_weight="700", color="var(--gray-12)"),
        border=rx.cond(
            tone == "danger",
            "1px solid var(--red-8)",
            rx.cond(
                tone == "warn",
                "1px solid var(--amber-8)",
                rx.cond(tone == "good", f"1px solid {_PRIMARY}", f"1px solid {_SURFACE_BORDER}"),
            ),
        ),
        border_radius="10px",
        background="var(--gray-a2)",
        padding="10px 14px",
        min_width="110px",
    )


def _evidence_row(item: dict) -> rx.Component:
    # `step_label` and `component_refs_label` are pre-formatted strings —
    # Reflex Vars don't support `str + Var` concatenation.
    return rx.vstack(
        rx.hstack(
            rx.text(
                item["step_label"],
                font_size="11px",
                color="var(--gray-a9)",
                font_family=_MONO,
            ),
            rx.text(item["rule"], font_size="12px", color="var(--gray-12)", font_family=_MONO),
            rx.badge(
                item["severity"],
                color_scheme=rx.match(
                    item["severity"],
                    ("critical", "red"),
                    ("warn", "amber"),
                    ("info", "blue"),
                    "gray",
                ),
                variant="soft",
                size="1",
            ),
            rx.cond(
                item["category_label"] != "",
                rx.badge(
                    item["category_label"],
                    color_scheme="cyan",
                    variant="soft",
                    size="1",
                ),
            ),
            spacing="2",
            align="center",
            width="100%",
        ),
        rx.text(item["description"], font_size="12px", color="var(--gray-a10)", line_height="1.5"),
        rx.cond(
            item["component_refs_label"] != "",
            rx.text(
                item["component_refs_label"],
                font_size="11px",
                color="var(--gray-a9)",
                font_family=_MONO,
            ),
        ),
        spacing="2",
        align="start",
        padding_y="10px",
        border_bottom=f"1px solid {_SURFACE_BORDER}",
        width="100%",
    )


def _category_chip(item: dict) -> rx.Component:
    return rx.badge(
        item["chip_label"],
        color_scheme="cyan",
        variant="soft",
        size="1",
    )


def _secondary_row(item: dict) -> rx.Component:
    return rx.grid(
        rx.text(
            item["step_label"],
            font_size="11px",
            color="var(--gray-a9)",
            font_family=_MONO,
        ),
        rx.badge(item["category_label"], color_scheme="cyan", variant="soft", size="1"),
        rx.badge(
            item["severity"],
            color_scheme=rx.match(
                item["severity"],
                ("high", "red"),
                ("medium", "amber"),
                ("low", "blue"),
                "gray",
            ),
            variant="soft",
            size="1",
        ),
        rx.text(item["reason"], font_size="12px", color="var(--gray-a10)", line_height="1.5"),
        columns="0.7fr 1.6fr 0.8fr 4fr",
        gap="8px",
        align="center",
        padding_y="6px",
        border_bottom=f"1px solid {_SURFACE_BORDER}",
        width="100%",
    )


def _rec_row(item: dict) -> rx.Component:
    return rx.box(
        rx.text(item["title"], font_size="13px", font_weight="700", color="var(--gray-12)"),
        rx.text(item["body"], font_size="12px", color="var(--gray-a10)", line_height="1.55"),
        padding_y="8px",
        border_bottom=f"1px solid {_SURFACE_BORDER}",
        width="100%",
    )


def _redaction_chip(item: dict) -> rx.Component:
    return rx.badge(
        item["chip_label"],
        color_scheme="cyan",
        variant="soft",
        size="1",
    )


def _judge_model_choice(model: str) -> rx.Component:
    return rx.select.item(model, value=model)


def _controls_panel() -> rx.Component:
    return rx.hstack(
        rx.vstack(
            rx.text(
                "Judge model",
                font_size="11px",
                color="var(--gray-a9)",
                text_transform="uppercase",
                font_weight="600",
            ),
            rx.select.root(
                rx.select.trigger(width="160px"),
                rx.select.content(
                    rx.foreach(State.diagnosis_judge_model_choices, _judge_model_choice),  # type: ignore[arg-type]
                ),
                value=State.diagnosis_judge_model,  # type: ignore[arg-type]
                on_change=State.set_diagnosis_judge_model,  # type: ignore[arg-type]
                disabled=State.diagnosis_offline,  # type: ignore[arg-type]
            ),
            spacing="1",
        ),
        rx.vstack(
            rx.text(
                "Mode",
                font_size="11px",
                color="var(--gray-a9)",
                text_transform="uppercase",
                font_weight="600",
            ),
            rx.hstack(
                rx.checkbox(
                    "Offline (no LLM)",
                    checked=State.diagnosis_offline,  # type: ignore[arg-type]
                    on_change=State.toggle_diagnosis_offline,  # type: ignore[arg-type]
                    size="2",
                ),
                rx.checkbox(
                    "Redact PII",
                    checked=State.diagnosis_redact_pii,  # type: ignore[arg-type]
                    on_change=State.toggle_diagnosis_redact,  # type: ignore[arg-type]
                    disabled=State.diagnosis_offline,  # type: ignore[arg-type]
                    size="2",
                ),
                spacing="3",
            ),
            spacing="1",
        ),
        rx.spacer(),
        rx.button(
            rx.cond(
                State.is_diagnosing,  # type: ignore[arg-type]
                rx.hstack(rx.spinner(size="2"), rx.text("Diagnosing…"), spacing="2"),
                rx.hstack(rx.icon("siren", size=14), rx.text("Diagnose failure"), spacing="2"),
            ),
            on_click=State.run_diagnose,  # type: ignore[arg-type]
            disabled=~State.can_diagnose,  # type: ignore[operator]
            size="2",
            color_scheme="red",
            variant="solid",
        ),
        align="end",
        spacing="3",
        width="100%",
        padding_y="8px",
    )


def _result_panel() -> rx.Component:
    return rx.cond(
        State.diagnosis_error != "",  # type: ignore[arg-type]
        rx.callout(State.diagnosis_error, icon="circle_alert", color_scheme="red", width="100%"),  # type: ignore[arg-type]
        rx.cond(
            State.diagnosis_has_result,  # type: ignore[arg-type]
            rx.vstack(
                rx.cond(
                    State.diagnosis_error_state,  # type: ignore[arg-type]
                    rx.callout(
                        State.diagnosis_error_message,  # type: ignore[arg-type]
                        icon="circle_alert",
                        color_scheme="amber",
                        width="100%",
                    ),
                ),
                rx.hstack(
                    rx.foreach(State.diagnosis_kpis, _kpi),  # type: ignore[arg-type]
                    spacing="3",
                    overflow_x="auto",
                    padding_y="12px",
                    width="100%",
                ),
                rx.cond(
                    State.diagnosis_category_chips.length() > 0,  # type: ignore[union-attr]
                    rx.hstack(
                        rx.text(
                            "Categories detected:",
                            font_size="11px",
                            color="var(--gray-a9)",
                            text_transform="uppercase",
                            letter_spacing="0.05em",
                            font_weight="600",
                        ),
                        rx.foreach(State.diagnosis_category_chips, _category_chip),  # type: ignore[arg-type]
                        spacing="2",
                        wrap="wrap",
                        padding_y="6px",
                        align="center",
                    ),
                ),
                rx.cond(
                    State.diagnosis_summary != "",  # type: ignore[arg-type]
                    rx.box(
                        rx.text(
                            State.diagnosis_summary,  # type: ignore[arg-type]
                            font_size="13px",
                            color="var(--gray-12)",
                            line_height="1.55",
                        ),
                        padding="10px 12px",
                        background="var(--gray-a2)",
                        border_radius="8px",
                        border=f"1px solid {_SURFACE_BORDER}",
                        width="100%",
                    ),
                ),
                rx.cond(
                    State.diagnosis_reason_for_index != "",  # type: ignore[arg-type]
                    rx.box(
                        rx.text(
                            f"Why this step: {State.diagnosis_reason_for_index}",
                            font_size="12px",
                            color="var(--gray-a10)",
                            font_style="italic",
                        ),
                        padding_x="12px",
                    ),
                ),
                rx.cond(
                    State.diagnosis_secondary_rows.length() > 0,  # type: ignore[union-attr]
                    rx.box(
                        rx.text(
                            "Secondary findings (LLM judge)",
                            font_size="13px",
                            font_weight="700",
                            color="var(--gray-12)",
                            padding_top="12px",
                        ),
                        rx.text(
                            "Other failure-shaped events the judge spotted beyond the critical step.",
                            font_size="11px",
                            color="var(--gray-a9)",
                            font_style="italic",
                        ),
                        rx.grid(
                            rx.text(
                                "Step",
                                font_size="11px",
                                color="var(--gray-a9)",
                                font_weight="600",
                                text_transform="uppercase",
                            ),
                            rx.text(
                                "Category",
                                font_size="11px",
                                color="var(--gray-a9)",
                                font_weight="600",
                                text_transform="uppercase",
                            ),
                            rx.text(
                                "Severity",
                                font_size="11px",
                                color="var(--gray-a9)",
                                font_weight="600",
                                text_transform="uppercase",
                            ),
                            rx.text(
                                "Reason",
                                font_size="11px",
                                color="var(--gray-a9)",
                                font_weight="600",
                                text_transform="uppercase",
                            ),
                            columns="0.7fr 1.6fr 0.8fr 4fr",
                            gap="8px",
                            padding_y="6px",
                            border_bottom=f"2px solid {_SURFACE_BORDER}",
                            width="100%",
                        ),
                        rx.foreach(State.diagnosis_secondary_rows, _secondary_row),  # type: ignore[arg-type]
                        width="100%",
                    ),
                ),
                rx.cond(
                    State.diagnosis_evidence_rows.length() > 0,  # type: ignore[union-attr]
                    rx.box(
                        rx.text(
                            "Evidence",
                            font_size="13px",
                            font_weight="700",
                            color="var(--gray-12)",
                            padding_top="12px",
                        ),
                        rx.foreach(State.diagnosis_evidence_rows, _evidence_row),  # type: ignore[arg-type]
                        width="100%",
                    ),
                ),
                rx.cond(
                    State.diagnosis_canned_recs.length() > 0,  # type: ignore[union-attr]
                    rx.box(
                        rx.text(
                            "Recommendations",
                            font_size="13px",
                            font_weight="700",
                            color="var(--gray-12)",
                            padding_top="12px",
                        ),
                        rx.foreach(State.diagnosis_canned_recs, _rec_row),  # type: ignore[arg-type]
                        width="100%",
                    ),
                ),
                rx.cond(
                    State.diagnosis_redaction_chips.length() > 0,  # type: ignore[union-attr]
                    rx.hstack(
                        rx.text(
                            "Redacted before LLM call:",
                            font_size="11px",
                            color="var(--gray-a9)",
                        ),
                        rx.foreach(State.diagnosis_redaction_chips, _redaction_chip),  # type: ignore[arg-type]
                        spacing="2",
                        wrap="wrap",
                        padding_top="8px",
                    ),
                ),
                rx.hstack(
                    rx.text(
                        f"Generated {State.diagnosis_generated_at}",
                        font_size="11px",
                        color="var(--gray-a8)",
                    ),
                    rx.cond(
                        State.diagnosis_judge_model_used != "",  # type: ignore[arg-type]
                        rx.text(
                            f"Model: {State.diagnosis_judge_model_used}",
                            font_size="11px",
                            color="var(--gray-a8)",
                        ),
                    ),
                    rx.spacer(),
                    rx.button(
                        "Re-run diagnosis",
                        variant="ghost",
                        size="1",
                        on_click=State.run_diagnose,  # type: ignore[arg-type]
                        disabled=~State.can_diagnose,  # type: ignore[operator]
                    ),
                    spacing="3",
                    padding_top="12px",
                    width="100%",
                ),
                spacing="2",
                align="start",
                width="100%",
            ),
            rx.box(
                rx.text(
                    'No diagnosis yet — click "Diagnose failure" to scan this transcript.',
                    font_size="13px",
                    color="var(--gray-a8)",
                    font_style="italic",
                ),
                padding="20px 0",
            ),
        ),
    )


def _chat_bubble(item: dict) -> rx.Component:
    is_user = item["role"] == "user"
    return rx.box(
        rx.text(
            rx.cond(is_user, "You", "Judge"),
            font_size="10px",
            color="var(--gray-a8)",
            text_transform="uppercase",
            letter_spacing="0.05em",
            font_weight="700",
        ),
        rx.text(
            item["content"],
            font_size="13px",
            color="var(--gray-12)",
            line_height="1.55",
            white_space="pre-wrap",
        ),
        background=rx.cond(is_user, "var(--cyan-a3)", "var(--gray-a2)"),
        border=rx.cond(is_user, f"1px solid {_PRIMARY}", f"1px solid {_SURFACE_BORDER}"),
        border_radius="10px",
        padding="10px 12px",
        margin_y="4px",
        align_self=rx.cond(is_user, "flex-end", "flex-start"),
        max_width="85%",
        width="fit-content",
    )


def _chat_streaming_bubble() -> rx.Component:
    """The bubble that fills in token-by-token while the judge streams."""
    return rx.cond(
        State.is_chatting & (State.diagnosis_chat_streaming_buffer != ""),  # type: ignore[operator]
        rx.box(
            rx.text(
                "JUDGE",
                font_size="10px",
                color="var(--gray-a8)",
                text_transform="uppercase",
                letter_spacing="0.05em",
                font_weight="700",
            ),
            rx.text(
                State.diagnosis_chat_streaming_buffer,  # type: ignore[arg-type]
                font_size="13px",
                color="var(--gray-12)",
                line_height="1.55",
                white_space="pre-wrap",
            ),
            background="var(--gray-a2)",
            border=f"1px solid {_SURFACE_BORDER}",
            border_radius="10px",
            padding="10px 12px",
            margin_y="4px",
            align_self="flex-start",
            max_width="85%",
            width="fit-content",
        ),
    )


def _chat_panel() -> rx.Component:
    """Collapsible 'Ask the judge' chat panel. Hidden when no judge ran."""
    return rx.cond(
        State.diagnosis_judge_model_used != "",  # type: ignore[arg-type]
        rx.accordion.root(
            rx.accordion.item(
                header=rx.hstack(
                    rx.icon("messages-square", size=14, color="var(--cyan-9)"),
                    rx.text("Ask the judge", font_size="13px", font_weight="700", color="var(--gray-12)"),
                    rx.cond(
                        State.has_chat_history,
                        rx.badge(
                            State.diagnosis_chat_history_active.length().to(str),  # type: ignore[union-attr]
                            color_scheme="cyan",
                            variant="soft",
                            size="1",
                        ),
                    ),
                    spacing="2",
                    align="center",
                ),
                content=rx.vstack(
                    rx.cond(
                        State.diagnosis_chat_error != "",  # type: ignore[arg-type]
                        rx.callout(
                            State.diagnosis_chat_error,  # type: ignore[arg-type]
                            icon="circle_alert",
                            color_scheme="red",
                            width="100%",
                        ),
                    ),
                    rx.vstack(
                        rx.foreach(State.diagnosis_chat_history_active, _chat_bubble),  # type: ignore[arg-type]
                        _chat_streaming_bubble(),
                        spacing="1",
                        align="stretch",
                        width="100%",
                    ),
                    rx.hstack(
                        rx.text_area(
                            placeholder="Where did you see this fabrication? What about the tool observation at position X?",
                            value=State.diagnosis_chat_input,  # type: ignore[arg-type]
                            on_change=State.set_diagnosis_chat_input,  # type: ignore[arg-type]
                            disabled=State.is_chatting,  # type: ignore[arg-type]
                            rows="2",
                            width="100%",
                        ),
                        rx.button(
                            rx.cond(
                                State.is_chatting,  # type: ignore[arg-type]
                                rx.spinner(size="2"),
                                rx.icon("send-horizontal", size=16),
                            ),
                            on_click=State.send_chat_message,  # type: ignore[arg-type]
                            disabled=~State.can_chat,  # type: ignore[operator]
                            color_scheme="cyan",
                            variant="solid",
                        ),
                        spacing="2",
                        align="end",
                        width="100%",
                    ),
                    rx.cond(
                        State.has_chat_history,
                        rx.button(
                            "Clear conversation",
                            variant="ghost",
                            size="1",
                            on_click=State.clear_chat,  # type: ignore[arg-type]
                            color_scheme="gray",
                        ),
                    ),
                    spacing="3",
                    align="stretch",
                    width="100%",
                ),
                value="ask-the-judge",
            ),
            collapsible=True,
            type="single",
            width="100%",
            margin_top="12px",
        ),
    )


def diagnosis_card() -> rx.Component:
    """The complete Failure Diagnosis card. Mount under the Quality tab."""
    return rx.box(
        rx.vstack(
            rx.hstack(
                rx.icon("siren", size=18, color="var(--red-9)"),
                rx.text(
                    "Failure Diagnosis (AgentRx)",
                    font_size="15px",
                    font_weight="700",
                    color="var(--gray-12)",
                ),
                spacing="2",
                align="center",
            ),
            rx.text(
                "AgentRx-style critical-step localization with a 10-category root-cause taxonomy.",
                font_size="12px",
                color="var(--gray-a9)",
            ),
            _controls_panel(),
            _result_panel(),
            _chat_panel(),
            spacing="2",
            align="start",
            width="100%",
        ),
        background="var(--gray-1)",
        border=f"1px solid {_SURFACE_BORDER}",
        border_radius="12px",
        padding="16px",
        width="100%",
    )
