"""Dynamic analysis visual panel components — green-themed."""

from __future__ import annotations

import reflex as rx

from web.components.common import _MONO
from web.components.report import _audit_options_popover, _audit_section_card
from web.mermaid import render_segment_styled
from web.state import State

# ── Design system constants (green theme) ─────────────────────────────────────
PRIMARY = "var(--green-9)"
PRIMARY_DARK = "var(--green-11)"
PRIMARY_SOFT = "var(--green-a3)"
CARD_SHADOW = "0 16px 40px rgba(12, 33, 70, 0.10)"
SURFACE_BORDER = "var(--gray-a4)"

_BODY = "Outfit, sans-serif"


# ── Building blocks ───────────────────────────────────────────────────────────


def card(*children: rx.Component, **props) -> rx.Component:
    defaults = {
        "background": "var(--gray-a2)",
        "border": f"1px solid {SURFACE_BORDER}",
        "border_radius": "16px",
        "padding": "24px",
        "box_shadow": CARD_SHADOW,
        "_hover": {"box_shadow": "0 20px 44px rgba(12, 33, 70, 0.14)"},
        "transition": "box-shadow 0.2s ease",
    }
    defaults.update(props)
    return rx.box(*children, **defaults)


def section_heading(text: str) -> rx.Component:
    return rx.heading(text, size="4", color="var(--gray-12)", letter_spacing="-0.01em")


def sub_heading(text: str) -> rx.Component:
    return rx.text(
        text,
        font_size="10px",
        font_weight="700",
        text_transform="uppercase",
        letter_spacing="0.06em",
        color="var(--gray-a9)",
    )


def label(text: str) -> rx.Component:
    return rx.text(text, font_size="12px", font_weight="700", color="var(--gray-a9)")


def info_row(lbl: str, value) -> rx.Component:
    return rx.hstack(
        rx.text(lbl, font_size="13px", color="var(--gray-a9)", font_weight="600", min_width="140px"),
        rx.text(value, font_size="13px", color="var(--gray-12)"),
        width="100%",
        align="center",
        spacing="3",
    )


def _trigger_score_badge(score_str, color_str) -> rx.Component:
    """Colored badge for trigger match score. Color is pre-computed in the backend."""
    return rx.cond(
        score_str != "",
        rx.badge(score_str, color_scheme=color_str, variant="soft", size="1"),
        rx.box(),
    )


# ── Sub-tab bar ───────────────────────────────────────────────────────────────


def _mcs_section_tab_bar() -> rx.Component:
    def _btn(tab_id: str, icon_name: str, lbl: str) -> rx.Component:
        active = State.mcs_analyse_tab == tab_id
        return rx.box(
            rx.hstack(
                rx.icon(icon_name, size=14),
                rx.text(lbl, font_size="13px", font_weight="600"),
                spacing="2",
                align="center",
            ),
            on_click=State.set_mcs_analyse_tab(tab_id),
            padding="8px 16px",
            cursor="pointer",
            border_bottom=rx.cond(active, f"2px solid {PRIMARY}", "2px solid transparent"),
            color=rx.cond(active, PRIMARY, "var(--gray-a9)"),
            _hover={"color": PRIMARY},
            transition="all 0.15s ease",
            user_select="none",
        )

    return rx.cond(
        State.mcs_section_profile,
        # Profile data exists: all tabs
        rx.hstack(
            _btn("profile", "user-round", "Profile"),
            _btn("topics", "list", "Topics"),
            _btn("tools", "wrench", "Tools"),
            _btn("knowledge", "database", "Knowledge"),
            _btn("routing", "route", "Routing"),
            _btn("conversation", "message-square", "Conversation"),
            _btn("quality", "shield-check", "Quality"),
            spacing="0",
            border_bottom=f"1px solid {SURFACE_BORDER}",
            width="100%",
            overflow_x="auto",
        ),
        # No profile: limited tabs
        rx.hstack(
            _btn("conversation", "message-square", "Conversation"),
            _btn("tools", "wrench", "Tools"),
            _btn("routing", "route", "Routing"),
            _btn("quality", "shield-check", "Quality"),
            spacing="0",
            border_bottom=f"1px solid {SURFACE_BORDER}",
            width="100%",
            overflow_x="auto",
        ),
    )


# ── Credits panel ─────────────────────────────────────────────────────────────


def _mcs_credit_row(item: dict) -> rx.Component:
    return rx.grid(
        rx.text(item["meter"], font_size="13px", color="var(--gray-12)", font_weight="500"),
        rx.text(item["count"], font_size="13px", color="var(--gray-11)", text_align="right"),
        rx.text(item["rate"], font_size="13px", color="var(--gray-a9)", text_align="right"),
        rx.text(item["credits"], font_size="13px", color="var(--gray-11)", font_weight="600", text_align="right"),
        columns="3fr 1fr 1fr 1fr",
        gap="8px",
        align="center",
        padding_y="8px",
        border_bottom=f"1px solid {SURFACE_BORDER}",
        width="100%",
    )


def _mcs_credit_step_row(item: dict) -> rx.Component:
    return rx.grid(
        rx.text(item["index"], font_size="13px", color="var(--gray-a9)", text_align="right"),
        rx.text(item["step_name"], font_size="13px", color="var(--gray-12)", font_weight="500"),
        rx.badge(
            item["step_type"],
            color_scheme=rx.match(
                item["step_type"],
                ("generative_answer", "green"),
                ("agent_action", "purple"),
                ("classic_answer", "blue"),
                ("flow_action", "amber"),
                "gray",
            ),
            variant="soft",
            size="1",
        ),
        rx.text(item["credits"], font_size="13px", color="var(--gray-11)", font_weight="600", text_align="right"),
        rx.text(
            item["detail"],
            font_size="12px",
            color="var(--gray-a9)",
            overflow="hidden",
            text_overflow="ellipsis",
            white_space="nowrap",
        ),
        columns="0.5fr 2fr 1fr 0.5fr 3fr",
        gap="8px",
        align="center",
        padding_y="6px",
        border_bottom="1px solid var(--gray-a4)",
        width="100%",
    )


def _mcs_credits_panel() -> rx.Component:
    return card(
        rx.hstack(
            rx.vstack(
                rx.text("Predicted Copilot Credits", font_size="12px", color="var(--gray-a9)", font_weight="600"),
                rx.text(
                    State.mcs_credit_total,
                    font_size="30px",
                    font_weight="800",
                    color=PRIMARY,
                    line_height="1.1",
                ),
                align="start",
                spacing="1",
            ),
            rx.spacer(),
            rx.badge("Heuristic Estimate", color_scheme="amber", variant="soft"),
            align="start",
            width="100%",
            margin_bottom="14px",
        ),
        # Credits detail table
        rx.box(
            rx.grid(
                rx.text("Meter", font_size="12px", color="var(--gray-a9)", font_weight="700"),
                rx.text("Count", font_size="12px", color="var(--gray-a9)", font_weight="700", text_align="right"),
                rx.text("Rate", font_size="12px", color="var(--gray-a9)", font_weight="700", text_align="right"),
                rx.text("Credits", font_size="12px", color="var(--gray-a9)", font_weight="700", text_align="right"),
                columns="3fr 1fr 1fr 1fr",
                gap="8px",
                padding_y="8px",
                width="100%",
            ),
            rx.foreach(State.mcs_credit_rows, _mcs_credit_row),
            rx.cond(
                State.mcs_credit_rows.length() == 0,  # type: ignore[union-attr]
                rx.text(
                    "No billable events detected in this conversation. "
                    "Credits are estimated from orchestrator steps "
                    "(knowledge searches, agent actions, topic transitions).",
                    font_size="13px",
                    color="var(--gray-a9)",
                    padding="12px",
                ),
            ),
            width="100%",
            border=f"1px solid {SURFACE_BORDER}",
            border_radius="8px",
            padding_x="12px",
            background="var(--gray-a2)",
        ),
        # Assumptions
        rx.vstack(
            rx.text("Assumptions", font_size="13px", color="var(--gray-12)", font_weight="700"),
            rx.foreach(
                State.mcs_credit_assumptions,
                lambda line: rx.hstack(
                    rx.text("•", color="var(--gray-a9)", margin_top="1px"),
                    rx.text(line, font_size="13px", color="var(--gray-a9)"),
                    align="start",
                    spacing="2",
                    width="100%",
                ),
            ),
            align="start",
            spacing="2",
            margin_top="14px",
            width="100%",
        ),
        # Per-step breakdown
        rx.cond(
            State.mcs_credit_step_rows.length() > 0,  # type: ignore[union-attr]
            rx.vstack(
                sub_heading("Per-Step Breakdown"),
                rx.box(
                    _grid_header("#", "Step", "Type", "Credits", "Detail", template="0.5fr 2fr 1fr 0.5fr 3fr"),
                    rx.foreach(State.mcs_credit_step_rows, _mcs_credit_step_row),
                    width="100%",
                    border="1px solid var(--gray-a4)",
                    border_radius="8px",
                    padding_x="12px",
                    background="var(--gray-a2)",
                    overflow_x="auto",
                ),
                spacing="2",
                margin_top="14px",
                width="100%",
            ),
        ),
        # Credit flow diagram
        _mermaid_block(State.mcs_credit_mermaid),
        width="100%",
    )


# ── Conversation flow ─────────────────────────────────────────────────────────


def _mcs_flow_message(item: dict) -> rx.Component:
    is_user = item["role"] == "user"
    return rx.vstack(
        rx.hstack(
            rx.cond(
                is_user,
                rx.box(),
                rx.hstack(
                    rx.icon("bot", size=14, color=PRIMARY),
                    rx.text(item["actor"], font_size="12px", font_weight="700", color="var(--gray-12)"),
                    rx.cond(
                        item["timestamp"] != "",
                        rx.text(item["timestamp"], font_size="11px", color="var(--gray-a8)"),
                        rx.box(),
                    ),
                    spacing="2",
                    align="center",
                ),
            ),
            rx.cond(
                is_user,
                rx.hstack(
                    rx.cond(
                        item["timestamp"] != "",
                        rx.text(item["timestamp"], font_size="11px", color="var(--gray-a8)"),
                        rx.box(),
                    ),
                    rx.text(item["actor"], font_size="12px", font_weight="700", color="var(--gray-12)"),
                    rx.icon("user-round", size=14, color=PRIMARY),
                    spacing="2",
                    align="center",
                ),
                rx.box(),
            ),
            width="100%",
            justify=rx.cond(is_user, "end", "start"),
        ),
        rx.hstack(
            rx.box(
                rx.text(item["text"], font_size="15px", color="var(--gray-12)", line_height="1.55"),
                max_width=["100%", "100%", "72%"],
                background=rx.cond(is_user, "var(--green-a3)", "var(--gray-a2)"),
                border=rx.cond(is_user, "1px solid var(--green-a5)", f"1px solid {SURFACE_BORDER}"),
                border_radius=rx.cond(is_user, "14px 14px 4px 14px", "14px 14px 14px 4px"),
                padding="14px 16px",
                box_shadow="0 6px 18px rgba(0,0,0,0.06)",
            ),
            width="100%",
            justify=rx.cond(is_user, "end", "start"),
        ),
        spacing="2",
        width="100%",
        align="stretch",
        id=item["flow_row_id"],
    )


def _flow_event_detail_accordion(item: dict) -> rx.Component:
    """Expandable detail section for flow events with rich fields."""
    return rx.accordion.root(
        rx.accordion.item(
            header=rx.text("Details", font_size="11px", color="var(--gray-a8)"),
            content=rx.vstack(
                rx.cond(
                    item["thought"] != "",
                    rx.text(
                        item["thought"],
                        font_size="11px",
                        font_style="italic",
                        color="var(--gray-a7)",
                        line_height="1.4",
                    ),
                    rx.box(),
                ),
                rx.cond(
                    item["error"] != "",
                    rx.text(item["error"], font_size="11px", color="var(--red-9)"),
                    rx.box(),
                ),
                rx.cond(
                    item["plan_steps"] != "",
                    rx.vstack(
                        rx.text("Plan steps:", font_size="11px", color="var(--gray-a8)", font_weight="600"),
                        rx.text(item["plan_steps"], font_size="11px", color="var(--gray-11)"),
                        spacing="1",
                        width="100%",
                    ),
                    rx.box(),
                ),
                rx.cond(
                    item["has_recommendations"] == "true",
                    rx.badge("Alternatives considered", color_scheme="amber", variant="soft", size="1"),
                    rx.box(),
                ),
                rx.cond(
                    item["plan_used_outputs"] != "",
                    rx.text(
                        rx.text.span("Used outputs: ", font_weight="600", color="var(--gray-a8)"),
                        rx.text.span(item["plan_used_outputs"]),
                        font_size="11px",
                        color="var(--blue-9)",
                    ),
                    rx.box(),
                ),
                rx.cond(
                    item["plan_identifier"] != "",
                    rx.hstack(
                        rx.text(item["plan_identifier"], font_size="11px", color="var(--gray-a8)"),
                        rx.cond(
                            item["is_final_plan"] == "True",
                            rx.badge("Final", color_scheme="green", variant="soft", size="1"),
                            rx.box(),
                        ),
                        spacing="2",
                        align="center",
                    ),
                    rx.box(),
                ),
                rx.cond(
                    item["orchestrator_ask"] != "",
                    rx.text(
                        rx.text.span("Ask: ", font_weight="600", color="var(--gray-a8)"),
                        rx.text.span(item["orchestrator_ask"], font_style="italic"),
                        font_size="11px",
                        color="var(--violet-11)",
                    ),
                    rx.box(),
                ),
                rx.cond(
                    item["trigger_phrase"] != "",
                    rx.text(
                        rx.text.span("Best routing phrase: ", font_weight="600", color="var(--gray-a8)"),
                        rx.text.span(item["trigger_phrase"], font_style="italic"),
                        font_size="11px",
                        color="var(--gray-a9)",
                    ),
                    rx.box(),
                ),
                spacing="1",
                width="100%",
                padding_top="4px",
            ),
            value="details",
        ),
        type="multiple",
        variant="ghost",
        width="100%",
    )


def _has_flow_details(item: dict) -> rx.Var:
    """Check if any detail field is non-empty."""
    return (
        (item["thought"] != "")
        | (item["error"] != "")
        | (item["plan_steps"] != "")
        | (item["has_recommendations"] == "true")
        | (item["plan_used_outputs"] != "")
        | (item["plan_identifier"] != "")
        | (item["orchestrator_ask"] != "")
        | (item["trigger_phrase"] != "")
    )


def _flow_row_actions(item: dict) -> rx.Component:
    """Per-row copy-JSON button + collapsible Raw JSON viewer. Renders
    only when `raw_json` is non-empty. Click handlers use
    `stop_propagation` so they don't trigger the parent card's
    deep-link navigation."""
    return rx.cond(
        item["raw_json"] != "",
        rx.vstack(
            rx.hstack(
                rx.spacer(),
                rx.tooltip(
                    rx.icon_button(
                        rx.icon("copy", size=12),
                        size="1",
                        variant="ghost",
                        color_scheme="green",
                        on_click=State.copy_flow_row_json(item["raw_json"]).stop_propagation,  # type: ignore[attr-defined]
                    ),
                    content="Copy activity JSON",
                ),
                spacing="2",
                align="center",
                width="100%",
            ),
            rx.box(
                rx.accordion.root(
                    rx.accordion.item(
                        header=rx.text(
                            "Raw activity JSON",
                            font_size="10px",
                            color="var(--gray-a8)",
                            font_weight="700",
                        ),
                        content=rx.box(
                            rx.el.pre(
                                item["raw_json"],
                                style={
                                    "fontSize": "10px",
                                    "color": "var(--gray-12)",
                                    "lineHeight": "1.5",
                                    "whiteSpace": "pre-wrap",
                                    "wordBreak": "break-word",
                                    "margin": 0,
                                },
                            ),
                            background="var(--gray-a3)",
                            border_radius="6px",
                            padding="8px 10px",
                            max_height="280px",
                            overflow_y="auto",
                            width="100%",
                        ),
                        value="raw",
                    ),
                    type="single",
                    collapsible=True,
                    variant="ghost",
                    width="100%",
                ),
                # Stop click bubbling so opening the accordion doesn't
                # also fire the card's deep-link navigation.
                on_click=rx.stop_propagation,
                width="100%",
            ),
            spacing="0",
            width="100%",
        ),
    )


def _mcs_flow_event(item: dict) -> rx.Component:
    is_error = item["tone"] == "error"
    is_trace = item["tone"] == "trace"
    is_linked = item["link_target_tab"] != ""

    return rx.cond(
        is_trace,
        # Compact chip for trace (condition eval) events
        rx.center(
            rx.hstack(
                rx.icon("git-branch", size=12, color="var(--gray-a8)"),
                rx.text(item["summary"], font_size="11px", color="var(--gray-a8)"),
                rx.cond(
                    is_linked,
                    rx.icon("arrow-up-right", size=10, color="var(--green-a9)"),
                ),
                rx.cond(
                    item["timestamp"] != "",
                    rx.text(item["timestamp"], font_size="10px", color="var(--gray-a6)"),
                    rx.box(),
                ),
                spacing="2",
                align="center",
                background="var(--gray-a2)",
                border=f"1px solid {SURFACE_BORDER}",
                border_radius="20px",
                padding="4px 10px",
                cursor=rx.cond(is_linked, "pointer", "default"),
                on_click=State.set_dynamic_link_target(item["link_target_tab"], item["link_target_id"]),
            ),
            width="100%",
            id=item["flow_row_id"],
        ),
        # Standard event card (info / error)
        rx.center(
            rx.box(
                rx.hstack(
                    rx.icon(
                        rx.cond(is_error, "triangle-alert", "workflow"),
                        size=16,
                        color=rx.cond(is_error, "var(--red-9)", PRIMARY),
                    ),
                    rx.vstack(
                        rx.hstack(
                            rx.text(item["title"], font_size="12px", font_weight="700", color="var(--gray-12)"),
                            rx.cond(
                                item["topic_name"] != "",
                                rx.badge(item["topic_name"], color_scheme="teal", variant="soft", size="1"),
                                rx.box(),
                            ),
                            rx.cond(
                                item["state"] != "",
                                rx.badge(
                                    item["state"],
                                    color_scheme=rx.cond(item["state"] == "completed", "green", "red"),
                                    variant="soft",
                                    size="1",
                                ),
                                rx.box(),
                            ),
                            _trigger_score_badge(item["trigger_score"], item["trigger_score_color"]),
                            rx.cond(
                                item["auto_filled_count"] != "",
                                rx.tooltip(
                                    rx.badge(
                                        "AUTO ",
                                        rx.text.span(item["auto_filled_count"]),
                                        color_scheme="amber",
                                        variant="soft",
                                        size="1",
                                    ),
                                    content="Arguments auto-filled by the orchestrator",
                                ),
                            ),
                            rx.cond(
                                item["manual_filled_count"] != "",
                                rx.tooltip(
                                    rx.badge(
                                        "MANUAL ",
                                        rx.text.span(item["manual_filled_count"]),
                                        color_scheme="gray",
                                        variant="soft",
                                        size="1",
                                    ),
                                    content="Arguments bound manually in the topic YAML",
                                ),
                            ),
                            rx.cond(
                                is_linked,
                                rx.icon("arrow-up-right", size=12, color="var(--green-a10)"),
                            ),
                            rx.cond(
                                item["timestamp"] != "",
                                rx.text(item["timestamp"], font_size="11px", color="var(--gray-a8)"),
                                rx.box(),
                            ),
                            spacing="2",
                            align="center",
                            flex_wrap="wrap",
                        ),
                        rx.text(item["summary"], font_size="12px", color="var(--gray-a9)", line_height="1.45"),
                        # Expandable details accordion (only when detail fields exist)
                        rx.cond(
                            _has_flow_details(item),
                            _flow_event_detail_accordion(item),
                            rx.box(),
                        ),
                        # Per-row copy + raw JSON
                        _flow_row_actions(item),
                        align="start",
                        spacing="1",
                        width="100%",
                    ),
                    spacing="2",
                    align="start",
                    width="100%",
                ),
                width=["100%", "100%", "78%"],
                background=rx.cond(is_error, "var(--red-a3)", "var(--green-a2)"),
                border=rx.cond(is_error, "1px solid var(--red-a5)", "1px solid var(--green-a4)"),
                border_radius="12px",
                padding="10px 12px",
                cursor=rx.cond(is_linked, "pointer", "default"),
                on_click=State.set_dynamic_link_target(item["link_target_tab"], item["link_target_id"]),
                _hover=rx.cond(
                    is_linked,
                    {"border_color": "var(--green-a8)", "background": "var(--green-a3)"},
                    {},
                ),
                transition="border-color 0.15s ease, background 0.15s ease",
            ),
            width="100%",
            id=item["flow_row_id"],
        ),
    )


def _mcs_flow_item(item: dict) -> rx.Component:
    return rx.cond(item["kind"] == "message", _mcs_flow_message(item), _mcs_flow_event(item))


def _mcs_flow_group(group: dict) -> rx.Component:
    """Render one Conversation Flow group: either a collapsible plan card
    (with status pill + step count) or a flat run of loose items
    (messages, standalone errors)."""
    return rx.cond(
        group["is_plan"] != "",
        # Plan card — collapsible accordion with header
        rx.box(
            rx.accordion.root(
                rx.accordion.item(
                    header=rx.hstack(
                        rx.icon("git-branch", size=14, color=PRIMARY),
                        rx.text(
                            group["header_summary"],
                            font_size="12px",
                            font_weight="700",
                            color="var(--gray-12)",
                        ),
                        rx.spacer(),
                        _status_badge(group["status"], group["status_tone"]),
                        rx.cond(
                            group["first_timestamp"] != "",
                            rx.text(
                                group["first_timestamp"],
                                font_size="11px",
                                color="var(--gray-a8)",
                                font_family=_MONO,
                            ),
                        ),
                        spacing="2",
                        align="center",
                        width="100%",
                    ),
                    content=rx.box(
                        rx.vstack(
                            rx.foreach(
                                group["items"].to(list[dict]),  # type: ignore[union-attr]
                                _mcs_flow_item,
                            ),
                            spacing="3",
                            width="100%",
                            align="stretch",
                        ),
                        padding="10px 4px 0 4px",
                    ),
                    value="plan_open",
                ),
                type="single",
                collapsible=True,
                default_value="plan_open",  # plans default to open
                width="100%",
                variant="ghost",
            ),
            background="var(--green-a2)",
            border="1px solid var(--green-a4)",
            border_radius="10px",
            padding="8px 10px",
            width="100%",
        ),
        # Loose group — render items inline, no header
        rx.vstack(
            rx.foreach(
                group["items"].to(list[dict]),  # type: ignore[union-attr]
                _mcs_flow_item,
            ),
            spacing="3",
            width="100%",
            align="stretch",
        ),
    )


def _flow_filter_chip(label: str) -> rx.Component:
    """One toggle chip for the Conversation Flow type filter. Selected chips
    have a green background; clicking toggles via
    `State.toggle_mcs_flow_filter_chip(label)`."""
    is_active = State.mcs_flow_filter_types.contains(label)
    return rx.button(
        label,
        on_click=State.toggle_mcs_flow_filter_chip(label),
        size="1",
        variant=rx.cond(is_active, "solid", "soft"),
        color_scheme=rx.cond(is_active, "green", "gray"),
        cursor="pointer",
    )


def _mcs_conversation_flow_panel() -> rx.Component:
    return card(
        rx.hstack(
            rx.hstack(
                rx.icon("message-square", size=16, color=PRIMARY),
                rx.text("Conversation Flow", font_size="14px", font_weight="700", color="var(--gray-12)"),
                spacing="2",
                align="center",
            ),
            rx.spacer(),
            rx.badge(
                rx.cond(
                    State.mcs_conversation_flow_source == "snapshot",
                    "Snapshot Dialog View",
                    "Transcript View",
                ),
                color_scheme="green",
                variant="soft",
                size="1",
            ),
            align="center",
            width="100%",
            margin_bottom="10px",
        ),
        # Filter bar — text search across summary/text/thought/topic
        # + clickable type chips. Match-count chip on the right.
        rx.vstack(
            rx.hstack(
                rx.icon("search", size=14, color="var(--gray-a8)"),
                rx.input(
                    placeholder="Search messages, topics, thoughts…",
                    value=State.mcs_flow_filter_text,
                    on_change=State.set_mcs_flow_filter_text,
                    size="2",
                    width="100%",
                ),
                rx.cond(
                    State.mcs_flow_filter_active,
                    rx.button(
                        rx.icon("x", size=12),
                        rx.text("Clear", font_size="11px"),
                        on_click=State.clear_mcs_flow_filters,
                        size="1",
                        variant="soft",
                        color_scheme="gray",
                        cursor="pointer",
                    ),
                ),
                spacing="2",
                align="center",
                width="100%",
            ),
            rx.hstack(
                _flow_filter_chip("Messages"),
                _flow_filter_chip("Plans"),
                _flow_filter_chip("Actions"),
                _flow_filter_chip("Knowledge"),
                _flow_filter_chip("Traces"),
                _flow_filter_chip("Errors"),
                rx.spacer(),
                rx.cond(
                    State.mcs_flow_filter_active,
                    rx.text(
                        State.mcs_conversation_flow_match_count.to(str)
                        + " of "
                        + State.mcs_conversation_flow_total_count.to(str)
                        + " events",
                        font_size="11px",
                        color="var(--gray-a9)",
                        font_family=_MONO,
                    ),
                ),
                spacing="2",
                align="center",
                width="100%",
                flex_wrap="wrap",
            ),
            spacing="2",
            width="100%",
            margin_bottom="10px",
        ),
        rx.box(
            rx.vstack(
                rx.foreach(State.mcs_conversation_flow_groups_filtered, _mcs_flow_group),
                spacing="4",
                width="100%",
                align="stretch",
            ),
            width="100%",
            background="var(--gray-a2)",
            border=f"1px solid {SURFACE_BORDER}",
            border_radius="12px",
            padding=["10px", "12px", "14px"],
            max_height="720px",
            overflow_y="auto",
        ),
        width="100%",
    )


# ── Visual dashboard ──────────────────────────────────────────────────────────


def _mcs_kpi_card(item: dict) -> rx.Component:
    return rx.box(
        rx.text(item["label"], font_size="12px", color="var(--gray-a9)", font_weight="700"),
        rx.text(item["value"], font_size="26px", color="var(--gray-12)", font_weight="800", line_height="1.1"),
        rx.text(item["hint"], font_size="11px", color="var(--gray-a8)"),
        border=rx.cond(
            item["tone"] == "warn",
            "1px solid var(--amber-8)",
            f"1px solid {SURFACE_BORDER}",
        ),
        border_radius="12px",
        background="var(--gray-a2)",
        padding="12px 14px",
        width="100%",
    )


def _mcs_mix_row(item: dict) -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.hstack(
                rx.box(width="10px", height="10px", border_radius="999px", background=item["color"]),
                rx.text(item["label"], font_size="12px", color="var(--gray-12)", font_weight="600"),
                spacing="2",
                align="center",
            ),
            rx.spacer(),
            rx.text(item["count"], font_size="12px", color="var(--gray-12)", font_weight="700"),
            spacing="2",
            width="100%",
            align="center",
        ),
        rx.box(
            rx.box(
                height="8px",
                border_radius="999px",
                background=item["bar_color"],
                width=item["pct"],
                min_width="6px",
            ),
            height="8px",
            border_radius="999px",
            background="var(--gray-a3)",
            width="100%",
        ),
        rx.cond(
            item["min_fmt"] != "",
            rx.hstack(
                rx.text("min ", item["min_fmt"], font_size="10px", color="var(--gray-a9)"),
                rx.text("·", font_size="10px", color="var(--gray-a6)"),
                rx.text("avg ", item["avg_fmt"], font_size="10px", color="var(--gray-a9)", font_weight="600"),
                rx.text("·", font_size="10px", color="var(--gray-a6)"),
                rx.text("max ", item["max_fmt"], font_size="10px", color="var(--gray-a9)"),
                spacing="1",
                align="center",
                padding_top="2px",
            ),
            rx.fragment(),
        ),
        spacing="1",
        width="100%",
        align="start",
    )


def _mcs_highlight_chip(item: dict) -> rx.Component:
    tone_color = rx.match(
        item["tone"],
        ("good", "var(--green-9)"),
        ("bad", "var(--red-9)"),
        "var(--blue-9)",
    )
    tone_bg = rx.match(
        item["tone"],
        ("good", "var(--green-a3)"),
        ("bad", "var(--red-a3)"),
        "var(--blue-a3)",
    )
    return rx.box(
        rx.text(item["title"], font_size="11px", color="var(--gray-a9)", font_weight="700"),
        rx.text(item["value"], font_size="20px", color=tone_color, font_weight="800", line_height="1.1"),
        padding="10px 12px",
        border_radius="10px",
        background=tone_bg,
        min_width="120px",
    )


def _mcs_conversation_visual_dashboard() -> rx.Component:
    return card(
        rx.vstack(
            # Header
            rx.hstack(
                rx.hstack(
                    rx.icon("chart-column", size=16, color=PRIMARY),
                    rx.text("Conversation Analytics", font_size="14px", font_weight="700", color="var(--gray-12)"),
                    spacing="2",
                    align="center",
                ),
                rx.spacer(),
                rx.badge("Visual Summary", color_scheme="green", variant="soft", size="1"),
                width="100%",
                align="center",
            ),
            # KPI cards grid
            rx.grid(
                rx.foreach(State.mcs_conv_kpis, _mcs_kpi_card),
                columns="4",
                gap="10px",
                width="100%",
            ),
            # Event mix + latency distribution
            rx.grid(
                rx.box(
                    rx.text(
                        "Event Mix",
                        font_size="13px",
                        color="var(--gray-12)",
                        font_weight="700",
                    ),
                    rx.text(
                        "Breakdown of all events in the conversation by category.",
                        font_size="11px",
                        color="var(--gray-a9)",
                        margin_bottom="8px",
                    ),
                    rx.vstack(rx.foreach(State.mcs_conv_event_mix, _mcs_mix_row), spacing="2", width="100%"),
                    border=f"1px solid {SURFACE_BORDER}",
                    border_radius="12px",
                    background="var(--gray-a2)",
                    padding="12px",
                ),
                rx.box(
                    rx.text(
                        "Turn Latency Distribution",
                        font_size="13px",
                        color="var(--gray-12)",
                        font_weight="700",
                    ),
                    rx.text(
                        "How long the agent takes to respond — green is fast, red is slow.",
                        font_size="11px",
                        color="var(--gray-a9)",
                        margin_bottom="8px",
                    ),
                    rx.vstack(rx.foreach(State.mcs_conv_latency_bands, _mcs_mix_row), spacing="2", width="100%"),
                    border=f"1px solid {SURFACE_BORDER}",
                    border_radius="12px",
                    background="var(--gray-a2)",
                    padding="12px",
                ),
                columns="2",
                gap="10px",
                width="100%",
            ),
            # Highlights
            rx.hstack(
                rx.foreach(State.mcs_conv_highlights, _mcs_highlight_chip),
                spacing="2",
                width="100%",
                flex_wrap="wrap",
            ),
            spacing="3",
            width="100%",
            align="start",
        ),
        width="100%",
    )


# ── Reusable table helpers ────────────────────────────────────────────────


def _grid_header(*cols: str, template: str) -> rx.Component:
    """Render a header row for a data grid."""
    return rx.grid(
        *[rx.text(c, font_size="12px", color="var(--gray-a9)", font_weight="700") for c in cols],
        columns=template,
        gap="8px",
        padding_y="8px",
        width="100%",
    )


def _grid_row(cells: list[rx.Component], template: str) -> rx.Component:
    """Render a body row for a data grid."""
    return rx.grid(
        *cells,
        columns=template,
        gap="8px",
        align="center",
        padding_y="6px",
        border_bottom=f"1px solid {SURFACE_BORDER}",
        width="100%",
    )


def _data_table(header_cols: list[str], template: str, items, row_fn) -> rx.Component:
    """Render a complete data table with header + foreach rows."""
    return rx.box(
        _grid_header(*header_cols, template=template),
        rx.foreach(items, row_fn),
        width="100%",
        border=f"1px solid {SURFACE_BORDER}",
        border_radius="8px",
        padding_x="12px",
        background="var(--gray-a2)",
    )


def _status_badge(text, tone) -> rx.Component:
    """Colored status badge."""
    return rx.badge(
        text,
        color_scheme=rx.match(
            tone,
            ("good", "green"),
            ("bad", "red"),
            ("info", "blue"),
            ("warn", "amber"),
            "gray",
        ),
        variant="soft",
        size="1",
    )


def _mermaid_block(source_var) -> rx.Component:
    """Render a mermaid diagram from a state var containing raw mermaid source."""
    return rx.cond(
        source_var != "",
        rx.box(
            rx.el.pre(
                source_var,
                class_name="mermaid",
                font_size="13px",
            ),
            width="100%",
            padding="16px",
            background="var(--gray-a2)",
            border=f"1px solid {SURFACE_BORDER}",
            border_radius="12px",
            overflow_x="auto",
        ),
    )


# ── Profile panel ────────────────────────────────────────────────────────


def _mcs_profile_ai_row(item: dict) -> rx.Component:
    return info_row(item["property"], item["value"])


def _mcs_profile_starter_chip(item: dict) -> rx.Component:
    return rx.box(
        rx.text(item["title"], font_size="11px", font_weight="700", color="var(--gray-12)"),
        rx.text(item["message"], font_size="11px", color="var(--gray-a9)"),
        padding="6px 10px",
        border_radius="8px",
        background="var(--green-a2)",
        border="1px solid var(--green-a4)",
    )


def _mcs_profile_meta_row(item: dict) -> rx.Component:
    return info_row(item["property"], item["value"])


def _mcs_profile_env_row(item: dict) -> rx.Component:
    return _grid_row(
        [
            rx.text(item["name"], font_size="13px", color="var(--gray-12)", font_family=_MONO),
            rx.text(item["type"], font_size="13px", color="var(--gray-a9)"),
            rx.text(item["value"], font_size="13px", color="var(--gray-11)"),
        ],
        template="2fr 1fr 2fr",
    )


def _mcs_profile_connector_row(item: dict) -> rx.Component:
    return _grid_row(
        [
            rx.text(item["name"], font_size="13px", color="var(--gray-12)"),
            rx.text(item["type"], font_size="13px", color="var(--gray-a9)"),
            rx.text(item["description"], font_size="13px", color="var(--gray-11)"),
        ],
        template="2fr 1fr 3fr",
    )


def _mcs_profile_conn_ref_row(item: dict) -> rx.Component:
    return _grid_row(
        [
            rx.text(item["name"], font_size="13px", color="var(--gray-12)"),
            rx.text(item["connector"], font_size="13px", color="var(--gray-a9)", font_family=_MONO),
            rx.text(item["custom"], font_size="13px", color="var(--gray-11)"),
        ],
        template="2fr 2fr 1fr",
    )


def _mcs_profile_conn_def_row(item: dict) -> rx.Component:
    return _grid_row(
        [
            rx.text(item["name"], font_size="13px", color="var(--gray-12)"),
            rx.text(item["type"], font_size="13px", color="var(--gray-a9)"),
            rx.text(item["custom"], font_size="13px", color="var(--gray-11)"),
            rx.text(item["operations"], font_size="13px", color="var(--gray-11)", text_align="right"),
            rx.cond(
                item["mcp"] == "Yes",
                rx.badge("MCP", color_scheme="purple", variant="soft", size="1"),
                rx.text(item["mcp"], font_size="13px", color="var(--gray-a9)"),
            ),
        ],
        template="2fr 1fr 1fr 1fr 1fr",
    )


def _mcs_profile_quick_win_row(item: dict) -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.badge(
                item["severity"],
                color_scheme=rx.match(item["severity"], ("warn", "amber"), ("info", "blue"), "gray"),
                variant="soft",
                size="1",
            ),
            rx.text(item["text"], font_size="13px", color="var(--gray-12)"),
            width="100%",
            align="center",
            spacing="2",
        ),
        rx.cond(
            item["detail"] != "",
            rx.text(
                item["detail"],
                font_size="12px",
                color="var(--gray-a9)",
                padding_left="32px",
            ),
        ),
        width="100%",
        spacing="1",
        padding_y="4px",
    )


def _mcs_profile_overlap_row(item: dict) -> rx.Component:
    return _grid_row(
        [
            rx.text(item["topic_a"], font_size="13px", color="var(--gray-12)"),
            rx.text(item["topic_b"], font_size="13px", color="var(--gray-12)"),
            rx.text(item["overlap_pct"], font_size="13px", color="var(--amber-11)", font_weight="600"),
            rx.text(item["shared_tokens"], font_size="12px", color="var(--gray-a9)", font_family=_MONO),
        ],
        template="2fr 2fr 1fr 3fr",
    )


def _mcs_profile_panel() -> rx.Component:
    return rx.vstack(
        # Instruction drift warning
        rx.cond(
            State.mcs_profile_instruction_drift.length() > 0,  # type: ignore[union-attr]
            rx.box(
                rx.hstack(
                    rx.icon("triangle-alert", size=16, color="var(--amber-9)"),
                    rx.text("Instruction Drift Detected", font_size="14px", font_weight="700", color="var(--amber-11)"),
                    spacing="2",
                    align="center",
                ),
                rx.text(
                    rx.cond(
                        State.mcs_profile_instruction_drift.contains("change_ratio"),  # type: ignore[union-attr]
                        State.mcs_profile_instruction_drift["change_ratio"].to(str),
                        "",
                    ),
                    font_size="13px",
                    color="var(--amber-11)",
                    margin_top="4px",
                ),
                background="var(--amber-a2)",
                border="1px solid var(--amber-a5)",
                border_radius="8px",
                padding="12px 16px",
                width="100%",
            ),
        ),
        # KPI grid
        rx.grid(
            rx.foreach(State.mcs_profile_kpis, _mcs_kpi_card),
            columns="4",
            gap="10px",
            width="100%",
        ),
        # AI Configuration
        rx.cond(
            State.mcs_profile_ai_config.length() > 0,  # type: ignore[union-attr]
            card(
                section_heading("AI Configuration"),
                rx.vstack(
                    rx.foreach(State.mcs_profile_ai_config, _mcs_profile_ai_row),
                    spacing="1",
                    width="100%",
                    padding_top="8px",
                ),
                rx.cond(
                    State.mcs_profile_starters.length() > 0,  # type: ignore[union-attr]
                    rx.vstack(
                        sub_heading("Conversation Starters"),
                        rx.hstack(
                            rx.foreach(State.mcs_profile_starters, _mcs_profile_starter_chip),
                            spacing="2",
                            flex_wrap="wrap",
                            width="100%",
                        ),
                        spacing="2",
                        padding_top="12px",
                        width="100%",
                    ),
                ),
                width="100%",
            ),
        ),
        # System Instructions (accordion)
        rx.cond(
            State.mcs_profile_instructions_text != "",
            card(
                rx.accordion.root(
                    rx.accordion.item(
                        header=rx.hstack(
                            rx.text("System Instructions", font_size="13px", font_weight="600", color="var(--gray-12)"),
                            rx.text(State.mcs_profile_instructions_len, font_size="12px", color="var(--gray-a9)"),
                            spacing="2",
                            align="center",
                        ),
                        content=rx.el.pre(
                            State.mcs_profile_instructions_text,
                            font_size="12px",
                            color="var(--gray-11)",
                            white_space="pre-wrap",
                            word_break="break-word",
                            font_family="var(--font-mono)",
                            background="var(--gray-a2)",
                            border="1px solid var(--gray-a4)",
                            border_radius="6px",
                            padding="12px",
                            max_height="400px",
                            overflow_y="auto",
                        ),
                    ),
                    collapsible=True,
                    variant="ghost",
                    width="100%",
                ),
                width="100%",
            ),
        ),
        # Security row
        rx.hstack(
            rx.foreach(State.mcs_profile_security_chips, _mcs_highlight_chip),
            spacing="2",
            width="100%",
            flex_wrap="wrap",
        ),
        # Bot Metadata
        card(
            section_heading("Bot Metadata"),
            rx.vstack(
                rx.foreach(State.mcs_profile_bot_meta, _mcs_profile_meta_row),
                spacing="1",
                width="100%",
                padding_top="8px",
            ),
            width="100%",
        ),
        # Environment Variables
        rx.cond(
            State.mcs_profile_env_vars.length() > 0,  # type: ignore[union-attr]
            card(
                section_heading("Environment Variables"),
                _data_table(
                    ["Name", "Type", "Value"],
                    "2fr 1fr 2fr",
                    State.mcs_profile_env_vars,
                    _mcs_profile_env_row,
                ),
                width="100%",
            ),
        ),
        # Connectors
        rx.cond(
            State.mcs_profile_connectors.length() > 0,  # type: ignore[union-attr]
            card(
                section_heading("Connectors"),
                _data_table(
                    ["Name", "Type", "Description"],
                    "2fr 1fr 3fr",
                    State.mcs_profile_connectors,
                    _mcs_profile_connector_row,
                ),
                width="100%",
            ),
        ),
        # Connection References
        rx.cond(
            State.mcs_profile_conn_refs.length() > 0,  # type: ignore[union-attr]
            card(
                section_heading("Connection References"),
                _data_table(
                    ["Name", "Connector", "Custom"],
                    "2fr 2fr 1fr",
                    State.mcs_profile_conn_refs,
                    _mcs_profile_conn_ref_row,
                ),
                width="100%",
            ),
        ),
        # Connector Definitions
        rx.cond(
            State.mcs_profile_conn_defs.length() > 0,  # type: ignore[union-attr]
            card(
                section_heading("Connector Definitions"),
                _data_table(
                    ["Name", "Type", "Custom", "Operations", "MCP"],
                    "2fr 1fr 1fr 1fr 1fr",
                    State.mcs_profile_conn_defs,
                    _mcs_profile_conn_def_row,
                ),
                width="100%",
            ),
        ),
        # Model Configuration (absorbed from Model tab)
        rx.cond(
            State.mcs_model_kpis.length() > 0,  # type: ignore[union-attr]
            card(
                rx.hstack(
                    rx.icon("bar-chart-2", size=16, color="var(--violet-9)"),
                    section_heading("Model Configuration"),
                    spacing="2",
                    align="center",
                ),
                rx.hstack(
                    rx.foreach(State.mcs_model_kpis, _mcs_kpi_card),
                    spacing="3",
                    width="100%",
                    overflow_x="auto",
                    padding_y="8px",
                ),
                rx.cond(
                    State.mcs_model_strengths.length() > 0,  # type: ignore[union-attr]
                    rx.grid(
                        rx.box(
                            rx.hstack(
                                rx.icon("check-circle", size=14, color=PRIMARY),
                                rx.text("Strengths", font_size="12px", font_weight="700", color="var(--gray-a9)"),
                                spacing="2",
                                align="center",
                            ),
                            rx.vstack(
                                rx.foreach(
                                    State.mcs_model_strengths,
                                    lambda s: rx.text(f"• {s}", font_size="12px", color="var(--gray-11)"),
                                ),
                                spacing="1",
                                padding_top="6px",
                            ),
                            padding="12px",
                            border=f"1px solid {SURFACE_BORDER}",
                            border_radius="10px",
                        ),
                        rx.box(
                            rx.hstack(
                                rx.icon("alert-triangle", size=14, color="var(--amber-9)"),
                                rx.text("Limitations", font_size="12px", font_weight="700", color="var(--gray-a9)"),
                                spacing="2",
                                align="center",
                            ),
                            rx.vstack(
                                rx.foreach(
                                    State.mcs_model_limitations,
                                    lambda s: rx.text(f"• {s}", font_size="12px", color="var(--gray-11)"),
                                ),
                                spacing="1",
                                padding_top="6px",
                            ),
                            padding="12px",
                            border=f"1px solid {SURFACE_BORDER}",
                            border_radius="10px",
                        ),
                        columns="1fr 1fr",
                        gap="12px",
                        width="100%",
                        padding_top="8px",
                    ),
                ),
                rx.cond(
                    State.mcs_model_recommendation != "",
                    rx.box(
                        rx.hstack(
                            rx.icon("lightbulb", size=14, color="var(--amber-9)"),
                            rx.text("Recommendation", font_size="12px", font_weight="700", color="var(--gray-a9)"),
                            spacing="2",
                            align="center",
                        ),
                        rx.text(
                            State.mcs_model_recommendation, font_size="13px", color="var(--gray-11)", padding_top="4px"
                        ),
                        padding="12px",
                        border=f"1px solid {SURFACE_BORDER}",
                        border_radius="10px",
                        margin_top="8px",
                    ),
                ),
                width="100%",
            ),
        ),
        # Custom findings
        _mcs_custom_findings_section(),
        spacing="4",
        width="100%",
    )


# ── Tools panel ──────────────────────────────────────────────────────────


def _mcs_tool_row(item: dict) -> rx.Component:
    is_target = State.mcs_highlight_target_id == item["link_id"]
    return rx.vstack(
        rx.grid(
            rx.text(item["name"], font_size="13px", color="var(--gray-12)", font_weight="500"),
            rx.badge(
                item["tool_type"],
                color_scheme=rx.match(
                    item["type_color"],
                    ("blue", "blue"),
                    ("green", "green"),
                    ("teal", "teal"),
                    ("cyan", "cyan"),
                    ("purple", "purple"),
                    ("amber", "amber"),
                    "gray",
                ),
                variant="soft",
                size="1",
            ),
            rx.text(item["connector"], font_size="13px", color="var(--gray-a9)"),
            rx.text(item["mode"], font_size="13px", color="var(--gray-11)"),
            rx.badge(
                item["state"],
                color_scheme=rx.cond(item["state"] == "Active", "green", "gray"),
                variant="soft",
                size="1",
            ),
            rx.text(
                item["description"],
                font_size="12px",
                color="var(--gray-a9)",
                overflow="hidden",
                text_overflow="ellipsis",
                white_space="nowrap",
            ),
            columns="2fr 1fr 1fr 1fr 1fr 3fr",
            gap="8px",
            align="center",
            padding_y="6px",
            border_bottom=f"1px solid {SURFACE_BORDER}",
            width="100%",
        ),
        _settings_explained_accordion(item),
        spacing="0",
        width="100%",
        id=item["row_id"],
        border_left=rx.cond(is_target, "3px solid var(--green-9)", "3px solid transparent"),
        background=rx.cond(is_target, "var(--green-a2)", "transparent"),
        transition="border-color 0.2s ease, background 0.2s ease",
    )


def _mcs_tools_ext_detail_row(item: dict) -> rx.Component:
    return _grid_row(
        [
            rx.text(item["topic"], font_size="13px", color="var(--gray-12)"),
            rx.text(item["kind"], font_size="13px", color="var(--gray-a9)"),
            rx.text(item["connector"], font_size="13px", color="var(--gray-11)"),
            rx.text(item["operation"], font_size="13px", color="var(--gray-a9)"),
        ],
        template="2fr 1fr 2fr 2fr",
    )


def _mcs_tools_stats_row(item: dict) -> rx.Component:
    """Statistics table row for tool call analysis."""
    return _grid_row(
        [
            rx.text(item["tool"], font_size="13px", color="var(--gray-12)", font_weight="500"),
            rx.badge(item["type"], color_scheme="gray", variant="soft", size="1"),
            rx.text(item["calls"], font_size="13px", color="var(--gray-11)"),
            rx.badge(
                item["success_rate"],
                color_scheme=item["success_color"],
                variant="soft",
                size="1",
            ),
            rx.text(item["avg_duration"], font_size="13px", color="var(--gray-11)"),
            rx.text(item["total_duration"], font_size="13px", color="var(--gray-a9)"),
        ],
        template="2fr 1fr 0.5fr 1fr 1fr 1fr",
    )


def _mcs_tools_chain_card(item: dict) -> rx.Component:
    """Summary card for an async/polling chain."""
    return rx.box(
        rx.hstack(
            rx.text(item["tool"], font_size="13px", font_weight="600", color="var(--gray-12)"),
            rx.badge(item["call_count_label"], color_scheme="purple", variant="soft", size="1"),
            rx.text(item["total_duration"], font_size="12px", color="var(--gray-a9)"),
            rx.badge(
                item["final_state"],
                color_scheme=rx.cond(item["final_state"] == "completed", "green", "red"),
                variant="soft",
                size="1",
            ),
            spacing="2",
            align="center",
        ),
        rx.cond(
            item["status_label"] != "",
            rx.hstack(
                rx.text("Status:", font_size="11px", color="var(--gray-a8)"),
                rx.badge(item["status_label"], color_scheme="blue", variant="outline", size="1"),
                spacing="1",
                align="center",
                padding_top="4px",
            ),
        ),
        rx.cond(
            item["correlation_label"] != "",
            rx.text(
                rx.text.span("Correlation: ", font_weight="600", color="var(--gray-a8)"),
                rx.text.span(item["correlation_label"], font_size="11px", color="var(--gray-11)"),
                font_size="11px",
                padding_top="2px",
            ),
        ),
        padding="10px 14px",
        border=f"1px solid {SURFACE_BORDER}",
        border_radius="8px",
        background="var(--gray-a2)",
        width="100%",
    )


def _mcs_tools_reasoning_row(item: dict) -> rx.Component:
    """Reasoning table row."""
    return _grid_row(
        [
            rx.text(item["index"], font_size="13px", color="var(--gray-a9)"),
            rx.text(item["tool"], font_size="13px", color="var(--gray-12)", font_weight="500"),
            rx.text(
                item["thought"], font_size="12px", color="var(--gray-11)", overflow="hidden", text_overflow="ellipsis"
            ),
        ],
        template="0.3fr 2fr 5fr",
    )


def _mcs_tools_detail_card(item: dict) -> rx.Component:
    """Expandable detail card for a single tool call."""
    status_color = rx.cond(item["state"] == "completed", "green", "red")

    header = rx.hstack(
        rx.text(item["index_label"], font_size="12px", color="var(--gray-a8)", font_weight="600"),
        rx.text(item["tool"], font_size="13px", font_weight="600", color="var(--gray-12)"),
        rx.cond(
            item["tool_type"] != "",
            rx.badge(item["tool_type"], color_scheme="gray", variant="soft", size="1"),
        ),
        rx.badge(item["state"], color_scheme=status_color, variant="soft", size="1"),
        rx.text(item["duration"], font_size="12px", color="var(--gray-a9)"),
        rx.cond(
            item["chain_id"] != "",
            rx.badge("chain", color_scheme="purple", variant="outline", size="1"),
        ),
        spacing="2",
        align="center",
        width="100%",
    )

    # Build content sections
    content_parts = []

    # Thought
    content_parts.append(
        rx.cond(
            item["thought"] != "",
            rx.box(
                rx.text(
                    item["thought"], font_size="12px", font_style="italic", color="var(--gray-a9)", line_height="1.4"
                ),
                padding="8px 12px",
                border_left="3px solid var(--green-a6)",
                background="var(--green-a2)",
                border_radius="0 6px 6px 0",
                width="100%",
            ),
        )
    )

    # Arguments — pre-computed as formatted text
    content_parts.append(
        rx.cond(
            item["arguments_text"] != "",
            rx.vstack(
                rx.text("Arguments", font_size="11px", font_weight="600", color="var(--gray-a8)"),
                rx.box(
                    rx.el.pre(
                        item["arguments_text"],
                        font_size="11px",
                        color="var(--gray-11)",
                        white_space="pre-wrap",
                        font_family="var(--font-mono)",
                    ),
                    width="100%",
                    padding="6px 10px",
                    border=f"1px solid {SURFACE_BORDER}",
                    border_radius="6px",
                    background="var(--gray-a2)",
                ),
                spacing="1",
                width="100%",
            ),
        )
    )

    # Observation summary
    content_parts.append(
        rx.cond(
            item["observation_summary"] != "",
            rx.vstack(
                rx.text("Response", font_size="11px", font_weight="600", color="var(--gray-a8)"),
                rx.text(item["observation_summary"], font_size="12px", color="var(--gray-11)"),
                spacing="1",
                width="100%",
            ),
        )
    )

    # Raw JSON (interactive tree viewer)
    content_parts.append(
        rx.cond(
            item["observation_json"] != "",
            rx.vstack(
                rx.text("Response JSON", font_size="11px", font_weight="600", color="var(--gray-a8)"),
                rx.box(
                    rx.el.div(
                        class_name="json-tree-viewer",
                        custom_attrs={"data-json": item["observation_json"]},
                    ),
                    max_height="400px",
                    overflow_y="auto",
                    width="100%",
                    padding="10px 14px",
                    background="var(--gray-a2)",
                    border=f"1px solid {SURFACE_BORDER}",
                    border_radius="8px",
                ),
                spacing="1",
                width="100%",
            ),
        )
    )

    # Error
    content_parts.append(
        rx.cond(
            item["error"] != "",
            rx.text(item["error"], font_size="12px", color="var(--red-9)", font_weight="500"),
        )
    )

    return rx.accordion.root(
        rx.accordion.item(
            header=header,
            content=rx.vstack(
                *content_parts,
                spacing="3",
                width="100%",
                padding_top="8px",
            ),
            value=item["accordion_value"],
        ),
        collapsible=True,
        width="100%",
        variant="ghost",
        border=f"1px solid {SURFACE_BORDER}",
        border_radius="10px",
        background="var(--gray-a2)",
    )


def _mcs_tools_panel() -> rx.Component:
    return rx.vstack(
        # KPI grid
        rx.grid(
            rx.foreach(State.mcs_tools_kpis, _mcs_kpi_card),
            columns="4",
            gap="10px",
            width="100%",
        ),
        # Tool table (static — from YAML)
        rx.cond(
            State.mcs_tools_rows.length() > 0,  # type: ignore[union-attr]
            card(
                section_heading("Tool Inventory"),
                rx.box(
                    _grid_header(
                        "Tool", "Type", "Connector", "Mode", "State", "Description", template="2fr 1fr 1fr 1fr 1fr 3fr"
                    ),
                    rx.foreach(State.mcs_tools_rows, _mcs_tool_row),
                    width="100%",
                    border=f"1px solid {SURFACE_BORDER}",
                    border_radius="8px",
                    padding_x="12px",
                    background="var(--gray-a2)",
                    overflow_x="auto",
                ),
                width="100%",
            ),
        ),
        # Integration map
        _mermaid_block(State.mcs_tools_mermaid),
        # External calls detail
        rx.cond(
            State.mcs_tools_external_calls.length() > 0,  # type: ignore[union-attr]
            card(
                section_heading("External Calls"),
                _data_table(
                    ["Topic", "Action Kind", "Connector", "Operation"],
                    "2fr 1fr 2fr 2fr",
                    State.mcs_tools_external_calls,
                    _mcs_tools_ext_detail_row,
                ),
                width="100%",
            ),
        ),
        # ── Runtime tool call analysis ──────────────────────────────────────
        rx.cond(
            State.has_mcs_tools_runtime,
            rx.vstack(
                rx.divider(color_scheme="green", size="4", margin_y="8px"),
                rx.text("Runtime Tool Call Analysis", font_size="15px", font_weight="700", color="var(--gray-12)"),
                # Tool call flow (Mermaid)
                _mermaid_block(State.mcs_tools_flow_mermaid),
                # Tool statistics
                rx.cond(
                    State.mcs_tools_stats_rows.length() > 0,  # type: ignore[union-attr]
                    card(
                        section_heading("Tool Statistics"),
                        _data_table(
                            ["Tool", "Type", "Calls", "Success", "Avg Duration", "Total"],
                            "2fr 1fr 0.5fr 1fr 1fr 1fr",
                            State.mcs_tools_stats_rows,
                            _mcs_tools_stats_row,
                        ),
                        width="100%",
                    ),
                ),
                # Async chains
                rx.cond(
                    State.mcs_tools_chain_rows.length() > 0,  # type: ignore[union-attr]
                    card(
                        section_heading("Async / Polling Chains"),
                        rx.vstack(
                            rx.foreach(State.mcs_tools_chain_rows, _mcs_tools_chain_card),
                            spacing="2",
                            width="100%",
                        ),
                        width="100%",
                    ),
                ),
                # Orchestrator reasoning
                rx.cond(
                    State.mcs_tools_reasoning_rows.length() > 0,  # type: ignore[union-attr]
                    card(
                        section_heading("Orchestrator Reasoning"),
                        _data_table(
                            ["#", "Tool", "Thought"],
                            "0.3fr 2fr 5fr",
                            State.mcs_tools_reasoning_rows,
                            _mcs_tools_reasoning_row,
                        ),
                        width="100%",
                    ),
                ),
                # Tool call details (expandable)
                rx.cond(
                    State.mcs_tools_detail_rows.length() > 0,  # type: ignore[union-attr]
                    card(
                        section_heading("Tool Call Details"),
                        rx.vstack(
                            rx.foreach(State.mcs_tools_detail_rows, _mcs_tools_detail_card),
                            spacing="2",
                            width="100%",
                        ),
                        width="100%",
                    ),
                ),
                spacing="4",
                width="100%",
            ),
        ),
        # Multi-Agent Delegation (moved from Insights)
        rx.cond(
            State.mcs_ins_deleg_kpis.length() > 0,  # type: ignore[union-attr]
            card(
                _ins_card_header(
                    "network",
                    "var(--cyan-9)",
                    "Multi-Agent Delegation",
                    "How the orchestrator delegates to child and connected agents.",
                ),
                rx.hstack(
                    rx.foreach(State.mcs_ins_deleg_kpis, _ins_kpi),
                    spacing="3",
                    width="100%",
                    overflow_x="auto",
                    padding_y="12px",
                ),
                rx.cond(
                    State.mcs_ins_deleg_rows.length() > 0,  # type: ignore[union-attr]
                    rx.box(
                        rx.grid(
                            rx.text("Agent", **_INS_HEADER_CELL),
                            rx.text("Type", **_INS_HEADER_CELL),
                            rx.text("State", **_INS_HEADER_CELL),
                            rx.text("Duration", **_INS_HEADER_CELL, text_align="right"),
                            rx.text("Reasoning", **_INS_HEADER_CELL),
                            columns="1.2fr 0.8fr 0.8fr 0.7fr 3fr",
                            gap="8px",
                            padding_y="8px",
                            border_bottom=f"2px solid {SURFACE_BORDER}",
                            width="100%",
                        ),
                        rx.foreach(State.mcs_ins_deleg_rows, _ins_deleg_row),
                        width="100%",
                    ),
                ),
                rx.cond(
                    State.mcs_ins_deleg_warnings.length() > 0,  # type: ignore[union-attr]
                    rx.box(
                        rx.foreach(
                            State.mcs_ins_deleg_warnings,
                            lambda w: rx.text(f"⚠ {w}", font_size="12px", color="var(--amber-9)"),
                        ),
                        padding_top="8px",
                        width="100%",
                    ),
                ),
                width="100%",
            ),
        ),
        spacing="4",
        width="100%",
    )


# ── Knowledge panel ──────────────────────────────────────────────────────


def _mcs_ks_source_row(item: dict) -> rx.Component:
    return _grid_row(
        [
            rx.text(item["name"], font_size="13px", color="var(--gray-12)"),
            rx.text(item["source_type"], font_size="13px", color="var(--gray-a9)"),
            rx.text(item["site"], font_size="13px", color="var(--gray-a9)"),
            _status_badge(item["status"], item["status_tone"]),
            rx.text(item["trigger"], font_size="12px", color="var(--gray-a9)"),
        ],
        template="2fr 1fr 1fr 1fr 1fr",
    )


def _mcs_ks_file_row(item: dict) -> rx.Component:
    return _grid_row(
        [
            rx.text(item["name"], font_size="13px", color="var(--gray-12)"),
            rx.text(item["file_type"], font_size="13px", color="var(--gray-a9)"),
            _status_badge(item["status"], item["status_tone"]),
        ],
        template="3fr 1fr 1fr",
    )


def _mcs_ks_coverage_row(item: dict) -> rx.Component:
    return _grid_row(
        [
            rx.text(item["name"], font_size="13px", color="var(--gray-12)"),
            rx.text(item["source_type"], font_size="13px", color="var(--gray-a9)"),
            rx.text(item["state"], font_size="13px", color="var(--gray-11)"),
            rx.text(item["trigger"], font_size="12px", color="var(--gray-a9)"),
            rx.text(item["notes"], font_size="12px", color="var(--gray-a9)"),
        ],
        template="2fr 1fr 1fr 1fr 2fr",
    )


def _mcs_ks_item(item: dict) -> rx.Component:
    """Dispatch between group header and search card."""
    return rx.cond(
        item["kind"] == "header",
        rx.hstack(
            rx.icon("message-circle", size=14, color=PRIMARY),
            rx.text(item["user_message"], font_size="14px", font_weight="600", color="var(--gray-12)"),
            spacing="2",
            align="center",
            padding_y="8px",
            padding_top="12px",
            width="100%",
        ),
        _mcs_ks_search_card(item),
    )


def _mcs_ks_search_card(item: dict) -> rx.Component:
    return card(
        rx.vstack(
            # Header
            rx.hstack(
                rx.badge(f"#{item['index']}", color_scheme="green", variant="soft", size="1"),
                rx.text(item["query"], font_size="13px", font_weight="600", color="var(--gray-12)", flex="1"),
                _status_badge(item["grounding_label"], item["grounding_tone"]),
                width="100%",
                align="center",
                spacing="2",
            ),
            # Meta row
            rx.hstack(
                rx.cond(
                    item["keywords"] != "—",
                    rx.text(item["keywords"], font_size="12px", color="var(--gray-a9)", font_style="italic"),
                ),
                rx.spacer(),
                rx.hstack(
                    rx.text(item["sources"], font_size="11px", color="var(--gray-a8)"),
                    rx.text("·", color="var(--gray-a6)"),
                    rx.text(item["duration"], font_size="12px", color="var(--gray-a8)", font_family=_MONO),
                    spacing="2",
                    align="center",
                ),
                width="100%",
                align="center",
            ),
            # Thought
            rx.cond(
                item["thought"] != "",
                rx.text(
                    item["thought"], font_size="12px", color="var(--gray-a9)", font_style="italic", padding_y="2px"
                ),
            ),
            # Output sources
            rx.cond(
                item["output_sources"] != "",
                rx.hstack(
                    rx.text("Sources used:", font_size="11px", color="var(--gray-a9)", font_weight="600"),
                    rx.text(item["output_sources"], font_size="11px", color="var(--gray-11)"),
                    spacing="2",
                    align="center",
                ),
            ),
            # Efficiency
            rx.cond(
                item["efficiency"] != "",
                rx.text(item["efficiency"], font_size="11px", color="var(--gray-a9)"),
            ),
            # Errors
            rx.cond(
                item["errors"] != "",
                rx.box(
                    rx.hstack(
                        rx.icon("triangle-alert", size=12, color="var(--red-9)"),
                        rx.text(item["errors"], font_size="12px", color="var(--red-11)"),
                        spacing="2",
                        align="center",
                    ),
                    background="var(--red-a2)",
                    border="1px solid var(--red-a4)",
                    border_radius="6px",
                    padding="4px 8px",
                ),
            ),
            # Results
            rx.cond(
                item["results_text"] != "",
                rx.box(
                    rx.hstack(
                        rx.text(item["result_count"], font_size="11px", color="var(--gray-a9)", font_weight="600"),
                        rx.text("result(s) retrieved:", font_size="11px", color="var(--gray-a9)", font_weight="600"),
                        spacing="1",
                        align="center",
                        margin_bottom="4px",
                    ),
                    rx.el.pre(
                        item["results_text"],
                        font_size="11px",
                        color="var(--gray-11)",
                        white_space="pre-wrap",
                        word_break="break-all",
                        overflow_wrap="anywhere",
                        font_family=_MONO,
                        line_height="1.6",
                        margin="0",
                    ),
                    background="var(--gray-a2)",
                    border=f"1px solid {SURFACE_BORDER}",
                    border_radius="6px",
                    padding="8px 10px",
                    width="100%",
                    overflow="hidden",
                ),
            ),
            # Source URLs
            rx.cond(
                item["has_urls"] != "",
                rx.hstack(
                    rx.icon("external-link", size=12, color="var(--gray-a8)"),
                    rx.text("Sources:", font_size="11px", color="var(--gray-a9)", font_weight="600"),
                    rx.text(item["has_urls"], font_size="11px", color=PRIMARY, word_break="break-all"),
                    spacing="2",
                    align="start",
                    flex_wrap="wrap",
                    padding_top="4px",
                ),
            ),
            spacing="2",
            width="100%",
        ),
        width="100%",
        padding="14px",
    )


def _mcs_ks_custom_step(item: dict) -> rx.Component:
    return rx.hstack(
        rx.badge(
            item["status"],
            color_scheme=rx.match(item["status"], ("completed", "green"), ("failed", "red"), "gray"),
            variant="soft",
            size="1",
        ),
        rx.text(item["name"], font_size="13px", color="var(--gray-12)", font_weight="500"),
        rx.cond(
            item["thought"] != "",
            rx.text(item["thought"], font_size="12px", color="var(--gray-a9)", font_style="italic"),
        ),
        rx.cond(item["error"] != "", rx.text(item["error"], font_size="12px", color="var(--red-11)")),
        rx.text(item["duration"], font_size="12px", color="var(--gray-a8)", font_family=_MONO),
        width="100%",
        align="center",
        spacing="2",
        padding_y="4px",
    )


def _gen_trace_result_row(r: dict) -> rx.Component:
    return rx.box(
        rx.hstack(
            rx.text(r["index"], font_size="11px", color="var(--gray-a8)", width="20px", font_family=_MONO),
            rx.cond(
                r["url"] != "",
                rx.link(r["title"], href=r["url"], font_size="12px", color=PRIMARY, flex="1", is_external=True),
                rx.text(r["title"], font_size="12px", color="var(--gray-12)", flex="1"),
            ),
            rx.text(r["rank"], font_size="11px", color="var(--gray-a9)", font_family=_MONO, width="80px"),
            rx.text(r["delta"], font_size="11px", color="var(--gray-a8)", font_family=_MONO, width="70px"),
            rx.text(
                rx.cond(r["snippet_len"] != "0", f"{r['snippet_len']} chars", "no content"),
                font_size="10px",
                color="var(--gray-a7)",
                font_family=_MONO,
                width="80px",
            ),
            spacing="2",
            align="center",
            width="100%",
            padding_y="2px",
        ),
        rx.cond(
            r["snippet"] != "",
            rx.box(
                rx.text(
                    r["snippet"],
                    font_size="10.5px",
                    color="var(--gray-a10)",
                    white_space="pre-wrap",
                    word_break="break-word",
                    line_height="1.5",
                    font_family=_MONO,
                ),
                padding="6px 10px",
                margin_left="20px",
                margin_top="2px",
                margin_bottom="6px",
                background="var(--gray-a2)",
                border_left="2px solid var(--gray-a5)",
                border_radius="4px",
                max_height="180px",
                overflow_y="auto",
            ),
        ),
        width="100%",
    )


def _gen_trace_citation_row(c: dict) -> rx.Component:
    return rx.box(
        rx.hstack(
            rx.badge(c["index"], color_scheme="green", variant="soft", size="1"),
            rx.cond(
                c["url"] != "",
                rx.link(c["title"], href=c["url"], font_size="12px", color=PRIMARY, is_external=True),
                rx.text(c["title"], font_size="12px", color="var(--gray-12)", font_weight="500"),
            ),
            spacing="2",
            align="center",
        ),
        rx.cond(
            c["snippet"] != "",
            rx.box(
                rx.text(
                    c["snippet"],
                    font_size="11px",
                    color="var(--gray-a10)",
                    font_style="italic",
                    white_space="pre-wrap",
                    word_break="break-word",
                    line_height="1.5",
                ),
                padding_left="8px",
                border_left="2px solid var(--green-a5)",
                margin_top="3px",
                margin_left="8px",
                max_height="240px",
                overflow_y="auto",
            ),
        ),
        padding_y="4px",
        width="100%",
    )


def _gen_trace_safety_chip(c: dict) -> rx.Component:
    return rx.hstack(
        rx.text(c["icon"], font_size="13px"),
        rx.text(c["label"], font_size="11px", color="var(--gray-a10)"),
        spacing="1",
        align="center",
        padding_x="8px",
        padding_y="3px",
        border_radius="6px",
        background=rx.match(
            c["tone"],
            ("good", "var(--green-a3)"),
            ("bad", "var(--red-a3)"),
            "var(--gray-a3)",
        ),
    )


def _gen_trace_endpoint_row(ep: rx.Var) -> rx.Component:
    return rx.text(
        ep,
        font_size="11px",
        color="var(--gray-a9)",
        font_family=_MONO,
        word_break="break-all",
    )


def _gen_trace_prompt_block(text) -> rx.Component:
    """Render a long prompt body in a scrollable monospace box."""
    return rx.box(
        rx.text(
            text,
            font_size="10.5px",
            color="var(--gray-11)",
            font_family=_MONO,
            white_space="pre-wrap",
            word_break="break-word",
            line_height="1.55",
        ),
        padding="10px 12px",
        background="var(--gray-a2)",
        border=f"1px solid {SURFACE_BORDER}",
        border_radius="6px",
        max_height="380px",
        overflow_y="auto",
    )


def _mcs_citation_panel_row(item: dict) -> rx.Component:
    """One row of the Citation Verification panel: citation id + title +
    answer/completion state + moderation/provenance flags. Wraps the URL
    snippet so the user can audit grounding inline."""
    return rx.box(
        rx.vstack(
            rx.hstack(
                rx.badge(
                    item["citation_id"],
                    color_scheme="green",
                    variant="solid",
                    size="1",
                ),
                rx.cond(
                    item["url"] != "",
                    rx.link(
                        item["title"],
                        href=item["url"],
                        is_external=True,
                        font_size="12px",
                        font_weight="700",
                        color="var(--green-11)",
                    ),
                    rx.text(item["title"], font_size="12px", font_weight="700", color="var(--gray-12)"),
                ),
                rx.cond(
                    item["trace_topic"] != "—",
                    rx.badge(item["trace_topic"], color_scheme="teal", variant="soft", size="1"),
                    rx.box(),
                ),
                rx.spacer(),
                _status_badge(item["answer_state"], item["answer_state_tone"]),
                rx.cond(
                    item["completion_state"] != "—",
                    rx.badge(
                        item["completion_state"],
                        color_scheme="gray",
                        variant="soft",
                        size="1",
                    ),
                    rx.box(),
                ),
                spacing="2",
                align="center",
                width="100%",
                flex_wrap="wrap",
            ),
            rx.cond(
                item["snippet"] != "",
                rx.text(
                    item["snippet"],
                    font_size="11px",
                    color="var(--gray-a9)",
                    line_height="1.5",
                    style={"wordBreak": "break-word"},
                ),
            ),
            rx.hstack(
                rx.text(
                    "Moderation:",
                    font_size="10px",
                    color="var(--gray-a8)",
                    font_weight="700",
                ),
                _status_badge(item["moderation"], item["moderation_tone"]),
                rx.text(
                    "Provenance:",
                    font_size="10px",
                    color="var(--gray-a8)",
                    font_weight="700",
                ),
                _status_badge(item["provenance"], item["provenance_tone"]),
                spacing="2",
                align="center",
                flex_wrap="wrap",
            ),
            spacing="2",
            align="start",
            width="100%",
        ),
        background="var(--gray-a2)",
        border=f"1px solid {SURFACE_BORDER}",
        border_radius="10px",
        padding="10px 12px",
        width="100%",
    )


def _mcs_generative_trace_card(trace: dict) -> rx.Component:
    """Card surfacing one topic-level SearchAndSummarizeContent diagnostic record."""
    return card(
        rx.vstack(
            # Header row
            rx.hstack(
                rx.badge(
                    trace["attempt_label"],
                    color_scheme=rx.cond(trace["is_retry"] != "", "amber", "green"),
                    variant="soft",
                    size="1",
                ),
                rx.icon("brain-circuit", size=14, color=PRIMARY),
                rx.text(trace["topic"], font_size="13px", font_weight="600", color="var(--gray-12)", flex="1"),
                _status_badge(trace["status_label"], trace["status_tone"]),
                width="100%",
                align="center",
                spacing="2",
            ),
            # Retry reason caption — shown only on attempts after the first
            rx.cond(
                trace["retry_reason"] != "",
                rx.hstack(
                    rx.icon("rotate-ccw", size=12, color="var(--amber-9)"),
                    rx.text(
                        "Retried because previous attempt was:",
                        font_size="11px",
                        color="var(--amber-11)",
                        font_style="italic",
                    ),
                    rx.code(trace["retry_reason"], font_size="11px"),
                    spacing="2",
                    align="center",
                    width="100%",
                ),
            ),
            # Outcome verdict — answers "what happened?" before the user has to read further
            rx.box(
                rx.hstack(
                    rx.text(trace["outcome_icon"], font_size="14px"),
                    rx.text(
                        trace["outcome_label_text"],
                        font_size="12px",
                        font_weight="700",
                        color="var(--gray-12)",
                    ),
                    spacing="2",
                    align="center",
                ),
                rx.text(
                    trace["outcome_explanation"],
                    font_size="12px",
                    color="var(--gray-11)",
                    line_height="1.5",
                    margin_top="3px",
                ),
                # Platform diagnostic strings — show what the SearchAndSummarizeContent
                # node literally reported, so users can distinguish "ran with 0 hits"
                # from "errored" or "skipped silently".
                rx.hstack(
                    rx.text("answer state:", font_size="10px", color="var(--gray-a8)"),
                    rx.code(trace["answer_state"], font_size="10px"),
                    rx.text("completion:", font_size="10px", color="var(--gray-a8)"),
                    rx.code(trace["completion_state"], font_size="10px"),
                    rx.text("fallback:", font_size="10px", color="var(--gray-a8)"),
                    rx.code(trace["fallback_flag"], font_size="10px"),
                    rx.text("errors:", font_size="10px", color="var(--gray-a8)"),
                    rx.code(
                        rx.cond(trace["search_errors"] != "", "see below", "0"),
                        font_size="10px",
                    ),
                    rx.text("logs:", font_size="10px", color="var(--gray-a8)"),
                    rx.code(trace["search_log_count"], font_size="10px"),
                    rx.text("shadow:", font_size="10px", color="var(--gray-a8)"),
                    rx.code(trace["shadow_result_count"], font_size="10px"),
                    spacing="2",
                    wrap="wrap",
                    margin_top="6px",
                ),
                width="100%",
                padding="10px 12px",
                background="var(--gray-a2)",
                border_left="3px solid var(--gray-a6)",
                border_radius="6px",
            ),
            # Shadow errors — only shown when the parallel shadow lane reported any
            rx.cond(
                trace["shadow_errors"] != "",
                rx.box(
                    rx.hstack(
                        rx.icon("triangle-alert", size=12, color="var(--red-9)"),
                        rx.text(
                            f"Shadow search errors: {trace['shadow_errors']}",
                            font_size="12px",
                            color="var(--red-11)",
                        ),
                        spacing="2",
                        align="center",
                    ),
                    background="var(--red-a2)",
                    border="1px solid var(--red-a4)",
                    border_radius="6px",
                    padding="4px 8px",
                ),
            ),
            # Query transformation chain
            rx.box(
                rx.text("Query transformation", font_size="11px", color="var(--gray-a8)", font_weight="700"),
                rx.hstack(
                    rx.text("🗣", font_size="12px"),
                    rx.text(trace["user_msg"], font_size="12px", color="var(--gray-12)"),
                    spacing="2",
                    align="center",
                ),
                rx.cond(
                    (trace["screened"] != "") & (trace["screened"] != trace["user_msg"]),
                    rx.hstack(
                        rx.text("🛡", font_size="12px"),
                        rx.text(trace["screened"], font_size="12px", color="var(--gray-11)"),
                        spacing="2",
                        align="center",
                    ),
                ),
                rx.cond(
                    (trace["rewritten"] != "")
                    & (trace["rewritten"] != trace["user_msg"])
                    & (trace["rewritten"] != trace["screened"]),
                    rx.hstack(
                        rx.text("✏️", font_size="12px"),
                        rx.text(trace["rewritten"], font_size="12px", color="var(--gray-11)"),
                        spacing="2",
                        align="center",
                    ),
                ),
                rx.cond(
                    trace["keywords"] != "",
                    rx.hstack(
                        rx.text("🔑", font_size="12px"),
                        rx.code(trace["keywords"], font_size="11px"),
                        spacing="2",
                        align="center",
                    ),
                ),
                width="100%",
                padding="8px",
                background="var(--gray-a2)",
                border_radius="6px",
            ),
            # Cost / models / backend
            rx.hstack(
                rx.vstack(
                    rx.text("Rewrite", font_size="10px", color="var(--gray-a8)", font_weight="700"),
                    rx.text(trace["rewrite_tokens"], font_size="12px", color="var(--gray-12)", font_family=_MONO),
                    rx.cond(
                        trace["rewrite_total_tokens"] != "",
                        rx.text(
                            f"total {trace['rewrite_total_tokens']}",
                            font_size="10px",
                            color="var(--gray-a8)",
                            font_family=_MONO,
                        ),
                    ),
                    rx.cond(
                        trace["rewrite_cached_tokens"] != "",
                        rx.text(
                            f"cached {trace['rewrite_cached_tokens']}",
                            font_size="10px",
                            color="var(--gray-a8)",
                            font_family=_MONO,
                        ),
                    ),
                    rx.code(trace["rewrite_model"], font_size="10px"),
                    spacing="0",
                    align="start",
                ),
                rx.vstack(
                    rx.text("Summarize", font_size="10px", color="var(--gray-a8)", font_weight="700"),
                    rx.text(trace["summarize_tokens"], font_size="12px", color="var(--gray-12)", font_family=_MONO),
                    rx.cond(
                        trace["summarize_total_tokens"] != "",
                        rx.text(
                            f"total {trace['summarize_total_tokens']}",
                            font_size="10px",
                            color="var(--gray-a8)",
                            font_family=_MONO,
                        ),
                    ),
                    rx.cond(
                        trace["summarize_cached_tokens"] != "",
                        rx.text(
                            f"cached {trace['summarize_cached_tokens']}",
                            font_size="10px",
                            color="var(--gray-a8)",
                            font_family=_MONO,
                        ),
                    ),
                    rx.code(trace["summarize_model"], font_size="10px"),
                    spacing="0",
                    align="start",
                ),
                rx.vstack(
                    rx.text("Backend", font_size="10px", color="var(--gray-a8)", font_weight="700"),
                    rx.text(trace["search_type"], font_size="12px", color="var(--gray-12)"),
                    rx.text(
                        f"{trace['result_count']} hits · {trace['citation_count']} citations",
                        font_size="11px",
                        color="var(--gray-a9)",
                    ),
                    rx.cond(
                        trace["shadow_label"] != "",
                        rx.text(trace["shadow_label"], font_size="10px", color="var(--gray-a9)"),
                    ),
                    spacing="0",
                    align="start",
                ),
                spacing="6",
                width="100%",
                wrap="wrap",
            ),
            # Anomaly callouts: zero-rank ranker, shadow lane mismatch, hypothetical-query insight
            rx.cond(
                trace["all_zero_rank"] != "",
                rx.box(
                    rx.hstack(
                        rx.icon("triangle-alert", size=12, color="var(--amber-9)"),
                        rx.text(
                            "All search ranks are 0 — search ranker likely disabled or misconfigured against the backend.",
                            font_size="11px",
                            color="var(--amber-11)",
                            font_weight="600",
                        ),
                        spacing="2",
                        align="center",
                    ),
                    background="var(--amber-a3)",
                    border="1px solid var(--amber-a5)",
                    border_radius="6px",
                    padding="6px 10px",
                    width="100%",
                ),
            ),
            rx.cond(
                trace["shadow_anomaly"] != "",
                rx.box(
                    rx.hstack(
                        rx.icon("triangle-alert", size=12, color="var(--amber-9)"),
                        rx.text(
                            "Parallel shadow search lane retrieved more results than the live lane — possible backend mismatch.",
                            font_size="11px",
                            color="var(--amber-11)",
                            font_weight="600",
                        ),
                        spacing="2",
                        align="center",
                    ),
                    background="var(--amber-a3)",
                    border="1px solid var(--amber-a5)",
                    border_radius="6px",
                    padding="6px 10px",
                    width="100%",
                ),
            ),
            rx.cond(
                trace["hypothetical_snippet"] != "",
                rx.box(
                    rx.text(
                        "LLM's hypothetical answer (what the rewriter expected to find)",
                        font_size="11px",
                        color="var(--gray-a8)",
                        font_weight="700",
                        margin_bottom="4px",
                    ),
                    rx.text(
                        trace["hypothetical_snippet"],
                        font_size="11px",
                        color="var(--gray-a10)",
                        font_style="italic",
                        white_space="pre-wrap",
                        word_break="break-word",
                    ),
                    padding="6px 10px",
                    background="var(--violet-a2)",
                    border_left="2px solid var(--violet-a5)",
                    border_radius="4px",
                    width="100%",
                ),
            ),
            # Safety chips
            rx.hstack(
                rx.foreach(trace["safety_chips"].to(list[dict]), _gen_trace_safety_chip),
                spacing="2",
                wrap="wrap",
                width="100%",
            ),
            # Endpoints
            rx.cond(
                trace["endpoint_count"] != "0",
                rx.box(
                    rx.text(
                        "Knowledge endpoints queried",
                        font_size="11px",
                        color="var(--gray-a8)",
                        font_weight="700",
                        margin_bottom="4px",
                    ),
                    rx.foreach(trace["endpoints"].to(list[str]), _gen_trace_endpoint_row),
                    width="100%",
                ),
            ),
            # Results table
            rx.cond(
                trace["result_count"] != "0",
                rx.box(
                    rx.text(
                        "Search results",
                        font_size="11px",
                        color="var(--gray-a8)",
                        font_weight="700",
                        margin_bottom="4px",
                    ),
                    rx.foreach(trace["results"].to(list[dict]), _gen_trace_result_row),
                    width="100%",
                    padding="6px 0",
                ),
            ),
            # Citations
            rx.cond(
                trace["citation_count"] != "0",
                rx.box(
                    rx.text(
                        "Citations cited in answer",
                        font_size="11px",
                        color="var(--gray-a8)",
                        font_weight="700",
                        margin_bottom="4px",
                    ),
                    rx.foreach(trace["citations"].to(list[dict]), _gen_trace_citation_row),
                    width="100%",
                ),
            ),
            # Generated answer text (the actual LLM summary)
            rx.cond(
                trace["summary_text"] != "",
                rx.accordion.root(
                    rx.accordion.item(
                        header=rx.hstack(
                            rx.icon("sparkles", size=12, color=PRIMARY),
                            rx.text(
                                "Generated answer",
                                font_size="11px",
                                color="var(--gray-a8)",
                                font_weight="700",
                            ),
                            spacing="2",
                            align="center",
                        ),
                        content=rx.box(
                            rx.markdown(trace["summary_text"]),
                            font_size="12px",
                            color="var(--gray-12)",
                            line_height="1.55",
                            padding="10px 12px",
                            background="var(--green-a2)",
                            border="1px solid var(--green-a4)",
                            border_radius="6px",
                            max_height="420px",
                            overflow_y="auto",
                        ),
                        value="answer",
                    ),
                    type="single",
                    collapsible=True,
                    width="100%",
                    variant="ghost",
                ),
            ),
            # Search errors
            rx.cond(
                trace["search_errors"] != "",
                rx.box(
                    rx.hstack(
                        rx.icon("triangle-alert", size=12, color="var(--red-9)"),
                        rx.text(trace["search_errors"], font_size="12px", color="var(--red-11)"),
                        spacing="2",
                        align="center",
                    ),
                    background="var(--red-a2)",
                    border="1px solid var(--red-a4)",
                    border_radius="6px",
                    padding="4px 8px",
                ),
            ),
            # Search backend logs — collapsible, only shown when present
            rx.cond(
                trace["search_logs_text"] != "",
                rx.accordion.root(
                    rx.accordion.item(
                        header=rx.text(
                            "Search backend logs",
                            font_size="11px",
                            color="var(--gray-a9)",
                            font_weight="700",
                        ),
                        content=_gen_trace_prompt_block(trace["search_logs_text"]),
                        value="search_logs",
                    ),
                    type="single",
                    collapsible=True,
                    width="100%",
                    variant="ghost",
                ),
            ),
            rx.cond(
                trace["shadow_logs_text"] != "",
                rx.accordion.root(
                    rx.accordion.item(
                        header=rx.text(
                            "Shadow search backend logs",
                            font_size="11px",
                            color="var(--gray-a9)",
                            font_weight="700",
                        ),
                        content=_gen_trace_prompt_block(trace["shadow_logs_text"]),
                        value="shadow_logs",
                    ),
                    type="single",
                    collapsible=True,
                    width="100%",
                    variant="ghost",
                ),
            ),
            # Deepest debug signal: full system prompts the LLM saw.
            # Each prompt gets its own accordion so we can conditionally hide it
            # without violating Accordion's children constraint.
            rx.cond(
                trace["rewrite_system_prompt"] != "",
                rx.accordion.root(
                    rx.accordion.item(
                        header=rx.text(
                            "Query-rewrite system prompt", font_size="11px", color="var(--gray-a9)", font_weight="700"
                        ),
                        content=_gen_trace_prompt_block(trace["rewrite_system_prompt"]),
                        value="rewrite_prompt",
                    ),
                    type="single",
                    collapsible=True,
                    width="100%",
                    variant="ghost",
                ),
            ),
            rx.cond(
                trace["summarize_system_prompt"] != "",
                rx.accordion.root(
                    rx.accordion.item(
                        header=rx.text(
                            "Summarization system prompt + retrieved context",
                            font_size="11px",
                            color="var(--gray-a9)",
                            font_weight="700",
                        ),
                        content=_gen_trace_prompt_block(trace["summarize_system_prompt"]),
                        value="summarize_prompt",
                    ),
                    type="single",
                    collapsible=True,
                    width="100%",
                    variant="ghost",
                ),
            ),
            rx.cond(
                trace["rewrite_raw_response"] != "",
                rx.accordion.root(
                    rx.accordion.item(
                        header=rx.text(
                            "Raw rewrite LLM response", font_size="11px", color="var(--gray-a9)", font_weight="700"
                        ),
                        content=_gen_trace_prompt_block(trace["rewrite_raw_response"]),
                        value="rewrite_raw",
                    ),
                    type="single",
                    collapsible=True,
                    width="100%",
                    variant="ghost",
                ),
            ),
            spacing="3",
            width="100%",
        ),
        width="100%",
        padding="14px",
    )


def _mcs_knowledge_panel() -> rx.Component:
    return rx.vstack(
        # KPI grid
        rx.grid(
            rx.foreach(State.mcs_knowledge_kpis, _mcs_kpi_card),
            columns="4",
            gap="10px",
            width="100%",
        ),
        # General knowledge badge
        rx.hstack(
            rx.text("General Knowledge:", font_size="13px", color="var(--gray-a9)", font_weight="600"),
            rx.cond(
                State.mcs_knowledge_general_enabled,
                rx.badge("Enabled", color_scheme="green", variant="soft", size="1"),
                rx.badge("Disabled", color_scheme="gray", variant="soft", size="1"),
            ),
            spacing="2",
            align="center",
        ),
        # Knowledge Sources table
        rx.cond(
            State.mcs_knowledge_sources.length() > 0,  # type: ignore[union-attr]
            card(
                section_heading("Knowledge Sources"),
                _data_table(
                    ["Name", "Type", "Site", "Status", "Trigger"],
                    "2fr 1fr 1fr 1fr 1fr",
                    State.mcs_knowledge_sources,
                    _mcs_ks_source_row,
                ),
                width="100%",
            ),
        ),
        # File Attachments table
        rx.cond(
            State.mcs_knowledge_files.length() > 0,  # type: ignore[union-attr]
            card(
                section_heading("File Attachments"),
                _data_table(
                    ["Name", "Type", "Status"],
                    "3fr 1fr 1fr",
                    State.mcs_knowledge_files,
                    _mcs_ks_file_row,
                ),
                width="100%",
            ),
        ),
        # Coverage table
        rx.cond(
            State.mcs_knowledge_coverage.length() > 0,  # type: ignore[union-attr]
            card(
                section_heading("Coverage"),
                _data_table(
                    ["Name", "Type", "State", "Trigger", "Notes"],
                    "2fr 1fr 1fr 1fr 2fr",
                    State.mcs_knowledge_coverage,
                    _mcs_ks_coverage_row,
                ),
                width="100%",
            ),
        ),
        # Search Results
        rx.cond(
            State.mcs_knowledge_searches.length() > 0,  # type: ignore[union-attr]
            rx.vstack(
                rx.hstack(
                    rx.icon("search", size=16, color=PRIMARY),
                    section_heading("Search Results"),
                    spacing="2",
                    align="center",
                ),
                rx.foreach(State.mcs_knowledge_searches, _mcs_ks_item),
                spacing="3",
                width="100%",
            ),
        ),
        # Custom Search Steps
        rx.cond(
            State.mcs_knowledge_custom_steps.length() > 0,  # type: ignore[union-attr]
            card(
                section_heading("Custom Search Steps"),
                rx.vstack(
                    rx.foreach(State.mcs_knowledge_custom_steps, _mcs_ks_custom_step),
                    spacing="1",
                    width="100%",
                ),
                width="100%",
            ),
        ),
        # Topic-level generative answer traces
        rx.cond(
            State.mcs_generative_traces.length() > 0,  # type: ignore[union-attr]
            rx.vstack(
                rx.hstack(
                    rx.icon("brain-circuit", size=16, color=PRIMARY),
                    section_heading("Topic-Level Generative Answers"),
                    rx.badge(
                        State.mcs_generative_traces.length(),  # type: ignore[union-attr]
                        color_scheme="green",
                        variant="soft",
                        size="1",
                    ),
                    spacing="2",
                    align="center",
                ),
                rx.text(
                    "SearchAndSummarizeContent invoked directly inside a topic — "
                    "captures the full query rewriting chain, token usage, ranked results, citations, and safety pipeline.",
                    font_size="11px",
                    color="var(--gray-a9)",
                    font_style="italic",
                ),
                rx.foreach(State.mcs_generative_traces, _mcs_generative_trace_card),
                spacing="3",
                width="100%",
            ),
        ),
        # Citation Verification panel — flat audit table of every citation
        # across all generative-answer traces with answer/completion state
        # and safety flags. Hidden when no citations exist.
        rx.cond(
            State.mcs_knowledge_citation_panel.length() > 0,  # type: ignore[union-attr]
            card(
                rx.hstack(
                    rx.icon("badge-check", size=16, color=PRIMARY),
                    section_heading("Citation Verification"),
                    rx.spacer(),
                    rx.badge(
                        State.mcs_knowledge_citation_panel.length().to(str),  # type: ignore[union-attr]
                        color_scheme="green",
                        variant="soft",
                        size="1",
                    ),
                    align="center",
                    width="100%",
                ),
                rx.text(
                    "Every citation referenced in the conversation, with the trace's "
                    "gptAnswerState / completionState and content moderation + provenance "
                    "flags. Click a row to open the source.",
                    font_size="11px",
                    color="var(--gray-a8)",
                    font_style="italic",
                ),
                rx.vstack(
                    rx.foreach(State.mcs_knowledge_citation_panel, _mcs_citation_panel_row),
                    spacing="2",
                    width="100%",
                    padding_top="8px",
                ),
                width="100%",
            ),
        ),
        # Knowledge Source Effectiveness (moved from Insights)
        rx.cond(
            State.mcs_ins_ke_kpis.length() > 0,  # type: ignore[union-attr]
            card(
                _ins_card_header(
                    "database",
                    "var(--amber-9)",
                    "Knowledge Source Effectiveness",
                    "Per-source hit rate and contribution to grounded responses.",
                ),
                rx.hstack(
                    rx.foreach(State.mcs_ins_ke_kpis, _ins_kpi),
                    spacing="3",
                    width="100%",
                    overflow_x="auto",
                    padding_y="12px",
                ),
                rx.box(
                    rx.grid(
                        rx.text("Source", **_INS_HEADER_CELL),
                        rx.text("Queries", **_INS_HEADER_CELL, text_align="right"),
                        rx.text("Contributed", **_INS_HEADER_CELL, text_align="right"),
                        rx.text("Hit Rate", **_INS_HEADER_CELL),
                        rx.text("Errors", **_INS_HEADER_CELL, text_align="right"),
                        rx.text("Avg Results", **_INS_HEADER_CELL, text_align="right"),
                        columns="2fr 0.7fr 0.9fr 0.7fr 0.6fr 0.7fr",
                        gap="8px",
                        padding_y="8px",
                        border_bottom=f"2px solid {SURFACE_BORDER}",
                        width="100%",
                    ),
                    rx.foreach(State.mcs_ins_ke_rows, _ins_ke_row),
                    width="100%",
                ),
                rx.cond(
                    State.mcs_ins_ke_warnings.length() > 0,  # type: ignore[union-attr]
                    rx.box(
                        rx.text(
                            "Low-performing sources",
                            font_size="12px",
                            font_weight="700",
                            color="var(--amber-9)",
                            padding_top="12px",
                        ),
                        rx.foreach(
                            State.mcs_ins_ke_warnings,
                            lambda w: rx.text(f"• {w}", font_size="12px", color="var(--gray-a9)"),
                        ),
                        width="100%",
                    ),
                ),
                width="100%",
            ),
        ),
        spacing="4",
        width="100%",
    )


# ── Routing panel ────────────────────────────────────────────────────────


def _mcs_lifecycle_card(item: dict) -> rx.Component:
    """Render a single topic lifecycle card."""
    is_failed = item["status"] == "failed"
    is_pending = item["status"] == "pending"
    is_redirected = item["status"] == "redirected"
    return rx.box(
        rx.vstack(
            rx.hstack(
                rx.badge(
                    item["name"],
                    color_scheme=rx.cond(
                        is_failed,
                        "red",
                        rx.cond(is_pending, "amber", rx.cond(is_redirected, "blue", "teal")),
                    ),
                    variant="soft",
                    size="1",
                ),
                rx.badge(
                    item["status"],
                    color_scheme=rx.cond(
                        is_failed,
                        "red",
                        rx.cond(is_pending, "amber", rx.cond(is_redirected, "blue", "green")),
                    ),
                    variant="outline",
                    size="1",
                ),
                rx.cond(
                    item["duration_label"] != "",
                    rx.text(item["duration_label"], font_size="11px", color="var(--gray-a8)", font_family=_MONO),
                    rx.box(),
                ),
                rx.cond(
                    item["start"] != "",
                    rx.text(
                        rx.text.span(item["start"]),
                        rx.text.span(" -> ", color="var(--gray-a6)"),
                        rx.text.span(item["end"]),
                        font_size="11px",
                        color="var(--gray-a8)",
                        font_family=_MONO,
                    ),
                    rx.box(),
                ),
                rx.cond(
                    item["has_recommendations"] == "true",
                    rx.badge("Alternatives considered", color_scheme="amber", variant="soft", size="1"),
                    rx.box(),
                ),
                spacing="2",
                align="center",
                flex_wrap="wrap",
            ),
            rx.cond(
                item["thought"] != "",
                rx.text(
                    item["thought"],
                    font_size="11px",
                    font_style="italic",
                    color="var(--gray-a7)",
                    line_height="1.4",
                ),
                rx.box(),
            ),
            rx.cond(
                item["used_outputs"] != "",
                rx.text(item["used_outputs"], font_size="11px", color="var(--blue-9)"),
                rx.box(),
            ),
            rx.cond(
                item["error"] != "",
                rx.text(item["error"], font_size="11px", color="var(--red-9)"),
                rx.box(),
            ),
            rx.cond(
                item["child_count"].to(int) > 0,  # type: ignore[union-attr]
                rx.text(
                    item["child_summary"],
                    font_size="11px",
                    color="var(--gray-a7)",
                    overflow="hidden",
                    text_overflow="ellipsis",
                    white_space="nowrap",
                ),
                rx.box(),
            ),
            spacing="1",
            width="100%",
        ),
        padding="10px 14px",
        border_bottom="1px solid var(--gray-a3)",
        _hover={"background": "var(--gray-a2)"},
    )


# ── Orchestrator Decision Timeline renderers ────────────────────────────


def _mcs_decision_item(item: dict) -> rx.Component:
    """Render a single orchestrator decision timeline item by kind."""
    return rx.match(
        item["kind"],
        # User message bubble
        (
            "user_message",
            rx.box(
                rx.hstack(
                    rx.icon("message-circle", size=14, color="var(--blue-9)"),
                    rx.text(item.get("text", ""), font_size="13px", color="var(--gray-12)", font_weight="500"),
                    rx.text(item.get("timestamp", ""), font_size="10px", color="var(--gray-a7)", font_family=_MONO),
                    spacing="2",
                    align="center",
                ),
                padding="10px 14px",
                background="var(--blue-a2)",
                border_radius="8px",
                margin_bottom="4px",
            ),
        ),
        # Interpreted query
        (
            "interpreted",
            rx.box(
                rx.hstack(
                    rx.icon("sparkles", size=12, color="var(--violet-9)"),
                    rx.text(
                        rx.text.span("Interpreted as: ", font_weight="600"),
                        rx.text.span(item.get("ask", ""), font_style="italic"),
                        font_size="12px",
                        color="var(--violet-11)",
                    ),
                    spacing="2",
                    align="center",
                ),
                padding="6px 14px 6px 28px",
                margin_bottom="2px",
            ),
        ),
        # Plan
        (
            "plan",
            rx.box(
                rx.hstack(
                    rx.icon("list-ordered", size=14, color="var(--teal-9)"),
                    rx.text("Plan", font_size="12px", font_weight="600", color="var(--gray-11)"),
                    rx.cond(
                        item.get("is_final", "") == "True",
                        rx.badge("Final", color_scheme="green", variant="soft", size="1"),
                        rx.cond(
                            item.get("is_final", "") == "False",
                            rx.badge("Intermediate", color_scheme="amber", variant="soft", size="1"),
                            rx.box(),
                        ),
                    ),
                    rx.text(item.get("timestamp", ""), font_size="10px", color="var(--gray-a7)", font_family=_MONO),
                    spacing="2",
                    align="center",
                ),
                rx.text(
                    item.get("steps", ""),
                    font_size="11px",
                    color="var(--gray-a9)",
                    padding_left="22px",
                    padding_top="2px",
                ),
                padding="8px 14px",
                border_left="3px solid var(--teal-7)",
                margin_left="6px",
                margin_bottom="4px",
            ),
        ),
        # Step
        (
            "step",
            rx.box(
                rx.hstack(
                    rx.cond(
                        item.get("event_subtype", "") == "triggered",
                        rx.icon("play", size=12, color="var(--green-9)"),
                        rx.icon("check", size=12, color="var(--gray-a8)"),
                    ),
                    rx.badge(
                        item.get("topic_name", ""),
                        color_scheme=rx.cond(
                            item.get("status", "") == "failed",
                            "red",
                            rx.cond(item.get("event_subtype", "") == "triggered", "teal", "gray"),
                        ),
                        variant="soft",
                        size="1",
                    ),
                    rx.cond(
                        item.get("step_type", "") != "",
                        rx.badge(item.get("step_type", ""), color_scheme="gray", variant="outline", size="1"),
                        rx.box(),
                    ),
                    rx.cond(
                        item.get("duration", "") != "",
                        rx.text(item.get("duration", ""), font_size="10px", color="var(--gray-a8)", font_family=_MONO),
                        rx.box(),
                    ),
                    rx.cond(
                        item.get("has_recommendations", "") == "true",
                        rx.badge("Alternatives", color_scheme="amber", variant="soft", size="1"),
                        rx.box(),
                    ),
                    rx.cond(
                        item.get("used_outputs", "") != "",
                        rx.badge(item.get("used_outputs", ""), color_scheme="blue", variant="outline", size="1"),
                        rx.box(),
                    ),
                    _trigger_score_badge(item.get("trigger_score", ""), item.get("trigger_score_color", "gray")),
                    spacing="2",
                    align="center",
                    flex_wrap="wrap",
                ),
                rx.cond(
                    item.get("thought", "") != "",
                    rx.text(
                        item.get("thought", ""),
                        font_size="11px",
                        font_style="italic",
                        color="var(--gray-a7)",
                        padding_left="22px",
                        padding_top="2px",
                    ),
                    rx.box(),
                ),
                rx.cond(
                    item.get("trigger_phrase", "") != "",
                    rx.text(
                        item.get("trigger_phrase", ""),
                        font_size="10px",
                        color="var(--gray-a6)",
                        padding_left="22px",
                        padding_top="1px",
                        font_style="italic",
                    ),
                    rx.box(),
                ),
                rx.cond(
                    item.get("error", "") != "",
                    rx.text(
                        item.get("error", ""),
                        font_size="11px",
                        color="var(--red-9)",
                        padding_left="22px",
                        padding_top="2px",
                    ),
                    rx.box(),
                ),
                padding="4px 14px 4px 36px",
                margin_bottom="2px",
            ),
        ),
        # Action (HTTP request / Begin Dialog)
        (
            "action",
            rx.box(
                rx.hstack(
                    rx.icon("globe", size=12, color="var(--purple-9)"),
                    rx.text(item.get("action_type", ""), font_size="11px", font_weight="600", color="var(--purple-11)"),
                    rx.cond(
                        item.get("topic_name", "") != "",
                        rx.badge(item.get("topic_name", ""), color_scheme="purple", variant="soft", size="1"),
                        rx.box(),
                    ),
                    rx.text(
                        item.get("summary", ""),
                        font_size="11px",
                        color="var(--gray-a8)",
                        overflow="hidden",
                        text_overflow="ellipsis",
                        white_space="nowrap",
                        max_width="400px",
                    ),
                    rx.cond(
                        item.get("error", "") != "",
                        rx.text(item.get("error", ""), font_size="11px", color="var(--red-9)"),
                        rx.box(),
                    ),
                    rx.text(item.get("timestamp", ""), font_size="10px", color="var(--gray-a7)", font_family=_MONO),
                    spacing="2",
                    align="center",
                    flex_wrap="wrap",
                ),
                padding="4px 14px 4px 36px",
                margin_bottom="2px",
            ),
        ),
        # Plan finished
        (
            "plan_finished",
            rx.box(
                rx.separator(size="4", color_scheme="gray"),
                rx.cond(
                    item.get("is_cancelled", "") == "true",
                    rx.text("Plan cancelled", font_size="10px", color="var(--red-9)", text_align="center"),
                    rx.box(),
                ),
                padding="4px 14px",
                margin_bottom="8px",
            ),
        ),
        # Fallback
        rx.box(),
    )


# ── Plan Evolution renderers ────────────────────────────────────────────


def _mcs_plan_evolution_card(item: dict) -> rx.Component:
    """Render a single plan evolution entry."""
    return rx.box(
        rx.vstack(
            rx.hstack(
                rx.text(
                    rx.text.span("Plan #"),
                    rx.text.span(item["plan_index"], font_weight="600"),
                    font_size="12px",
                    color="var(--gray-11)",
                ),
                rx.cond(
                    item["is_final"] == "True",
                    rx.badge("Final", color_scheme="green", variant="soft", size="1"),
                    rx.cond(
                        item["is_final"] == "False",
                        rx.badge("Intermediate", color_scheme="amber", variant="soft", size="1"),
                        rx.box(),
                    ),
                ),
                rx.cond(
                    item["change_summary"] != "",
                    rx.text(item["change_summary"], font_size="11px", color="var(--gray-a8)"),
                    rx.box(),
                ),
                rx.text(item["timestamp"], font_size="10px", color="var(--gray-a7)", font_family=_MONO),
                spacing="2",
                align="center",
                flex_wrap="wrap",
            ),
            rx.text(item["steps"], font_size="11px", color="var(--gray-a9)", line_height="1.4"),
            rx.cond(
                item["added_steps"] != "",
                rx.text(
                    rx.text.span("+ ", color="var(--green-9)", font_weight="600"),
                    rx.text.span(item["added_steps"]),
                    font_size="11px",
                    color="var(--green-11)",
                ),
                rx.box(),
            ),
            rx.cond(
                item["removed_steps"] != "",
                rx.text(
                    rx.text.span("- ", color="var(--red-9)", font_weight="600"),
                    rx.text.span(item["removed_steps"]),
                    font_size="11px",
                    color="var(--red-11)",
                ),
                rx.box(),
            ),
            rx.cond(
                item["step_scores"] != "",
                rx.text(
                    rx.text.span("Routing scores: ", font_weight="600", color="var(--gray-a8)"),
                    rx.text.span(item["step_scores"]),
                    font_size="11px",
                    color="var(--teal-11)",
                ),
                rx.box(),
            ),
            spacing="1",
            width="100%",
        ),
        padding="10px 14px",
        border_bottom="1px solid var(--gray-a3)",
    )


def _mcs_routing_panel() -> rx.Component:
    return rx.vstack(
        # Section 1: Orchestrator Decision Timeline
        rx.cond(
            State.mcs_routing_decisions.length() > 0,  # type: ignore[union-attr]
            card(
                rx.hstack(
                    rx.icon("brain", size=16, color="var(--violet-9)"),
                    section_heading("Orchestrator Decision Timeline"),
                    spacing="2",
                    align="center",
                ),
                rx.text(
                    "How the orchestrator interpreted queries, planned steps, and executed topics.",
                    font_size="12px",
                    color="var(--gray-a9)",
                    padding_bottom="8px",
                ),
                rx.box(
                    rx.foreach(State.mcs_routing_decisions, _mcs_decision_item),
                    width="100%",
                    padding="8px 0",
                ),
                width="100%",
            ),
        ),
        # Section 2: Plan Evolution (only when >1 plan)
        rx.cond(
            State.mcs_routing_plan_evolution.length() > 0,  # type: ignore[union-attr]
            card(
                rx.hstack(
                    rx.icon("git-compare", size=16, color="var(--amber-9)"),
                    section_heading("Plan Evolution"),
                    spacing="2",
                    align="center",
                ),
                rx.text(
                    "How the orchestrator's plan changed across replanning attempts.",
                    font_size="12px",
                    color="var(--gray-a9)",
                    padding_bottom="8px",
                ),
                rx.box(
                    rx.foreach(State.mcs_routing_plan_evolution, _mcs_plan_evolution_card),
                    width="100%",
                    border=f"1px solid {SURFACE_BORDER}",
                    border_radius="8px",
                    background="var(--gray-a2)",
                    overflow="hidden",
                ),
                width="100%",
            ),
        ),
        # Section 3: Topic Lifecycles (enhanced)
        rx.cond(
            State.mcs_routing_lifecycles.length() > 0,  # type: ignore[union-attr]
            card(
                rx.hstack(
                    rx.icon("activity", size=16, color="var(--teal-9)"),
                    section_heading("Topic Lifecycles"),
                    spacing="2",
                    align="center",
                ),
                rx.text(
                    "How topics were triggered, executed, and completed during the conversation.",
                    font_size="12px",
                    color="var(--gray-a9)",
                    padding_bottom="8px",
                ),
                rx.box(
                    rx.foreach(State.mcs_routing_lifecycles, _mcs_lifecycle_card),
                    width="100%",
                    border=f"1px solid {SURFACE_BORDER}",
                    border_radius="8px",
                    background="var(--gray-a2)",
                    overflow="hidden",
                ),
                width="100%",
            ),
        ),
        # Section 4: Trigger Phrase Analysis (enhanced)
        rx.cond(
            State.mcs_topics_trigger_matches.length() > 0,  # type: ignore[union-attr]
            card(
                rx.hstack(
                    rx.icon("crosshair", size=16, color="var(--teal-9)"),
                    section_heading("Trigger Phrase Analysis"),
                    spacing="2",
                    align="center",
                ),
                rx.text(
                    "How user messages matched against topic trigger phrases.",
                    font_size="12px",
                    color="var(--gray-a9)",
                    padding_bottom="8px",
                ),
                rx.box(
                    rx.foreach(State.mcs_topics_trigger_matches, _mcs_trigger_match_card),
                    width="100%",
                    border=f"1px solid {SURFACE_BORDER}",
                    border_radius="8px",
                    background="var(--gray-a2)",
                    overflow="hidden",
                ),
                width="100%",
            ),
        ),
        # Section 5: Plan Evolution Diffs (moved from Insights)
        rx.cond(
            State.mcs_ins_plan_diffs.length() > 0,  # type: ignore[union-attr]
            card(
                _ins_card_header(
                    "git-compare",
                    "var(--violet-9)",
                    "Plan Evolution Diffs",
                    "How the orchestrator changed its plan within a single turn.",
                ),
                rx.cond(
                    State.mcs_ins_plan_kpis.length() > 0,  # type: ignore[union-attr]
                    rx.hstack(
                        rx.foreach(State.mcs_ins_plan_kpis, _ins_kpi),
                        spacing="3",
                        width="100%",
                        overflow_x="auto",
                        padding_y="12px",
                    ),
                ),
                rx.foreach(State.mcs_ins_plan_diffs, _ins_plan_diff_item),
                width="100%",
            ),
        ),
        # Section 6: Topic Coverage (moved from Topics)
        rx.cond(
            State.mcs_topics_coverage.length() > 0,  # type: ignore[union-attr]
            card(
                rx.hstack(
                    rx.icon("scan-search", size=16, color="var(--teal-9)"),
                    section_heading("Topic Coverage"),
                    spacing="2",
                    align="center",
                ),
                rx.text(
                    State.mcs_topics_coverage_summary,
                    font_size="13px",
                    color="var(--gray-12)",
                    font_weight="600",
                    padding_bottom="8px",
                ),
                sub_heading("Not triggered in this session"),
                _data_table(
                    ["Topic", "State", "External Calls"],
                    "3fr 1fr 1fr",
                    State.mcs_topics_coverage,
                    _mcs_topics_coverage_row,
                ),
                width="100%",
            ),
        ),
        spacing="4",
        width="100%",
    )


# ── Topics panel ─────────────────────────────────────────────────────────


def _mcs_topics_summary_row(item: dict) -> rx.Component:
    return _grid_row(
        [
            rx.text(item["category"], font_size="13px", color="var(--gray-12)"),
            rx.text(item["count"], font_size="13px", color="var(--gray-12)", font_weight="600", text_align="right"),
            rx.text(item["active"], font_size="13px", color="var(--green-11)", text_align="right"),
            rx.text(item["inactive"], font_size="13px", color="var(--gray-a9)", text_align="right"),
        ],
        template="3fr 1fr 1fr 1fr",
    )


def _settings_hover_card(row: dict) -> rx.Component:
    """Hover card with the KB-sourced explanation for one setting.

    Trigger is a small (i) icon next to the setting. Content shows the summary
    plus a Microsoft Learn link. For undocumented entries, the trigger is
    greyed out and the card states the gap explicitly — no fake explanation.
    """
    return rx.hover_card.root(
        rx.hover_card.trigger(
            rx.icon(
                "info",
                size=12,
                color=rx.cond(row["documented"] != "", "var(--accent-9)", "var(--gray-a7)"),
                cursor="help",
            ),
        ),
        rx.hover_card.content(
            rx.cond(
                row["documented"] != "",
                rx.vstack(
                    rx.text(row["summary"], font_size="12px", line_height="1.55"),
                    rx.cond(
                        row["doc_url"] != "",
                        rx.link(
                            "Open Microsoft Learn ↗",
                            href=row["doc_url"],
                            is_external=True,
                            font_size="11px",
                            color="var(--accent-11)",
                            text_decoration="underline",
                        ),
                    ),
                    spacing="2",
                    align="start",
                ),
                rx.text(
                    "Not yet documented in the analyser's curated KB. "
                    "Add an entry to data/topic_explainer.yaml to surface a hover here.",
                    font_size="12px",
                    color="var(--gray-a10)",
                    font_style="italic",
                ),
            ),
            max_width="420px",
            padding="10px 12px",
        ),
    )


def _settings_kind_row(row: dict) -> rx.Component:
    """Row that names an action / trigger / component."""
    return rx.hstack(
        rx.box(min_width=row["indent_px"]),
        rx.icon(
            rx.cond(row["documented"] != "", "circle-check", "circle-help"),
            size=12,
            color=rx.cond(row["documented"] != "", "var(--accent-9)", "var(--gray-a7)"),
        ),
        rx.text(
            row["label"],
            font_size="12px",
            font_weight="700",
            color="var(--gray-12)",
        ),
        rx.cond(
            row["node_id"] != "",
            rx.code(row["node_id"], font_size="10px", color="var(--gray-a9)"),
        ),
        _settings_hover_card(row),
        spacing="2",
        align="center",
        width="100%",
        padding="3px 0",
    )


def _settings_prop_row(row: dict) -> rx.Component:
    """Row that displays one property: name + value, with hover-card explainer."""
    return rx.hstack(
        rx.box(min_width=row["indent_px"]),
        rx.text(
            row["label"],
            font_size="11px",
            color="var(--gray-a9)",
            font_family=_MONO,
        ),
        rx.text(":", font_size="11px", color="var(--gray-a7)"),
        rx.code(
            row["display_value"],
            font_size="11px",
            color="var(--gray-12)",
        ),
        _settings_hover_card(row),
        spacing="2",
        align="center",
        width="100%",
        padding="2px 0",
    )


def _settings_row_dispatch(row: dict) -> rx.Component:
    """Render either a kind row or a prop row based on `row_type`."""
    return rx.cond(
        row["row_type"] == "kind",
        _settings_kind_row(row),
        _settings_prop_row(row),
    )


def _settings_explained_accordion(item: dict) -> rx.Component:
    """Per-row accordion that opens to the structured settings panel.

    Each setting in the panel has an (i) icon. Hovering reveals a card with
    the KB-sourced explanation and a Microsoft Learn link. Undocumented
    settings show a circle-help icon and an explicit "not in KB" hover.

    Rendered only when `settings_rows` is non-empty, so non-DialogComponent
    rows collapse cleanly.
    """
    return rx.cond(
        item["has_settings"] != "",
        rx.accordion.root(
            rx.accordion.item(
                header=rx.hstack(
                    rx.icon("settings", size=12, color=PRIMARY),
                    rx.text(
                        "Settings",
                        font_size="11px",
                        color="var(--gray-a9)",
                        font_weight="700",
                    ),
                    rx.text(
                        "(hover ⓘ to explain)",
                        font_size="10px",
                        color="var(--gray-a8)",
                        font_style="italic",
                    ),
                    spacing="2",
                    align="center",
                ),
                content=rx.box(
                    rx.vstack(
                        rx.foreach(
                            item["settings_rows"].to(list[dict]),  # type: ignore[union-attr]
                            _settings_row_dispatch,
                        ),
                        spacing="0",
                        align="start",
                        width="100%",
                    ),
                    padding="10px 14px",
                    background="var(--gray-a2)",
                    border_radius="6px",
                    max_height="520px",
                    overflow_y="auto",
                ),
                value="settings_explained",
            ),
            type="single",
            collapsible=True,
            width="100%",
            variant="ghost",
        ),
    )


def _highlight_row_style(item: dict) -> dict:
    """Return highlight style props when this row is the current deep-link
    target. The Conversation Flow → tab linker sets
    `mcs_highlight_target_id` to the row's identity (matched against the
    pre-computed `link_id` field on the row dict), and this helper paints a
    green border + soft glow so the user can see which row was targeted."""
    is_target = State.mcs_highlight_target_id == item["link_id"]
    return {
        "border_left": rx.cond(is_target, "3px solid var(--green-9)", "3px solid transparent"),
        "background": rx.cond(is_target, "var(--green-a2)", "transparent"),
        "transition": "border-color 0.2s ease, background 0.2s ease",
    }


def _mcs_topics_user_row(item: dict) -> rx.Component:
    return rx.vstack(
        _grid_row(
            [
                rx.text(item["name"], font_size="13px", color="var(--gray-12)", font_weight="500"),
                rx.text(item["schema"], font_size="12px", color="var(--gray-a9)", font_family=_MONO),
                rx.badge(
                    item["state"],
                    color_scheme=rx.cond(item["state"] == "Active", "green", "gray"),
                    variant="soft",
                    size="1",
                ),
                rx.text(
                    item["triggers"],
                    font_size="12px",
                    color="var(--gray-a9)",
                    overflow="hidden",
                    text_overflow="ellipsis",
                    white_space="nowrap",
                ),
                rx.text(
                    item["description"],
                    font_size="12px",
                    color="var(--gray-a9)",
                    overflow="hidden",
                    text_overflow="ellipsis",
                    white_space="nowrap",
                ),
            ],
            template="2fr 2fr 1fr 2fr 2fr",
        ),
        _settings_explained_accordion(item),
        spacing="0",
        width="100%",
        id=item["row_id"],
        **_highlight_row_style(item),
    )


def _mcs_topics_orch_row(item: dict) -> rx.Component:
    return rx.vstack(
        _grid_row(
            [
                rx.text(item["name"], font_size="13px", color="var(--gray-12)", font_weight="500"),
                rx.badge(
                    item["state"],
                    color_scheme=rx.cond(item["state"] == "Active", "green", "gray"),
                    variant="soft",
                    size="1",
                ),
                rx.text(item["tool_type"], font_size="13px", color="var(--gray-a9)"),
                rx.text(item["connector"], font_size="13px", color="var(--gray-a9)"),
                rx.text(item["mode"], font_size="13px", color="var(--gray-11)"),
            ],
            template="2fr 1fr 1fr 1fr 1fr",
        ),
        _settings_explained_accordion(item),
        spacing="0",
        width="100%",
        id=item["row_id"],
        **_highlight_row_style(item),
    )


def _mcs_topics_system_row(item: dict) -> rx.Component:
    return rx.vstack(
        _grid_row(
            [
                rx.text(item["name"], font_size="13px", color="var(--gray-12)", font_weight="500"),
                rx.text(item["schema"], font_size="12px", color="var(--gray-a9)", font_family=_MONO),
                rx.badge(
                    item["state"],
                    color_scheme=rx.cond(item["state"] == "Active", "green", "gray"),
                    variant="soft",
                    size="1",
                ),
                rx.text(item["trigger"], font_size="13px", color="var(--gray-a9)"),
            ],
            template="2fr 2fr 1fr 1fr",
        ),
        _settings_explained_accordion(item),
        spacing="0",
        width="100%",
        id=item["row_id"],
        **_highlight_row_style(item),
    )


def _mcs_topics_ext_row(item: dict) -> rx.Component:
    return _grid_row(
        [
            rx.text(item["name"], font_size="13px", color="var(--gray-12)"),
            rx.text(item["connector"], font_size="13px", color="var(--gray-11)", text_align="right"),
            rx.text(item["flow"], font_size="13px", color="var(--gray-11)", text_align="right"),
            rx.text(item["ai_builder"], font_size="13px", color="var(--gray-11)", text_align="right"),
            rx.text(item["http"], font_size="13px", color="var(--gray-11)", text_align="right"),
            rx.text(item["total"], font_size="13px", color="var(--gray-12)", font_weight="600", text_align="right"),
        ],
        template="3fr 1fr 1fr 1fr 1fr 1fr",
    )


def _mcs_topics_coverage_row(item: dict) -> rx.Component:
    return _grid_row(
        [
            rx.text(item["name"], font_size="13px", color="var(--gray-12)"),
            rx.badge(
                item["state"],
                color_scheme=rx.cond(item["state"] == "Active", "green", "gray"),
                variant="soft",
                size="1",
            ),
            rx.text(item["has_external_calls"], font_size="13px", color="var(--gray-a9)"),
        ],
        template="3fr 1fr 1fr",
    )


def _mcs_trigger_match_card(item: dict) -> rx.Component:
    """Render a single trigger phrase analysis card for one user message."""
    return rx.box(
        rx.vstack(
            # User message
            rx.hstack(
                rx.icon("message-circle", size=14, color="var(--blue-9)"),
                rx.text(item["user_message"], font_size="13px", color="var(--gray-12)", font_weight="500"),
                spacing="2",
                align="center",
            ),
            # Orchestrator interpretation (when different from user message)
            rx.cond(
                item.get("orchestrator_ask", "") != "",
                rx.hstack(
                    rx.icon("sparkles", size=12, color="var(--violet-9)"),
                    rx.text(
                        rx.text.span("Orchestrator interpreted as: ", font_weight="600"),
                        rx.text.span(item.get("orchestrator_ask", ""), font_style="italic"),
                        font_size="12px",
                        color="var(--violet-11)",
                    ),
                    spacing="2",
                    align="center",
                    padding_left="6px",
                ),
                rx.box(),
            ),
            # Selected topic badge
            rx.hstack(
                rx.text("Triggered:", font_size="12px", color="var(--gray-a9)"),
                rx.badge(
                    item["selected_topic"],
                    color_scheme=rx.cond(item["selected_topic"] == "—", "gray", "green"),
                    variant="soft",
                    size="1",
                ),
                spacing="2",
                align="center",
            ),
            # Matches summary with visual hierarchy
            rx.box(
                rx.text(
                    "Trigger phrase similarity (offline analysis, not evaluated by orchestrator):",
                    font_size="11px",
                    color="var(--gray-a7)",
                    font_style="italic",
                    margin_bottom="4px",
                ),
                rx.text(
                    item["matches_summary"],
                    font_size="12px",
                    color="var(--gray-a9)",
                    white_space="pre-wrap",
                    font_family=_MONO,
                    line_height="1.6",
                ),
                border_left="2px solid var(--gray-a4)",
                padding_left="12px",
                margin_top="4px",
            ),
            # Cap indicator
            rx.cond(
                item["total_matches"].to(int) > 8,  # type: ignore[union-attr]
                rx.text(
                    rx.text.span("showing top 8 of "),
                    rx.text.span(item["total_matches"], font_weight="600"),
                    rx.text.span(" matches"),
                    font_size="11px",
                    color="var(--gray-a7)",
                    font_style="italic",
                    padding_top="4px",
                ),
            ),
            spacing="2",
            width="100%",
        ),
        padding="14px 16px",
        border_bottom="1px solid var(--gray-a3)",
        _hover={"background": "var(--gray-a2)"},
    )


def _mcs_topic_explorer_picker_row(item: dict) -> rx.Component:
    """One row in the Topic Definition Explorer's left-hand picker.
    Displays the topic name + category badge + action count, highlights
    the selected row."""
    is_selected = State.mcs_topic_explorer_selected == item["schema_name"]
    return rx.hstack(
        rx.vstack(
            rx.text(
                item["display_name"],
                font_size="12px",
                font_weight="600",
                color=rx.cond(is_selected, "var(--green-12)", "var(--gray-12)"),
                style={
                    "overflow": "hidden",
                    "textOverflow": "ellipsis",
                    "whiteSpace": "nowrap",
                },
            ),
            rx.hstack(
                rx.badge(item["category"], color_scheme="teal", variant="soft", size="1"),
                rx.text(
                    item["action_count"],
                    rx.text.span(" actions"),
                    font_size="10px",
                    color="var(--gray-a8)",
                ),
                spacing="2",
                align="center",
            ),
            spacing="1",
            align="start",
            width="100%",
            style={"minWidth": 0},
        ),
        on_click=State.select_topic_in_explorer(item["schema_name"]),
        cursor="pointer",
        padding="8px 10px",
        border_radius="6px",
        background=rx.cond(is_selected, "var(--green-a3)", "transparent"),
        border=rx.cond(is_selected, "1px solid var(--green-a6)", "1px solid transparent"),
        _hover={"background": "var(--green-a2)"},
        transition="background 0.1s ease",
        width="100%",
    )


def _mcs_topic_explorer_settings_row(row: dict) -> rx.Component:
    """One settings row inside the Topic Definition Explorer's right
    pane. Reuses the same kind/prop split used in the Topics tab so the
    rendering is consistent."""
    return rx.cond(
        row["row_type"] == "kind",
        _settings_kind_row(row),
        _settings_prop_row(row),
    )


def _mcs_topic_explorer_modal() -> rx.Component:
    """Dialog modal — searchable topic picker (left) + step-by-step
    settings rows (right). Opens via the call-to-action at the top of
    the Topics tab."""
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title("Topic Definition Explorer"),
            rx.dialog.description(
                "Browse every topic in the agent. Search by name or category, "
                "click a row to see its full step-by-step action tree (with "
                "branching) on the right.",
                size="2",
                margin_bottom="12px",
            ),
            rx.hstack(
                # Left pane — picker
                rx.vstack(
                    rx.input(
                        placeholder="Search topics…",
                        value=State.mcs_topic_explorer_search,
                        on_change=State.set_topic_explorer_search,
                        size="2",
                        width="100%",
                    ),
                    rx.text(
                        State.mcs_topic_explorer_filtered.length().to(str),  # type: ignore[union-attr]
                        rx.text.span(" / "),
                        State.mcs_topic_explorer_topics.length().to(str),  # type: ignore[union-attr]
                        rx.text.span(" topics"),
                        font_size="10px",
                        color="var(--gray-a8)",
                    ),
                    rx.box(
                        rx.foreach(
                            State.mcs_topic_explorer_filtered,
                            _mcs_topic_explorer_picker_row,
                        ),
                        width="100%",
                        max_height="60vh",
                        overflow_y="auto",
                        border=f"1px solid {SURFACE_BORDER}",
                        border_radius="8px",
                        padding="6px",
                    ),
                    spacing="2",
                    align="start",
                    width="40%",
                    flex_shrink="0",
                ),
                # Right pane — selected topic detail
                rx.box(
                    rx.cond(
                        State.mcs_topic_explorer_selected != "",
                        rx.vstack(
                            rx.hstack(
                                rx.text(
                                    State.mcs_topic_explorer_selected_meta["display_name"],
                                    font_size="16px",
                                    font_weight="700",
                                    color="var(--gray-12)",
                                ),
                                rx.badge(
                                    State.mcs_topic_explorer_selected_meta["category"],
                                    color_scheme="teal",
                                    variant="soft",
                                    size="1",
                                ),
                                rx.spacer(),
                                rx.text(
                                    State.mcs_topic_explorer_selected_meta["action_count"],
                                    rx.text.span(" actions"),
                                    font_size="11px",
                                    color="var(--gray-a8)",
                                ),
                                spacing="2",
                                align="center",
                                width="100%",
                            ),
                            rx.cond(
                                State.mcs_topic_explorer_selected_meta["schema_name"] != "",
                                rx.code(
                                    State.mcs_topic_explorer_selected_meta["schema_name"],
                                    font_size="10px",
                                    color="var(--gray-a9)",
                                ),
                            ),
                            rx.divider(),
                            rx.cond(
                                State.mcs_topic_explorer_selected_rows.length() > 0,  # type: ignore[union-attr]
                                rx.box(
                                    rx.foreach(
                                        State.mcs_topic_explorer_selected_rows,
                                        _mcs_topic_explorer_settings_row,
                                    ),
                                    width="100%",
                                    max_height="60vh",
                                    overflow_y="auto",
                                    padding_right="6px",
                                ),
                                rx.text(
                                    "This topic has no settings rows — its dialog "
                                    "tree is empty or wasn't captured during parse.",
                                    font_size="11px",
                                    color="var(--gray-a8)",
                                    font_style="italic",
                                ),
                            ),
                            spacing="2",
                            align="start",
                            width="100%",
                        ),
                        rx.center(
                            rx.text(
                                "Pick a topic on the left to see its action tree.",
                                font_size="12px",
                                color="var(--gray-a8)",
                                font_style="italic",
                            ),
                            min_height="200px",
                        ),
                    ),
                    flex_grow="1",
                    width="100%",
                    border=f"1px solid {SURFACE_BORDER}",
                    border_radius="8px",
                    padding="14px",
                    background="var(--gray-a2)",
                    style={"minWidth": 0},
                ),
                spacing="3",
                align="start",
                width="100%",
            ),
            rx.flex(
                rx.dialog.close(
                    rx.button("Close", size="2", variant="soft", color_scheme="gray"),
                ),
                spacing="2",
                margin_top="14px",
                justify="end",
            ),
            max_width="1100px",
            width="92vw",
        ),
        open=State.mcs_topic_explorer_open,
        on_open_change=State.set_topic_explorer_open,
    )


def _mcs_topic_explorer_card() -> rx.Component:
    """Call-to-action card at the top of the Topics tab opening the
    Topic Definition Explorer modal."""
    return rx.cond(
        State.mcs_topic_explorer_topics.length() > 0,  # type: ignore[union-attr]
        card(
            rx.hstack(
                rx.icon("compass", size=20, color=PRIMARY),
                rx.vstack(
                    rx.text(
                        "Topic Definition Explorer",
                        font_size="14px",
                        font_weight="700",
                        color="var(--gray-12)",
                    ),
                    rx.text(
                        "Browse every topic with a searchable picker + step-by-step "
                        "action tree (incl. branching). Useful for understanding "
                        "topic logic without leaving the analyser.",
                        font_size="11px",
                        color="var(--gray-a8)",
                        line_height="1.5",
                    ),
                    spacing="1",
                    align="start",
                    flex_grow="1",
                ),
                rx.button(
                    "Open Explorer",
                    rx.icon("external-link", size=12),
                    size="2",
                    variant="soft",
                    color_scheme="green",
                    on_click=State.open_topic_explorer,
                ),
                spacing="3",
                align="center",
                width="100%",
            ),
            width="100%",
        ),
    )


def _mcs_topics_panel() -> rx.Component:
    return rx.vstack(
        # Topic Definition Explorer launcher
        _mcs_topic_explorer_card(),
        # Explorer modal
        _mcs_topic_explorer_modal(),
        # KPI grid
        rx.grid(
            rx.foreach(State.mcs_topics_kpis, _mcs_kpi_card),
            columns="4",
            gap="10px",
            width="100%",
        ),
        # Category summary
        rx.cond(
            State.mcs_topics_summary.length() > 0,  # type: ignore[union-attr]
            card(
                section_heading("Category Summary"),
                _data_table(
                    ["Category", "Count", "Active", "Inactive"],
                    "3fr 1fr 1fr 1fr",
                    State.mcs_topics_summary,
                    _mcs_topics_summary_row,
                ),
                width="100%",
            ),
        ),
        # Anomaly chips
        rx.hstack(
            rx.foreach(State.mcs_topics_anomalies, _mcs_highlight_chip),
            spacing="2",
            width="100%",
            flex_wrap="wrap",
        ),
        # User Topics detail
        rx.cond(
            State.mcs_topics_user_rows.length() > 0,  # type: ignore[union-attr]
            card(
                section_heading("User Topics"),
                rx.box(
                    _grid_header("Name", "Schema", "State", "Triggers", "Description", template="2fr 2fr 1fr 2fr 2fr"),
                    rx.foreach(State.mcs_topics_user_rows, _mcs_topics_user_row),
                    width="100%",
                    border=f"1px solid {SURFACE_BORDER}",
                    border_radius="8px",
                    padding_x="12px",
                    background="var(--gray-a2)",
                    overflow_x="auto",
                ),
                width="100%",
            ),
        ),
        # Trigger Overlaps
        card(
            section_heading("Trigger Overlaps"),
            rx.text(
                "Topics with >50% token overlap in trigger phrases.",
                font_size="12px",
                color="var(--gray-a9)",
                padding_bottom="8px",
            ),
            rx.cond(
                State.mcs_profile_trigger_overlaps.length() > 0,  # type: ignore[union-attr]
                _data_table(
                    ["Topic A", "Topic B", "Overlap", "Shared Tokens"],
                    "2fr 2fr 1fr 3fr",
                    State.mcs_profile_trigger_overlaps,
                    _mcs_profile_overlap_row,
                ),
                rx.text(
                    "No overlaps detected — all topics have distinct trigger phrases.",
                    font_size="12px",
                    color="var(--gray-a8)",
                    font_style="italic",
                ),
            ),
            width="100%",
        ),
        # Orchestrator Topics detail
        rx.cond(
            State.mcs_topics_orch_rows.length() > 0,  # type: ignore[union-attr]
            card(
                section_heading("Orchestrator Topics"),
                _data_table(
                    ["Name", "State", "Tool Type", "Connector", "Mode"],
                    "2fr 1fr 1fr 1fr 1fr",
                    State.mcs_topics_orch_rows,
                    _mcs_topics_orch_row,
                ),
                width="100%",
            ),
        ),
        # System/Automation Topics
        rx.cond(
            State.mcs_topics_system_rows.length() > 0,  # type: ignore[union-attr]
            card(
                section_heading("System & Automation Topics"),
                _data_table(
                    ["Name", "Schema", "State", "Trigger"],
                    "2fr 2fr 1fr 1fr",
                    State.mcs_topics_system_rows,
                    _mcs_topics_system_row,
                ),
                width="100%",
            ),
        ),
        # Topic graph
        _mermaid_block(State.mcs_topics_mermaid),
        spacing="4",
        width="100%",
    )


# ── Model panel ──────────────────────────────────────────────────────────


def _mcs_model_config_row(item: dict) -> rx.Component:
    return info_row(item["property"], item["value"])


def _mcs_model_catalogue_row(item: dict) -> rx.Component:
    is_current = item["is_current"] == "yes"
    return rx.grid(
        rx.text(item["model"], font_size="13px", color="var(--gray-12)", font_weight=rx.cond(is_current, "700", "400")),
        rx.text(item["tier"], font_size="13px", color="var(--gray-a9)"),
        rx.text(item["context"], font_size="13px", color="var(--gray-11)"),
        rx.text(item["cost"], font_size="13px", color="var(--gray-a9)"),
        columns="2fr 2fr 1fr 1fr",
        gap="8px",
        align="center",
        padding_y="6px",
        border_bottom=f"1px solid {SURFACE_BORDER}",
        border_left=rx.cond(is_current, f"3px solid {PRIMARY}", "3px solid transparent"),
        padding_left="8px",
        background=rx.cond(is_current, "var(--green-a2)", "transparent"),
        width="100%",
    )


def _mcs_model_panel() -> rx.Component:
    return rx.vstack(
        # KPI grid
        rx.grid(
            rx.foreach(State.mcs_model_kpis, _mcs_kpi_card),
            columns="4",
            gap="10px",
            width="100%",
        ),
        # Configured model card
        card(
            section_heading("Configured Model"),
            rx.vstack(
                rx.foreach(State.mcs_model_configured, _mcs_model_config_row),
                spacing="1",
                width="100%",
                padding_top="8px",
            ),
            width="100%",
        ),
        # Strengths / Limitations
        rx.cond(
            State.mcs_model_strengths.length() > 0,  # type: ignore[union-attr]
            rx.grid(
                card(
                    rx.hstack(
                        rx.icon("check-circle", size=16, color="var(--green-9)"),
                        rx.text("Strengths", font_size="14px", font_weight="700", color="var(--gray-12)"),
                        spacing="2",
                        align="center",
                    ),
                    rx.vstack(
                        rx.foreach(
                            State.mcs_model_strengths,
                            lambda s: rx.hstack(
                                rx.text("•", color="var(--green-9)"),
                                rx.text(s, font_size="13px", color="var(--gray-12)"),
                                spacing="2",
                                align="start",
                            ),
                        ),
                        spacing="1",
                        width="100%",
                        padding_top="8px",
                    ),
                    width="100%",
                ),
                card(
                    rx.hstack(
                        rx.icon("alert-triangle", size=16, color="var(--amber-9)"),
                        rx.text("Limitations", font_size="14px", font_weight="700", color="var(--gray-12)"),
                        spacing="2",
                        align="center",
                    ),
                    rx.vstack(
                        rx.foreach(
                            State.mcs_model_limitations,
                            lambda s: rx.hstack(
                                rx.text("•", color="var(--amber-9)"),
                                rx.text(s, font_size="13px", color="var(--gray-12)"),
                                spacing="2",
                                align="start",
                            ),
                        ),
                        spacing="1",
                        width="100%",
                        padding_top="8px",
                    ),
                    width="100%",
                ),
                columns="2",
                gap="10px",
                width="100%",
            ),
        ),
        # Recommendation
        rx.cond(
            State.mcs_model_recommendation != "",
            card(
                rx.hstack(
                    rx.icon("lightbulb", size=16, color=PRIMARY),
                    rx.text("Recommendation", font_size="14px", font_weight="700", color="var(--gray-12)"),
                    spacing="2",
                    align="center",
                ),
                rx.text(
                    State.mcs_model_recommendation,
                    font_size="13px",
                    color="var(--gray-12)",
                    line_height="1.6",
                    padding_top="8px",
                ),
                width="100%",
            ),
        ),
        # Model catalogue
        card(
            section_heading("Model Catalogue"),
            rx.box(
                _grid_header("Model", "Tier", "Context", "Cost", template="2fr 2fr 1fr 1fr"),
                rx.foreach(State.mcs_model_catalogue, _mcs_model_catalogue_row),
                width="100%",
                border=f"1px solid {SURFACE_BORDER}",
                border_radius="8px",
                padding_x="12px",
                background="var(--gray-a2)",
            ),
            width="100%",
        ),
        spacing="4",
        width="100%",
    )


# ── Conversation detail panel ─────────────────────────────────────────────────


def _mcs_conv_meta_row(item: dict) -> rx.Component:
    return info_row(item["property"], item["value"])


def _mcs_waterfall_row(item: dict) -> rx.Component:
    """One row in the Performance Waterfall: activity label + a
    horizontal proportional bar whose width is the gap-to-previous as a
    percentage of the largest gap. The colour reflects the event
    category (Message / Plan / Action / Knowledge / Orchestrator /
    Trace / Error)."""
    return rx.hstack(
        rx.text(
            item["timestamp"],
            font_size="10px",
            color="var(--gray-a7)",
            font_family=_MONO,
            min_width="64px",
            flex_shrink="0",
        ),
        rx.badge(
            item["category"],
            color_scheme=rx.match(
                item["category"],
                ("Message", "green"),
                ("Plan", "blue"),
                ("Action", "teal"),
                ("AI Builder", "purple"),
                ("Knowledge", "amber"),
                ("Orchestrator", "violet"),
                ("Trace", "gray"),
                ("Error", "red"),
                "gray",
            ),
            variant="soft",
            size="1",
        ),
        rx.text(
            item["label"],
            font_size="11px",
            color="var(--gray-12)",
            min_width="180px",
            flex_grow="1",
            style={"overflow": "hidden", "textOverflow": "ellipsis", "whiteSpace": "nowrap"},
        ),
        rx.box(
            rx.box(
                width=item["width_pct"],
                height="10px",
                background=item["color"],
                border_radius="4px",
                min_width="2px",
            ),
            width="40%",
            height="10px",
            background="var(--gray-a3)",
            border_radius="4px",
            position="relative",
            overflow="hidden",
        ),
        rx.text(
            item["gap_fmt"],
            font_size="10px",
            color="var(--gray-a8)",
            font_family=_MONO,
            min_width="50px",
            text_align="right",
        ),
        spacing="2",
        align="center",
        width="100%",
        padding="3px 0",
    )


def _mcs_conv_phase_row(item: dict) -> rx.Component:
    return rx.grid(
        rx.text(item["label"], font_size="13px", color="var(--gray-12)", font_weight="500"),
        rx.text(item["phase_type"], font_size="13px", color="var(--gray-a9)"),
        rx.text(item["duration"], font_size="13px", color="var(--gray-11)", font_family=_MONO),
        rx.text(item["pct"], font_size="13px", color="var(--gray-a9)", text_align="right"),
        _status_badge(item["status"], item["status_tone"]),
        columns="2fr 1fr 1fr 1fr 1fr",
        gap="8px",
        align="center",
        padding_y="6px",
        border_bottom=f"1px solid {SURFACE_BORDER}",
        width="100%",
    )


def _mcs_conv_event_row(item: dict) -> rx.Component:
    return rx.grid(
        rx.text(item["index"], font_size="13px", color="var(--gray-a9)", text_align="right"),
        rx.text(item["position"], font_size="13px", color="var(--gray-11)", font_family=_MONO),
        rx.badge(
            item["event_type"],
            color_scheme=rx.match(
                item["type_color"],
                ("green", "green"),
                ("blue", "blue"),
                ("teal", "teal"),
                ("amber", "amber"),
                ("red", "red"),
                ("purple", "purple"),
                "gray",
            ),
            variant="soft",
            size="1",
        ),
        rx.text(
            item["summary"],
            font_size="12px",
            color="var(--gray-11)",
            overflow="hidden",
            text_overflow="ellipsis",
            white_space="nowrap",
        ),
        columns="0.5fr 0.5fr 1.5fr 4fr",
        gap="8px",
        align="center",
        padding_y="6px",
        border_bottom=f"1px solid {SURFACE_BORDER}",
        width="100%",
    )


def _mcs_conv_error_item(error: str) -> rx.Component:
    return rx.box(
        rx.hstack(
            rx.icon("triangle-alert", size=14, color="var(--red-9)"),
            rx.text(error, font_size="13px", color="var(--red-11)"),
            spacing="2",
            align="start",
        ),
        background="var(--red-a2)",
        border="1px solid var(--red-a4)",
        border_radius="8px",
        padding="10px 12px",
        width="100%",
    )


def _mcs_conv_reasoning_row(item: dict) -> rx.Component:
    return rx.box(
        rx.vstack(
            # Header row: step number + topic badge + step_type badge + status badge + duration
            rx.hstack(
                rx.text(
                    rx.text.span("#"),
                    rx.text.span(item["step"], font_weight="600"),
                    font_size="12px",
                    color="var(--gray-a9)",
                ),
                rx.badge(item["topic"], color_scheme="teal", variant="soft", size="1"),
                rx.cond(
                    item["step_type"] != "",
                    rx.badge(item["step_type"], color_scheme="gray", variant="outline", size="1"),
                    rx.box(),
                ),
                rx.cond(
                    item["status"] != "",
                    rx.badge(
                        item["status"],
                        color_scheme=rx.cond(item["status"] == "completed", "green", "red"),
                        variant="soft",
                        size="1",
                    ),
                    rx.box(),
                ),
                rx.cond(
                    item["duration"] != "",
                    rx.text(item["duration"], font_size="11px", color="var(--gray-a8)", font_family=_MONO),
                    rx.box(),
                ),
                spacing="2",
                align="center",
                flex_wrap="wrap",
            ),
            # Reasoning text
            rx.text(item["reasoning"], font_size="12px", color="var(--gray-11)", line_height="1.5"),
            # Conditional details
            rx.cond(
                item["orchestrator_ask"] != "",
                rx.text(
                    rx.text.span("Ask: ", font_weight="600", color="var(--gray-a8)"),
                    rx.text.span(item["orchestrator_ask"], font_style="italic"),
                    font_size="11px",
                    color="var(--violet-11)",
                ),
                rx.box(),
            ),
            rx.cond(
                item["has_recommendations"] == "true",
                rx.badge("Alternatives considered", color_scheme="amber", variant="soft", size="1"),
                rx.box(),
            ),
            rx.cond(
                item["used_outputs"] != "",
                rx.text(
                    rx.text.span("Outputs: ", font_weight="600", color="var(--gray-a8)"),
                    rx.text.span(item["used_outputs"]),
                    font_size="11px",
                    color="var(--blue-9)",
                ),
                rx.box(),
            ),
            rx.cond(
                item["error"] != "",
                rx.text(item["error"], font_size="11px", color="var(--red-9)"),
                rx.box(),
            ),
            spacing="1",
            width="100%",
        ),
        padding="10px 14px",
        border_bottom=f"1px solid {SURFACE_BORDER}",
        width="100%",
    )


def _mcs_var_argument_row(arg: dict) -> rx.Component:
    """One argument inside a Variable Tracker card. Shows the binding key,
    its value, and an AUTO/MANUAL badge."""
    return rx.hstack(
        rx.text(
            arg["name"],
            font_size="11px",
            color="var(--gray-a9)",
            font_family=_MONO,
            min_width="140px",
        ),
        rx.code(arg["value"], font_size="11px", color="var(--gray-12)"),
        rx.spacer(),
        rx.cond(
            arg["auto_filled"] != "",
            rx.badge("AUTO", color_scheme="amber", variant="soft", size="1"),
            rx.badge("MANUAL", color_scheme="gray", variant="soft", size="1"),
        ),
        spacing="2",
        align="center",
        width="100%",
        padding="3px 0",
    )


def _mcs_var_card_header(item: dict, icon_name: str, badge_color: str) -> rx.Component:
    """Header row shared across the three Variable Tracker card kinds."""
    return rx.vstack(
        rx.hstack(
            rx.icon(icon_name, size=14, color=PRIMARY),
            rx.text(
                item["display_name"],
                font_size="13px",
                font_weight="700",
                color="var(--gray-12)",
            ),
            rx.badge(
                item["step_type"],
                color_scheme=badge_color,
                variant="soft",
                size="1",
            ),
            _status_badge(item["state"], item["state_tone"]),
            rx.cond(
                (item["duration"] != "—") & (item["duration"] != ""),
                rx.text(
                    item["duration"],
                    font_size="11px",
                    color="var(--gray-a8)",
                    font_family=_MONO,
                ),
            ),
            rx.cond(
                item["timestamp"] != "",
                rx.text(
                    item["timestamp"],
                    font_size="11px",
                    color="var(--gray-a7)",
                    font_family=_MONO,
                ),
            ),
            spacing="2",
            align="center",
            width="100%",
            flex_wrap="wrap",
        ),
        rx.cond(
            item["thought"] != "",
            rx.text(
                item["thought"],
                font_size="11px",
                font_style="italic",
                color="var(--gray-a9)",
                line_height="1.4",
            ),
        ),
        spacing="2",
        align="start",
        width="100%",
    )


def _mcs_var_kv_row(label: str, value, mono: bool = False, italic: bool = False) -> rx.Component:
    """Generic 'label: value' row used by the variable_assignment and
    generative_answer card kinds."""
    return rx.cond(
        value != "",
        rx.hstack(
            rx.text(
                label,
                font_size="11px",
                color="var(--gray-a8)",
                font_weight="700",
                min_width="120px",
            ),
            rx.text(
                value,
                font_size="11px",
                color="var(--gray-12)",
                font_family=_MONO if mono else None,
                font_style="italic" if italic else "normal",
                line_height="1.5",
                style={"wordBreak": "break-word"},
            ),
            spacing="2",
            align="start",
            width="100%",
            padding="2px 0",
        ),
    )


def _mcs_var_card_tool_call(item: dict) -> rx.Component:
    return rx.vstack(
        _mcs_var_card_header(item, "wrench", "teal"),
        rx.cond(
            item["has_arguments"] != "",
            rx.box(
                rx.text(
                    "Arguments",
                    font_size="11px",
                    color="var(--gray-a8)",
                    font_weight="700",
                    margin_bottom="4px",
                ),
                rx.foreach(
                    item["arguments"].to(list[dict]),  # type: ignore[union-attr]
                    _mcs_var_argument_row,
                ),
                width="100%",
            ),
        ),
        rx.cond(
            item["has_output"] != "",
            rx.vstack(
                rx.cond(
                    item["output_preview"] != "",
                    rx.hstack(
                        rx.text(
                            "Output:",
                            font_size="11px",
                            color="var(--gray-a8)",
                            font_weight="700",
                        ),
                        rx.code(
                            item["output_preview"],
                            font_size="11px",
                            color="var(--gray-12)",
                        ),
                        spacing="2",
                        align="center",
                    ),
                ),
                rx.cond(
                    item["output_full"] != "",
                    rx.accordion.root(
                        rx.accordion.item(
                            header=rx.text(
                                "Raw output JSON",
                                font_size="11px",
                                color="var(--gray-a9)",
                                font_weight="700",
                            ),
                            content=rx.box(
                                rx.el.pre(
                                    item["output_full"],
                                    style={
                                        "fontSize": "10px",
                                        "color": "var(--gray-12)",
                                        "lineHeight": "1.5",
                                        "whiteSpace": "pre-wrap",
                                        "wordBreak": "break-word",
                                    },
                                ),
                                background="var(--gray-a3)",
                                border_radius="6px",
                                padding="8px 10px",
                                max_height="320px",
                                overflow_y="auto",
                                width="100%",
                            ),
                            value="raw_json",
                        ),
                        type="single",
                        collapsible=True,
                        variant="ghost",
                        width="100%",
                    ),
                ),
                spacing="2",
                align="start",
                width="100%",
            ),
        ),
        rx.cond(
            item["error"] != "",
            rx.box(
                rx.hstack(
                    rx.icon("triangle-alert", size=12, color="var(--red-9)"),
                    rx.text(
                        item["error"],
                        font_size="11px",
                        color="var(--red-11)",
                    ),
                    spacing="2",
                    align="center",
                ),
                background="var(--red-a2)",
                border="1px solid var(--red-a4)",
                border_radius="6px",
                padding="6px 10px",
                width="100%",
            ),
        ),
        spacing="3",
        align="start",
        width="100%",
    )


def _mcs_var_card_variable_assignment(item: dict) -> rx.Component:
    return rx.vstack(
        _mcs_var_card_header(item, "variable", "purple"),
        rx.hstack(
            rx.cond(
                item["var_scope"] != "",
                rx.badge(
                    item["var_scope"],
                    color_scheme="gray",
                    variant="soft",
                    size="1",
                ),
            ),
            rx.code(
                item["var_name"],
                font_size="11px",
                color="var(--gray-12)",
            ),
            rx.text("=", font_size="11px", color="var(--gray-a8)"),
            rx.code(
                item["var_value"],
                font_size="11px",
                color="var(--green-11)",
                style={"wordBreak": "break-word"},
            ),
            spacing="2",
            align="center",
            width="100%",
            flex_wrap="wrap",
        ),
        spacing="3",
        align="start",
        width="100%",
    )


def _mcs_var_card_generative_answer(item: dict) -> rx.Component:
    return rx.vstack(
        _mcs_var_card_header(item, "sparkles", "amber"),
        rx.cond(
            item["ga_output_variable"] != "",
            rx.hstack(
                rx.text(
                    "Writes to:",
                    font_size="11px",
                    color="var(--gray-a8)",
                    font_weight="700",
                ),
                rx.code(
                    item["ga_output_variable"],
                    font_size="11px",
                    color="var(--green-11)",
                ),
                rx.spacer(),
                rx.cond(
                    item["ga_citation_count"] != "0",
                    rx.badge(
                        item["ga_citation_count"].to(str),  # type: ignore[union-attr]
                        rx.text.span(" citations"),
                        color_scheme="blue",
                        variant="soft",
                        size="1",
                    ),
                ),
                spacing="2",
                align="center",
                width="100%",
            ),
        ),
        _mcs_var_kv_row("User asked", item["ga_original"], italic=True),
        _mcs_var_kv_row("Rewritten", item["ga_rewritten"], italic=True),
        _mcs_var_kv_row("Keywords", item["ga_keywords"], mono=True),
        rx.cond(
            item["ga_summary"] != "",
            rx.box(
                rx.text(
                    "Summary",
                    font_size="11px",
                    color="var(--gray-a8)",
                    font_weight="700",
                    margin_bottom="4px",
                ),
                rx.text(
                    item["ga_summary"],
                    font_size="11px",
                    color="var(--gray-12)",
                    line_height="1.5",
                    style={"wordBreak": "break-word"},
                ),
                background="var(--gray-a3)",
                border_radius="6px",
                padding="8px 10px",
                width="100%",
            ),
        ),
        spacing="3",
        align="start",
        width="100%",
    )


def _mcs_var_card(item: dict) -> rx.Component:
    """Variable Tracker card. Dispatches on `card_kind` to render the
    right shape per row (tool_call / variable_assignment / generative_answer)."""
    return rx.box(
        rx.match(
            item["card_kind"],
            ("tool_call", _mcs_var_card_tool_call(item)),
            ("variable_assignment", _mcs_var_card_variable_assignment(item)),
            ("generative_answer", _mcs_var_card_generative_answer(item)),
            rx.fragment(),
        ),
        id=item["row_id"],
        padding="14px 16px",
        background="var(--gray-a2)",
        border=f"1px solid {SURFACE_BORDER}",
        border_radius="10px",
        width="100%",
    )


def _mcs_error_banner_row(item: dict) -> rx.Component:
    """One row inside the error banner — clickable, jumps to the offending
    Conversation Flow event via `set_dynamic_link_target`."""
    return rx.hstack(
        rx.icon("triangle-alert", size=14, color="var(--red-9)"),
        rx.vstack(
            rx.hstack(
                rx.text(
                    item["title"],
                    font_size="12px",
                    font_weight="700",
                    color="var(--red-11)",
                ),
                rx.cond(
                    item["topic_name"] != "",
                    rx.badge(item["topic_name"], color_scheme="red", variant="soft", size="1"),
                    rx.box(),
                ),
                rx.cond(
                    item["timestamp"] != "",
                    rx.text(
                        item["timestamp"],
                        font_size="10px",
                        color="var(--red-a9)",
                        font_family=_MONO,
                    ),
                    rx.box(),
                ),
                spacing="2",
                align="center",
                flex_wrap="wrap",
            ),
            rx.text(
                item["summary"],
                font_size="11px",
                color="var(--red-11)",
                line_height="1.4",
                style={"wordBreak": "break-word"},
            ),
            spacing="1",
            align="start",
            width="100%",
        ),
        rx.spacer(),
        rx.icon("arrow-up-right", size=12, color="var(--red-a10)"),
        spacing="2",
        align="start",
        width="100%",
        padding="8px 10px",
        border_radius="6px",
        cursor="pointer",
        on_click=State.set_dynamic_link_target("conversation", item["flow_id"]),
        _hover={"background": "var(--red-a3)"},
        transition="background 0.15s ease",
    )


def _mcs_error_banner() -> rx.Component:
    """Banner at the top of the Conversation tab summarising every
    error-toned event with click-to-jump to the offending row.
    Hidden when there are no errors."""
    return rx.cond(
        State.mcs_conv_error_banner.length() > 0,  # type: ignore[union-attr]
        rx.box(
            rx.hstack(
                rx.icon("triangle-alert", size=18, color="var(--red-9)"),
                rx.text(
                    "Errors detected — click to jump to the failing step",
                    font_size="13px",
                    font_weight="700",
                    color="var(--red-11)",
                ),
                rx.spacer(),
                rx.badge(
                    State.mcs_conv_error_banner.length().to(str),  # type: ignore[union-attr]
                    color_scheme="red",
                    variant="solid",
                    size="1",
                ),
                spacing="2",
                align="center",
                width="100%",
            ),
            rx.vstack(
                rx.foreach(State.mcs_conv_error_banner, _mcs_error_banner_row),
                spacing="1",
                width="100%",
                padding_top="6px",
            ),
            background="var(--red-a2)",
            border="1px solid var(--red-a5)",
            border_radius="10px",
            padding="12px 14px",
            width="100%",
        ),
    )


def _mcs_conv_expand_collapse_bar() -> rx.Component:
    """Compact button row toggling every accordion under the Conversation
    tab open or closed. Click handlers walk the DOM via call_script."""
    return rx.hstack(
        rx.spacer(),
        rx.button(
            rx.icon("chevrons-down", size=12),
            "Expand all",
            size="1",
            variant="soft",
            color_scheme="gray",
            on_click=State.conv_expand_all,
        ),
        rx.button(
            rx.icon("chevrons-up", size=12),
            "Collapse all",
            size="1",
            variant="soft",
            color_scheme="gray",
            on_click=State.conv_collapse_all,
        ),
        spacing="2",
        align="center",
        width="100%",
    )


def _mcs_conversation_detail_panel() -> rx.Component:
    return rx.cond(
        State.has_mcs_conv_detail,
        rx.vstack(
            # Expand/collapse-all toolbar (Conv tab scope)
            _mcs_conv_expand_collapse_bar(),
            # Error banner (hidden when no errors)
            _mcs_error_banner(),
            # Metadata card
            card(
                rx.hstack(
                    rx.icon("info", size=16, color=PRIMARY),
                    section_heading("Conversation Metadata"),
                    spacing="2",
                    align="center",
                ),
                rx.vstack(
                    rx.foreach(State.mcs_conv_metadata, _mcs_conv_meta_row),
                    spacing="1",
                    width="100%",
                    padding_top="8px",
                ),
                width="100%",
            ),
            # Sequence diagram
            _mermaid_block(State.mcs_conv_sequence_mermaid),
            # Gantt chart
            _mermaid_block(State.mcs_conv_gantt_mermaid),
            # Phase breakdown
            rx.cond(
                State.mcs_conv_phases.length() > 0,  # type: ignore[union-attr]
                card(
                    rx.hstack(
                        rx.icon("layers", size=16, color=PRIMARY),
                        section_heading("Phase Breakdown"),
                        spacing="2",
                        align="center",
                    ),
                    rx.box(
                        _grid_header(
                            "Phase", "Type", "Duration", "% of Total", "Status", template="2fr 1fr 1fr 1fr 1fr"
                        ),
                        rx.foreach(State.mcs_conv_phases, _mcs_conv_phase_row),
                        width="100%",
                        border=f"1px solid {SURFACE_BORDER}",
                        border_radius="8px",
                        padding_x="12px",
                        background="var(--gray-a2)",
                        overflow_x="auto",
                    ),
                    width="100%",
                ),
            ),
            # Performance Waterfall — between-activity gaps with
            # category-colored bars so bottlenecks stand out. Different
            # framing from the Gantt (which shows phase totals).
            rx.cond(
                State.mcs_conv_waterfall.length() > 0,  # type: ignore[union-attr]
                card(
                    rx.hstack(
                        rx.icon("activity", size=16, color=PRIMARY),
                        section_heading("Performance Waterfall"),
                        rx.spacer(),
                        rx.badge(
                            State.mcs_conv_waterfall.length().to(str),  # type: ignore[union-attr]
                            color_scheme="green",
                            variant="soft",
                            size="1",
                        ),
                        align="center",
                        width="100%",
                    ),
                    rx.text(
                        "Time gap between consecutive activities. Bar widths are "
                        "proportional to the longest gap so the slowest step is "
                        "easiest to find. User-think idle time is suppressed.",
                        font_size="11px",
                        color="var(--gray-a8)",
                        font_style="italic",
                    ),
                    rx.box(
                        rx.foreach(State.mcs_conv_waterfall, _mcs_waterfall_row),
                        width="100%",
                        padding_top="8px",
                        max_height="480px",
                        overflow_y="auto",
                    ),
                    width="100%",
                ),
            ),
            # Variable Tracker — unified surface across orchestrator tool
            # calls, topic-level variable assignments, and topic-level
            # generative-answer traces. Always rendered so the section
            # never silently disappears for bots without tool calls.
            card(
                rx.hstack(
                    rx.icon("variable", size=16, color=PRIMARY),
                    section_heading("Variable Tracker"),
                    rx.spacer(),
                    rx.badge(
                        State.mcs_conv_variables.length().to(str),  # type: ignore[union-attr]
                        color_scheme="green",
                        variant="soft",
                        size="1",
                    ),
                    align="center",
                    width="100%",
                ),
                rx.text(
                    "Inputs, outputs, and harvested values across the conversation: "
                    "orchestrator tool calls (AUTO/MANUAL bindings), Topic / Global "
                    "variable assignments, and topic-level Generative Answer traces.",
                    font_size="11px",
                    color="var(--gray-a8)",
                    font_style="italic",
                ),
                rx.cond(
                    State.mcs_conv_variables.length() > 0,  # type: ignore[union-attr]
                    rx.vstack(
                        rx.foreach(State.mcs_conv_variables, _mcs_var_card),
                        spacing="3",
                        width="100%",
                        padding_top="8px",
                    ),
                    rx.box(
                        rx.hstack(
                            rx.icon("info", size=14, color="var(--gray-a8)"),
                            rx.text(
                                "No variable activity captured for this conversation. "
                                "This bot didn't trigger orchestrator tool calls, set "
                                "Topic / Global variables, or run a topic-level "
                                "generative answer.",
                                font_size="11px",
                                color="var(--gray-a9)",
                                font_style="italic",
                                line_height="1.5",
                            ),
                            spacing="2",
                            align="start",
                        ),
                        background="var(--gray-a3)",
                        border_radius="6px",
                        padding="10px 12px",
                        width="100%",
                        margin_top="8px",
                    ),
                ),
                width="100%",
            ),
            # Event log
            rx.cond(
                State.mcs_conv_event_log.length() > 0,  # type: ignore[union-attr]
                card(
                    rx.hstack(
                        rx.icon("list", size=16, color=PRIMARY),
                        section_heading("Event Log"),
                        rx.spacer(),
                        rx.badge(
                            State.mcs_conv_event_log.length().to(str),  # type: ignore[union-attr]
                            color_scheme="green",
                            variant="soft",
                            size="1",
                        ),
                        align="center",
                        width="100%",
                    ),
                    rx.box(
                        _grid_header("#", "Position", "Type", "Summary", template="0.5fr 0.5fr 1.5fr 4fr"),
                        rx.foreach(State.mcs_conv_event_log, _mcs_conv_event_row),
                        width="100%",
                        border=f"1px solid {SURFACE_BORDER}",
                        border_radius="8px",
                        padding_x="12px",
                        background="var(--gray-a2)",
                        overflow_x="auto",
                        max_height="600px",
                        overflow_y="auto",
                    ),
                    width="100%",
                ),
            ),
            # Errors
            rx.cond(
                State.mcs_conv_errors.length() > 0,  # type: ignore[union-attr]
                card(
                    rx.hstack(
                        rx.icon("triangle-alert", size=16, color="var(--red-9)"),
                        section_heading("Errors"),
                        rx.spacer(),
                        rx.badge(
                            State.mcs_conv_errors.length().to(str),  # type: ignore[union-attr]
                            color_scheme="red",
                            variant="soft",
                            size="1",
                        ),
                        align="center",
                        width="100%",
                    ),
                    rx.vstack(
                        rx.foreach(State.mcs_conv_errors, _mcs_conv_error_item),
                        spacing="2",
                        width="100%",
                        padding_top="8px",
                    ),
                    width="100%",
                ),
            ),
            # Orchestrator reasoning
            rx.cond(
                State.mcs_conv_reasoning.length() > 0,  # type: ignore[union-attr]
                card(
                    rx.hstack(
                        rx.icon("brain", size=16, color=PRIMARY),
                        section_heading("Orchestrator Reasoning"),
                        spacing="2",
                        align="center",
                    ),
                    rx.box(
                        rx.foreach(State.mcs_conv_reasoning, _mcs_conv_reasoning_row),
                        width="100%",
                        border=f"1px solid {SURFACE_BORDER}",
                        border_radius="8px",
                        background="var(--gray-a2)",
                        overflow="hidden",
                    ),
                    width="100%",
                ),
            ),
            spacing="4",
            width="100%",
            id="mcs-conv-tab-root",
        ),
    )


# ── Section content block ─────────────────────────────────────────────────────


def _mcs_segment_block(segment: dict) -> rx.Component:
    return rx.box(
        render_segment_styled(segment),
        width="100%",
    )


# ── Custom findings (dynamic view) ────────────────────────────────────────────


def _mcs_finding_row(finding: dict) -> rx.Component:
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


def _mcs_custom_findings_section() -> rx.Component:
    return rx.cond(
        State.has_mcs_custom_findings,
        rx.box(
            rx.hstack(
                rx.icon("shield-check", size=16, color=PRIMARY),
                rx.text("Custom Rules", size="3", font_weight="500", color="var(--gray-12)"),
                rx.badge(
                    State.mcs_custom_findings.length().to(str),  # type: ignore[union-attr]
                    color_scheme="green",
                    variant="soft",
                    size="1",
                ),
                align="center",
                spacing="2",
            ),
            rx.box(
                rx.foreach(State.mcs_custom_findings, _mcs_finding_row),
                width="100%",
                border=f"1px solid {SURFACE_BORDER}",
                border_radius="8px",
                overflow="hidden",
                margin_top="8px",
            ),
            padding_top="24px",
            padding_bottom="8px",
        ),
    )


# ── Insights panel (conversation analysis features) ───────────────────────────

_INS_LABEL = dict(
    font_size="11px", font_weight="700", color="var(--gray-a9)", text_transform="uppercase", letter_spacing="0.04em"
)
_INS_CELL = dict(font_size="13px", color="var(--gray-12)", font_family=_MONO)
_INS_HEADER_CELL = dict(font_size="11px", font_weight="700", color="var(--gray-a9)")
_INS_ROW_BORDER = f"1px solid {SURFACE_BORDER}"


def _ins_kpi(item: dict) -> rx.Component:
    tone = item.get("tone", "")
    return rx.box(
        rx.text(item["label"], **_INS_LABEL),
        rx.text(item["value"], font_size="22px", font_weight="800", color="var(--gray-12)", line_height="1.2"),
        border=rx.cond(
            tone == "warn",
            "1px solid var(--amber-8)",
            rx.cond(
                tone == "danger",
                "1px solid var(--red-8)",
                rx.cond(tone == "good", f"1px solid {PRIMARY}", f"1px solid {SURFACE_BORDER}"),
            ),
        ),
        border_radius="10px",
        background="var(--gray-a2)",
        padding="10px 14px",
        min_width="100px",
    )


def _ins_card_header(icon_name: str, icon_color: str, title: str, subtitle: str) -> rx.Component:
    return rx.vstack(
        rx.hstack(rx.icon(icon_name, size=16, color=icon_color), section_heading(title), spacing="2", align="center"),
        rx.text(subtitle, font_size="12px", color="var(--gray-a9)"),
        spacing="1",
        width="100%",
    )


def _ins_turn_row(item: dict) -> rx.Component:
    return rx.grid(
        rx.text(item["turn"], **_INS_CELL, text_align="right"),
        rx.text(
            item["message"],
            font_size="13px",
            color="var(--gray-12)",
            overflow="hidden",
            text_overflow="ellipsis",
            white_space="nowrap",
        ),
        rx.text(item["plans"], **_INS_CELL, text_align="right"),
        rx.text(item["tools"], **_INS_CELL, text_align="right"),
        rx.text(item["searches"], **_INS_CELL, text_align="right"),
        rx.text(item["thinking"], **_INS_CELL, text_align="right"),
        rx.text(item["total"], **_INS_CELL, text_align="right"),
        rx.cond(
            item["flags"] != "",
            rx.badge(item["flags"], color_scheme="amber", variant="soft", size="1"),
            rx.text("—", color="var(--gray-a7)", font_size="12px"),
        ),
        columns="0.4fr 2.5fr 0.5fr 0.5fr 0.6fr 0.8fr 0.8fr 2fr",
        gap="8px",
        align="center",
        padding_y="6px",
        border_bottom=_INS_ROW_BORDER,
        width="100%",
    )


def _ins_quality_row(item: dict) -> rx.Component:
    return rx.grid(
        rx.text(item["turn"], **_INS_CELL, text_align="right"),
        rx.badge(
            item["risk"],
            color_scheme=rx.match(item["risk"], ("high", "red"), ("medium", "amber"), "green"),
            variant="soft",
            size="1",
        ),
        rx.badge(item["source"], variant="outline", size="1"),
        rx.text(item["flags"], font_size="12px", color="var(--gray-11)"),
        columns="0.4fr 0.8fr 0.8fr 4fr",
        gap="8px",
        align="center",
        padding_y="6px",
        border_bottom=_INS_ROW_BORDER,
        width="100%",
    )


def _ins_plan_diff_item(item: dict) -> rx.Component:
    return rx.box(
        rx.hstack(
            rx.badge(f"Turn {item['turn']}", variant="soft", color_scheme="violet", size="1"),
            rx.cond(
                item["is_thrashing"] == "yes", rx.badge("THRASHING", color_scheme="red", variant="solid", size="1")
            ),
            spacing="2",
            align="center",
        ),
        rx.cond(
            item["ask"] != "",
            rx.text(item["ask"], font_size="12px", color="var(--gray-a9)", font_style="italic", padding_top="4px"),
        ),
        rx.hstack(
            rx.cond(
                item["added"] != "",
                rx.hstack(
                    rx.text("+", color="var(--green-9)", font_weight="700"),
                    rx.text(item["added"], font_size="12px", font_family=_MONO, color="var(--green-11)"),
                    spacing="1",
                    align="center",
                ),
            ),
            rx.cond(
                item["removed"] != "",
                rx.hstack(
                    rx.text("−", color="var(--red-9)", font_weight="700"),
                    rx.text(item["removed"], font_size="12px", font_family=_MONO, color="var(--red-11)"),
                    spacing="1",
                    align="center",
                ),
            ),
            spacing="4",
            padding_top="4px",
        ),
        padding="10px 0",
        border_bottom=_INS_ROW_BORDER,
        width="100%",
    )


def _ins_ke_row(item: dict) -> rx.Component:
    return rx.grid(
        rx.text(
            item["source"],
            font_size="13px",
            color="var(--gray-12)",
            overflow="hidden",
            text_overflow="ellipsis",
            white_space="nowrap",
        ),
        rx.text(item["queries"], **_INS_CELL, text_align="right"),
        rx.text(item["contributions"], **_INS_CELL, text_align="right"),
        rx.badge(
            item["hit_rate"],
            color_scheme=rx.match(item["hit_tone"], ("good", "green"), ("warn", "amber"), "red"),
            variant="soft",
            size="1",
        ),
        rx.text(item["errors"], **_INS_CELL, text_align="right"),
        rx.text(item["avg_results"], **_INS_CELL, text_align="right"),
        columns="2fr 0.7fr 0.9fr 0.7fr 0.6fr 0.7fr",
        gap="8px",
        align="center",
        padding_y="6px",
        border_bottom=_INS_ROW_BORDER,
        width="100%",
    )


def _ins_dead_row(item: dict) -> rx.Component:
    return rx.grid(
        rx.badge(
            item["kind"],
            variant="soft",
            color_scheme=rx.match(
                item["kind"], ("Tool", "purple"), ("KnowledgeSource", "amber"), ("Variable", "cyan"), "gray"
            ),
            size="1",
        ),
        rx.text(item["name"], font_size="13px", color="var(--gray-12)"),
        rx.text(
            item["schema"],
            font_size="12px",
            color="var(--gray-a8)",
            font_family=_MONO,
            overflow="hidden",
            text_overflow="ellipsis",
            white_space="nowrap",
        ),
        columns="0.8fr 2fr 3fr",
        gap="8px",
        align="center",
        padding_y="6px",
        border_bottom=_INS_ROW_BORDER,
        width="100%",
    )


def _ins_latency_row(item: dict) -> rx.Component:
    return rx.grid(
        rx.text(item["turn"], **_INS_CELL, text_align="right"),
        rx.text(
            item["message"],
            font_size="13px",
            color="var(--gray-12)",
            overflow="hidden",
            text_overflow="ellipsis",
            white_space="nowrap",
        ),
        rx.text(item["total"], **_INS_CELL, text_align="right", font_weight="600"),
        rx.text(item["thinking"], **_INS_CELL, text_align="right"),
        rx.text(item["tools"], **_INS_CELL, text_align="right"),
        rx.text(item["knowledge"], **_INS_CELL, text_align="right"),
        rx.cond(
            item["bottleneck"] != "—",
            rx.badge(item["bottleneck"], color_scheme="amber", variant="soft", size="1"),
            rx.text("—", color="var(--gray-a7)", font_size="12px"),
        ),
        columns="0.4fr 2fr 0.8fr 1.2fr 1.2fr 1.2fr 1.5fr",
        gap="8px",
        align="center",
        padding_y="6px",
        border_bottom=_INS_ROW_BORDER,
        width="100%",
    )


def _ins_deleg_row(item: dict) -> rx.Component:
    return rx.grid(
        rx.text(item["agent"], font_size="13px", color="var(--gray-12)", font_weight="500"),
        rx.badge(item["type"], variant="outline", size="1"),
        rx.badge(
            item["state"],
            color_scheme=rx.match(item["state"], ("completed", "green"), ("failed", "red"), "gray"),
            variant="soft",
            size="1",
        ),
        rx.text(item["duration"], **_INS_CELL, text_align="right"),
        rx.text(
            item["thought"],
            font_size="12px",
            color="var(--gray-a9)",
            overflow="hidden",
            text_overflow="ellipsis",
            white_space="nowrap",
        ),
        columns="1.2fr 0.8fr 0.8fr 0.7fr 3fr",
        gap="8px",
        align="center",
        padding_y="6px",
        border_bottom=_INS_ROW_BORDER,
        width="100%",
    )


def _ins_align_row(item: dict) -> rx.Component:
    return rx.grid(
        rx.text(item["directive"], font_size="13px", color="var(--gray-12)"),
        rx.badge(
            item["type"],
            color_scheme=rx.match(
                item["type"],
                ("language_mismatch", "blue"),
                ("missing_escalation", "amber"),
                ("scope_breach", "red"),
                "gray",
            ),
            variant="soft",
            size="1",
        ),
        rx.text(item["evidence"], font_size="12px", color="var(--gray-a9)"),
        columns="2fr 1.2fr 3fr",
        gap="8px",
        align="center",
        padding_y="6px",
        border_bottom=_INS_ROW_BORDER,
        width="100%",
    )


def _ins_grid_header(*cols: tuple[str, str]) -> rx.Component:
    """Create a grid header row. cols = list of (label, alignment)."""
    children = [rx.text(lbl, **_INS_HEADER_CELL, text_align=align) for lbl, align in cols]
    return rx.box(*children, display="contents")


def _mcs_audit_runner_card() -> rx.Component:
    """LLM Audit Runner — header card on the Quality tab. Mirrors the
    Instruction Lint button on the document-report page so the audit
    feature is reachable from both views.

    Default behaviour (one click) runs the static-config audit;
    everything else is opt-in via the "Audit options" popover."""
    return rx.cond(
        State.can_lint,
        card(
            rx.hstack(
                rx.icon("scan-search", size=18, color="var(--amber-9)"),
                section_heading("LLM Audit Runner"),
                rx.spacer(),
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
                align="center",
                width="100%",
            ),
            rx.text(
                "Run LLM audits over the bot's static configuration and (optionally) "
                "the conversation transcript. The default Instruction Lint runs the "
                "static-config audit only; use Audit options to opt into Sentiment, "
                "PII detection, Answer Accuracy, Topic Routing Quality, and custom "
                "prompts.",
                font_size="11px",
                color="var(--gray-a8)",
                font_style="italic",
                line_height="1.5",
            ),
            rx.cond(
                State.lint_error != "",
                rx.callout(
                    State.lint_error,
                    icon="triangle_alert",
                    color_scheme="red",
                    size="1",
                    margin_top="8px",
                ),
            ),
            rx.cond(
                State.has_lint_report,
                rx.box(
                    rx.hstack(
                        rx.text(
                            "Audit results",
                            font_size="11px",
                            font_weight="700",
                            color="var(--gray-a9)",
                            text_transform="uppercase",
                            letter_spacing="0.04em",
                        ),
                        rx.badge(
                            State.lint_audit_results.length().to(str),  # type: ignore[union-attr]
                            color_scheme="amber",
                            variant="soft",
                            size="1",
                        ),
                        rx.spacer(),
                        rx.button(
                            rx.icon("download", size=12),
                            "Download",
                            variant="ghost",
                            size="1",
                            color_scheme="amber",
                            on_click=State.download_lint_report,
                        ),
                        rx.button(
                            rx.icon("x", size=12),
                            "Clear",
                            variant="ghost",
                            size="1",
                            color_scheme="gray",
                            on_click=State.clear_lint,
                        ),
                        spacing="2",
                        align="center",
                        width="100%",
                        margin_top="12px",
                    ),
                    rx.foreach(State.lint_audit_results, _audit_section_card),
                    width="100%",
                ),
            ),
            width="100%",
        ),
    )


def _mcs_quality_panel() -> rx.Component:
    return rx.vstack(
        # ── LLM Audit Runner (visible when a profile is loaded) ────────────
        _mcs_audit_runner_card(),
        # ── Credits (moved from Credits tab) ───────────────────────────────
        rx.cond(
            State.mcs_credit_rows.length() > 0,  # type: ignore[union-attr]
            rx.vstack(
                _mcs_credits_panel(),
                rx.foreach(State.mcs_current_section_segments, _mcs_segment_block),
                spacing="4",
                width="100%",
            ),
        ),
        # ── Quick Wins (moved from Profile) ────────────────────────────────
        rx.cond(
            State.mcs_profile_quick_wins.length() > 0,  # type: ignore[union-attr]
            card(
                rx.hstack(
                    rx.icon("zap", size=16, color="var(--amber-9)"),
                    section_heading("Quick Wins"),
                    spacing="2",
                    align="center",
                ),
                rx.vstack(
                    rx.foreach(State.mcs_profile_quick_wins, _mcs_profile_quick_win_row),
                    spacing="1",
                    width="100%",
                    padding_top="8px",
                ),
                width="100%",
            ),
        ),
        # ── Response Quality ───────────────────────────────────────────────
        rx.cond(
            State.mcs_ins_quality_kpis.length() > 0,  # type: ignore[union-attr]
            card(
                _ins_card_header(
                    "shield-check",
                    "var(--blue-9)",
                    "Response Quality",
                    "Groundedness and hallucination risk for bot responses.",
                ),
                rx.hstack(
                    rx.foreach(State.mcs_ins_quality_kpis, _ins_kpi),
                    spacing="3",
                    width="100%",
                    overflow_x="auto",
                    padding_y="12px",
                ),
                rx.cond(
                    State.mcs_ins_quality_rows.length() > 0,  # type: ignore[union-attr]
                    rx.box(
                        rx.grid(
                            rx.text("#", **_INS_HEADER_CELL, text_align="right"),
                            rx.text("Risk", **_INS_HEADER_CELL),
                            rx.text("Source", **_INS_HEADER_CELL),
                            rx.text("Flags", **_INS_HEADER_CELL),
                            columns="0.4fr 0.8fr 0.8fr 4fr",
                            gap="8px",
                            padding_y="8px",
                            border_bottom=f"2px solid {SURFACE_BORDER}",
                            width="100%",
                        ),
                        rx.foreach(State.mcs_ins_quality_rows, _ins_quality_row),
                        width="100%",
                    ),
                    rx.text(
                        "All responses appear grounded.", font_size="13px", color="var(--green-11)", padding_top="8px"
                    ),
                ),
                width="100%",
            ),
        ),
        # ── Dead Code Detection ────────────────────────────────────────────
        rx.cond(
            State.mcs_ins_dead_summary != "",
            card(
                _ins_card_header(
                    "trash-2",
                    "var(--red-9)",
                    "Dead Code Detection",
                    "Components with no runtime evidence of being used.",
                ),
                rx.text(
                    State.mcs_ins_dead_summary,
                    font_size="14px",
                    color="var(--gray-12)",
                    font_weight="500",
                    padding_y="8px",
                ),
                rx.cond(
                    State.mcs_ins_dead_rows.length() > 0,  # type: ignore[union-attr]
                    rx.box(
                        rx.grid(
                            rx.text("Kind", **_INS_HEADER_CELL),
                            rx.text("Display Name", **_INS_HEADER_CELL),
                            rx.text("Schema Name", **_INS_HEADER_CELL),
                            columns="0.8fr 2fr 3fr",
                            gap="8px",
                            padding_y="8px",
                            border_bottom=f"2px solid {SURFACE_BORDER}",
                            width="100%",
                        ),
                        rx.foreach(State.mcs_ins_dead_rows, _ins_dead_row),
                        width="100%",
                    ),
                ),
                width="100%",
            ),
        ),
        # ── Instruction Alignment ──────────────────────────────────────────
        rx.cond(
            State.mcs_ins_align_kpis.length() > 0,  # type: ignore[union-attr]
            card(
                _ins_card_header(
                    "scale",
                    "var(--pink-9)",
                    "Instruction Alignment",
                    "Whether the bot's runtime behavior matches its system instructions.",
                ),
                rx.hstack(
                    rx.foreach(State.mcs_ins_align_kpis, _ins_kpi),
                    spacing="3",
                    width="100%",
                    overflow_x="auto",
                    padding_y="12px",
                ),
                rx.cond(
                    State.mcs_ins_align_rows.length() > 0,  # type: ignore[union-attr]
                    rx.box(
                        rx.grid(
                            rx.text("Directive", **_INS_HEADER_CELL),
                            rx.text("Violation", **_INS_HEADER_CELL),
                            rx.text("Evidence", **_INS_HEADER_CELL),
                            columns="2fr 1.2fr 3fr",
                            gap="8px",
                            padding_y="8px",
                            border_bottom=f"2px solid {SURFACE_BORDER}",
                            width="100%",
                        ),
                        rx.foreach(State.mcs_ins_align_rows, _ins_align_row),
                        width="100%",
                    ),
                    rx.text("No violations detected.", font_size="13px", color="var(--green-11)", padding_top="8px"),
                ),
                width="100%",
            ),
        ),
        # ── Empty state ────────────────────────────────────────────────────
        rx.cond(
            ~State.has_mcs_quality,
            rx.center(
                rx.vstack(
                    rx.icon("shield-check", size=48, color="var(--gray-a5)"),
                    rx.text("No quality data available", size="3", color="var(--gray-a7)"),
                    rx.text(
                        "Upload a bot export or transcript to generate quality analysis",
                        size="2",
                        color="var(--gray-a6)",
                    ),
                    align="center",
                    spacing="2",
                    padding="60px 0",
                ),
                width="100%",
            ),
        ),
        spacing="4",
        width="100%",
    )


# ── Main panel ────────────────────────────────────────────────────────────────


def dynamic_analysis_viewer() -> rx.Component:
    return rx.box(
        # Header
        rx.hstack(
            rx.vstack(
                rx.text(
                    "Dynamic Analysis",
                    size="1",
                    font_family=_MONO,
                    color="var(--green-11)",
                    letter_spacing="0.08em",
                    text_transform="uppercase",
                ),
                rx.hstack(
                    rx.heading(
                        State.report_title,
                        size="5",
                        font_family=_MONO,
                        font_weight="600",
                        color="var(--gray-12)",
                        letter_spacing="-0.3px",
                    ),
                    rx.cond(
                        State.mcs_conversation_id != "",
                        rx.hstack(
                            rx.text(
                                "—",
                                size="3",
                                color="var(--gray-a7)",
                                font_family=_MONO,
                            ),
                            rx.code(
                                State.mcs_conversation_id,
                                font_size="12px",
                                color="var(--gray-a10)",
                                font_family=_MONO,
                            ),
                            spacing="2",
                            align="center",
                        ),
                    ),
                    spacing="3",
                    align="center",
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
                    rx.icon("plus", size=14),
                    rx.text("New Analysis"),
                    variant="soft",
                    size="2",
                    color_scheme="green",
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
        rx.separator(),
        # Sub-tab bar
        rx.box(_mcs_section_tab_bar(), padding_top="12px"),
        # Content area
        rx.cond(
            State.has_dynamic_sections,
            rx.box(
                rx.match(
                    State.mcs_analyse_tab,
                    ("profile", _mcs_profile_panel()),
                    ("topics", _mcs_topics_panel()),
                    ("tools", _mcs_tools_panel()),
                    ("knowledge", _mcs_knowledge_panel()),
                    ("routing", _mcs_routing_panel()),
                    (
                        "conversation",
                        rx.vstack(
                            rx.cond(State.has_mcs_conv_visual_summary, _mcs_conversation_visual_dashboard()),
                            rx.cond(State.has_mcs_conversation_flow, _mcs_conversation_flow_panel()),
                            _mcs_conversation_detail_panel(),
                            # Turn Efficiency (moved from Insights)
                            rx.cond(
                                State.mcs_ins_turn_kpis.length() > 0,  # type: ignore[union-attr]
                                card(
                                    _ins_card_header(
                                        "gauge",
                                        PRIMARY,
                                        "Turn Efficiency",
                                        "How efficiently the orchestrator resolves each user turn.",
                                    ),
                                    rx.hstack(
                                        rx.foreach(State.mcs_ins_turn_kpis, _ins_kpi),
                                        spacing="3",
                                        width="100%",
                                        overflow_x="auto",
                                        padding_y="12px",
                                    ),
                                    rx.cond(
                                        State.mcs_ins_turn_rows.length() > 0,  # type: ignore[union-attr]
                                        rx.box(
                                            rx.grid(
                                                rx.text("#", **_INS_HEADER_CELL, text_align="right"),
                                                rx.text("User Message", **_INS_HEADER_CELL),
                                                rx.text("Plans", **_INS_HEADER_CELL, text_align="right"),
                                                rx.text("Tools", **_INS_HEADER_CELL, text_align="right"),
                                                rx.text("Search", **_INS_HEADER_CELL, text_align="right"),
                                                rx.text("Thinking", **_INS_HEADER_CELL, text_align="right"),
                                                rx.text("Total", **_INS_HEADER_CELL, text_align="right"),
                                                rx.text("Flags", **_INS_HEADER_CELL),
                                                columns="0.4fr 2.5fr 0.5fr 0.5fr 0.6fr 0.8fr 0.8fr 2fr",
                                                gap="8px",
                                                padding_y="8px",
                                                border_bottom=f"2px solid {SURFACE_BORDER}",
                                                width="100%",
                                            ),
                                            rx.foreach(State.mcs_ins_turn_rows, _ins_turn_row),
                                            width="100%",
                                            overflow_x="auto",
                                        ),
                                    ),
                                    width="100%",
                                ),
                            ),
                            # Latency Bottlenecks (moved from Insights)
                            rx.cond(
                                State.mcs_ins_latency_kpis.length() > 0,  # type: ignore[union-attr]
                                card(
                                    _ins_card_header(
                                        "timer",
                                        "var(--orange-9)",
                                        "Latency Bottlenecks",
                                        "Where time is spent per turn — thinking, tools, knowledge, or delivery.",
                                    ),
                                    rx.hstack(
                                        rx.foreach(State.mcs_ins_latency_kpis, _ins_kpi),
                                        spacing="3",
                                        width="100%",
                                        overflow_x="auto",
                                        padding_y="12px",
                                    ),
                                    rx.box(
                                        rx.grid(
                                            rx.text("#", **_INS_HEADER_CELL, text_align="right"),
                                            rx.text("Message", **_INS_HEADER_CELL),
                                            rx.text("Total", **_INS_HEADER_CELL, text_align="right"),
                                            rx.text("Thinking", **_INS_HEADER_CELL, text_align="right"),
                                            rx.text("Tools", **_INS_HEADER_CELL, text_align="right"),
                                            rx.text("Knowledge", **_INS_HEADER_CELL, text_align="right"),
                                            rx.text("Bottleneck", **_INS_HEADER_CELL),
                                            columns="0.4fr 2fr 0.8fr 1.2fr 1.2fr 1.2fr 1.5fr",
                                            gap="8px",
                                            padding_y="8px",
                                            border_bottom=f"2px solid {SURFACE_BORDER}",
                                            width="100%",
                                        ),
                                        rx.foreach(State.mcs_ins_latency_rows, _ins_latency_row),
                                        width="100%",
                                        overflow_x="auto",
                                    ),
                                    rx.cond(
                                        State.mcs_ins_latency_mermaid != "",
                                        rx.box(
                                            rx.el.pre(State.mcs_ins_latency_mermaid, class_name="mermaid"),
                                            width="100%",
                                            overflow_x="auto",
                                            padding="22px",
                                            background="var(--green-a2)",
                                            border="1px solid var(--green-a4)",
                                            border_radius="14px",
                                            margin_top="12px",
                                        ),
                                    ),
                                    width="100%",
                                ),
                            ),
                            spacing="4",
                            width="100%",
                        ),
                    ),
                    ("quality", _mcs_quality_panel()),
                    rx.box(),  # fallback
                ),
                padding_top="20px",
            ),
            # Empty state
            rx.center(
                rx.vstack(
                    rx.icon("scan-search", size=48, color="var(--gray-a5)"),
                    rx.text("No analysis loaded", size="3", color="var(--gray-a7)"),
                    rx.text("Upload a bot export or transcript to begin", size="2", color="var(--gray-a6)"),
                    align="center",
                    spacing="2",
                    padding="60px 0",
                ),
                width="100%",
            ),
        ),
        id="dynamic-content",
        max_width="1400px",
        width="100%",
        padding="28px 32px",
        margin="0 auto",
    )
