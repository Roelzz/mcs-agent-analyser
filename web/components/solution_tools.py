import reflex as rx

from web.components.common import _MONO
from web.mermaid import render_segment
from web.state import State

SOL_UPLOAD_ID = "sol_upload"


def _severity_badge(severity: str) -> rx.Component:
    return rx.badge(
        severity,
        color_scheme=rx.match(
            severity,
            ("pass", "green"),
            ("warning", "amber"),
            ("fail", "red"),
            ("info", "blue"),
            "gray",
        ),
        variant="soft",
        size="1",
    )


def _check_result_row(result: dict) -> rx.Component:
    return rx.box(
        rx.hstack(
            _severity_badge(result["severity"]),
            rx.badge(result["category"], color_scheme="gray", variant="outline", size="1"),
            rx.text(result["title"], size="2", font_weight="500", color="var(--gray-12)", flex="1"),
            width="100%",
            align="center",
            spacing="2",
        ),
        rx.text(result["detail"], size="1", color="var(--gray-a9)", padding_top="4px", padding_left="80px"),
        padding="10px 12px",
        border_bottom="1px solid var(--gray-a3)",
        _hover={"background": "var(--gray-a2)"},
    )


def _validate_result_row(result: dict) -> rx.Component:
    return rx.box(
        rx.hstack(
            _severity_badge(result["severity"]),
            rx.text(result["title"], size="2", font_weight="500", color="var(--gray-12)", flex="1"),
            width="100%",
            align="center",
            spacing="2",
        ),
        rx.text(result["detail"], size="1", color="var(--gray-a9)", padding_top="4px", padding_left="60px"),
        padding="10px 12px",
        border_bottom="1px solid var(--gray-a3)",
        _hover={"background": "var(--gray-a2)"},
    )


def _tab_button(label: str, tab_key: str) -> rx.Component:
    return rx.button(
        label,
        variant=rx.cond(State.sol_active_tab == tab_key, "solid", "outline"),
        color_scheme="green",
        size="2",
        on_click=State.set_sol_active_tab(tab_key),
        cursor="pointer",
    )


def _sol_check_tab() -> rx.Component:
    return rx.vstack(
        rx.cond(
            State.sol_check_error != "",
            rx.vstack(
                rx.callout(State.sol_check_error, icon="triangle_alert", color_scheme="red", size="1", width="100%"),
                rx.button(
                    rx.hstack(rx.icon("rotate-ccw", size=14), rx.text("Retry"), align="center", spacing="2"),
                    on_click=State.run_solution_check,
                    size="2",
                    variant="outline",
                    color_scheme="red",
                    cursor="pointer",
                ),
                spacing="2",
                width="100%",
            ),
        ),
        rx.cond(
            State.sol_is_checking,
            rx.center(
                rx.hstack(
                    rx.spinner(size="2"),
                    rx.text("Running checks...", size="2", color="var(--gray-a9)"),
                    spacing="2",
                    align="center",
                ),
                padding="24px",
                width="100%",
            ),
            rx.vstack(
                rx.cond(
                    State.sol_check_agent_name != "",
                    rx.hstack(
                        rx.icon("bot", size=16, color="var(--green-9)"),
                        rx.text(
                            State.sol_check_agent_name,
                            size="3",
                            font_weight="600",
                            color="var(--gray-12)",
                            font_family=_MONO,
                        ),
                        rx.text(" / ", size="2", color="var(--gray-a8)"),
                        rx.text(State.sol_check_solution_name, size="2", color="var(--gray-a9)", font_family=_MONO),
                        align="center",
                        spacing="2",
                    ),
                ),
                rx.hstack(
                    rx.badge(
                        rx.hstack(
                            rx.icon("check-circle", size=12), rx.text(State.sol_check_pass), spacing="1", align="center"
                        ),
                        color_scheme="green",
                        variant="soft",
                        size="2",
                    ),
                    rx.badge(
                        rx.hstack(
                            rx.icon("alert-triangle", size=12),
                            rx.text(State.sol_check_warn),
                            spacing="1",
                            align="center",
                        ),
                        color_scheme="amber",
                        variant="soft",
                        size="2",
                    ),
                    rx.badge(
                        rx.hstack(
                            rx.icon("x-circle", size=12), rx.text(State.sol_check_fail), spacing="1", align="center"
                        ),
                        color_scheme="red",
                        variant="soft",
                        size="2",
                    ),
                    rx.badge(
                        rx.hstack(rx.icon("info", size=12), rx.text(State.sol_check_info), spacing="1", align="center"),
                        color_scheme="blue",
                        variant="soft",
                        size="2",
                    ),
                    spacing="2",
                    align="center",
                ),
                rx.hstack(
                    rx.button(
                        "All",
                        variant=rx.cond(State.sol_check_active_category == "All", "solid", "outline"),
                        color_scheme="gray",
                        size="1",
                        on_click=State.set_sol_check_active_category("All"),
                        cursor="pointer",
                    ),
                    rx.button(
                        "Solution",
                        variant=rx.cond(State.sol_check_active_category == "Solution", "solid", "outline"),
                        color_scheme="gray",
                        size="1",
                        on_click=State.set_sol_check_active_category("Solution"),
                        cursor="pointer",
                    ),
                    rx.button(
                        "Agent",
                        variant=rx.cond(State.sol_check_active_category == "Agent", "solid", "outline"),
                        color_scheme="gray",
                        size="1",
                        on_click=State.set_sol_check_active_category("Agent"),
                        cursor="pointer",
                    ),
                    rx.button(
                        "Topics",
                        variant=rx.cond(State.sol_check_active_category == "Topics", "solid", "outline"),
                        color_scheme="gray",
                        size="1",
                        on_click=State.set_sol_check_active_category("Topics"),
                        cursor="pointer",
                    ),
                    rx.button(
                        "Knowledge",
                        variant=rx.cond(State.sol_check_active_category == "Knowledge", "solid", "outline"),
                        color_scheme="gray",
                        size="1",
                        on_click=State.set_sol_check_active_category("Knowledge"),
                        cursor="pointer",
                    ),
                    rx.button(
                        "Security",
                        variant=rx.cond(State.sol_check_active_category == "Security", "solid", "outline"),
                        color_scheme="gray",
                        size="1",
                        on_click=State.set_sol_check_active_category("Security"),
                        cursor="pointer",
                    ),
                    spacing="2",
                    flex_wrap="wrap",
                ),
                rx.box(
                    rx.foreach(State.sol_filtered_results, _check_result_row),
                    width="100%",
                    border="1px solid var(--gray-a4)",
                    border_radius="8px",
                    overflow="hidden",
                ),
                spacing="4",
                width="100%",
            ),
        ),
        spacing="4",
        width="100%",
    )


def _sol_validate_tab() -> rx.Component:
    return rx.vstack(
        rx.cond(
            State.sol_validate_error != "",
            rx.vstack(
                rx.callout(State.sol_validate_error, icon="triangle_alert", color_scheme="red", size="1", width="100%"),
                rx.button(
                    rx.hstack(rx.icon("rotate-ccw", size=14), rx.text("Retry"), align="center", spacing="2"),
                    on_click=State.run_solution_validate,
                    size="2",
                    variant="outline",
                    color_scheme="red",
                    cursor="pointer",
                ),
                spacing="2",
                width="100%",
            ),
        ),
        rx.cond(
            State.sol_is_validating,
            rx.center(
                rx.hstack(
                    rx.spinner(size="2"),
                    rx.text("Validating instructions...", size="2", color="var(--gray-a9)"),
                    spacing="2",
                    align="center",
                ),
                padding="24px",
                width="100%",
            ),
            rx.vstack(
                rx.cond(
                    State.sol_validate_model_display != "",
                    rx.hstack(
                        rx.icon("cpu", size=16, color="var(--green-9)"),
                        rx.text("Model: ", size="2", color="var(--gray-a9)"),
                        rx.text(
                            State.sol_validate_model_display,
                            size="2",
                            font_weight="600",
                            color="var(--gray-12)",
                            font_family=_MONO,
                        ),
                        align="center",
                        spacing="2",
                    ),
                ),
                rx.box(
                    rx.foreach(State.sol_validate_results, _validate_result_row),
                    width="100%",
                    border="1px solid var(--gray-a4)",
                    border_radius="8px",
                    overflow="hidden",
                ),
                rx.cond(
                    State.sol_validate_best_practices_md != "",
                    rx.box(
                        rx.heading(
                            "Best Practices", size="3", font_family=_MONO, color="var(--gray-12)", padding_bottom="8px"
                        ),
                        rx.foreach(State.sol_validate_bp_segments, render_segment),
                        padding_top="16px",
                    ),
                ),
                spacing="4",
                width="100%",
            ),
        ),
        spacing="4",
        width="100%",
    )


def _sol_deps_tab() -> rx.Component:
    return rx.vstack(
        rx.cond(
            State.sol_deps_error != "",
            rx.vstack(
                rx.callout(State.sol_deps_error, icon="triangle_alert", color_scheme="red", size="1", width="100%"),
                rx.button(
                    rx.hstack(rx.icon("rotate-ccw", size=14), rx.text("Retry"), align="center", spacing="2"),
                    on_click=State.run_deps_analysis,
                    size="2",
                    variant="outline",
                    color_scheme="red",
                    cursor="pointer",
                ),
                spacing="2",
                width="100%",
            ),
        ),
        rx.cond(
            State.sol_is_deps_analyzing,
            rx.center(
                rx.hstack(
                    rx.spinner(size="2"),
                    rx.text("Analysing dependencies...", size="2", color="var(--gray-a9)"),
                    spacing="2",
                    align="center",
                ),
                padding="24px",
                width="100%",
            ),
            rx.box(rx.foreach(State.sol_deps_segments, render_segment), width="100%"),
        ),
        spacing="4",
        width="100%",
    )


def _sol_rename_tab() -> rx.Component:
    return rx.vstack(
        rx.cond(
            State.sol_detected_info.length() > 0,  # type: ignore
            rx.callout(
                rx.vstack(
                    rx.text("Detected from solution:", size="2", font_weight="500"),
                    rx.text(
                        rx.text.strong("Agent: "),
                        State.sol_detected_info["bot_display_name"],
                        size="1",
                        color="var(--gray-a9)",
                    ),
                    rx.text(
                        rx.text.strong("Solution: "),
                        State.sol_detected_info["solution_unique_name"],
                        size="1",
                        color="var(--gray-a9)",
                    ),
                    spacing="1",
                ),
                icon="info",
                color_scheme="blue",
                size="1",
                width="100%",
            ),
        ),
        rx.vstack(
            rx.text("New Agent Name", size="2", font_weight="500", color="var(--gray-11)"),
            rx.input(
                placeholder="My Renamed Agent",
                value=State.sol_rename_new_agent,
                on_change=State.set_sol_rename_new_agent,
                width="100%",
                size="2",
                font_family=_MONO,
            ),
            rx.text("Display name for the agent", size="1", color="var(--gray-a8)"),
            spacing="1",
            width="100%",
        ),
        rx.vstack(
            rx.text("New Solution Name", size="2", font_weight="500", color="var(--gray-11)"),
            rx.input(
                placeholder="MyRenamedSolution",
                value=State.sol_rename_new_solution,
                on_change=State.set_sol_rename_new_solution,
                width="100%",
                size="2",
                font_family=_MONO,
            ),
            rx.text("PascalCase, letters/digits/underscores only (e.g. MyNewBot)", size="1", color="var(--gray-a8)"),
            spacing="1",
            width="100%",
        ),
        rx.cond(
            State.sol_rename_error != "",
            rx.vstack(
                rx.callout(State.sol_rename_error, icon="triangle_alert", color_scheme="red", size="1", width="100%"),
                rx.button(
                    rx.hstack(rx.icon("rotate-ccw", size=14), rx.text("Retry"), align="center", spacing="2"),
                    on_click=State.run_rename,
                    size="2",
                    variant="outline",
                    color_scheme="red",
                    cursor="pointer",
                ),
                spacing="2",
                width="100%",
            ),
        ),
        rx.button(
            rx.cond(
                State.sol_is_renaming,
                rx.hstack(rx.spinner(size="1"), rx.text("Renaming..."), align="center", spacing="2"),
                rx.hstack(rx.icon("pen-line", size=15), rx.text("Rename Solution"), align="center", spacing="2"),
            ),
            on_click=State.run_rename,
            width="100%",
            size="3",
            color_scheme="green",
            disabled=State.sol_is_renaming,
            cursor="pointer",
            font_weight="500",
        ),
        rx.cond(
            State.sol_rename_result.length() > 0,  # type: ignore
            rx.vstack(
                rx.callout(
                    rx.vstack(
                        rx.text("Rename complete!", size="2", font_weight="600", color="var(--green-11)"),
                        rx.text(
                            rx.text.strong("Agent: "),
                            State.sol_rename_result["old_agent_name"],
                            " -> ",
                            State.sol_rename_result["new_agent_name"],
                            size="1",
                        ),
                        rx.text(
                            rx.text.strong("Solution: "),
                            State.sol_rename_result["old_solution_name"],
                            " -> ",
                            State.sol_rename_result["new_solution_name"],
                            size="1",
                        ),
                        rx.text(
                            rx.text.strong("Files modified: "),
                            State.sol_rename_result["files_modified"].to(str),
                            " | Folders renamed: ",
                            State.sol_rename_result["folders_renamed"].to(str),
                            size="1",
                        ),
                        spacing="1",
                    ),
                    icon="check-circle",
                    color_scheme="green",
                    size="1",
                    width="100%",
                ),
                rx.button(
                    rx.hstack(
                        rx.icon("download", size=15), rx.text("Download Renamed ZIP"), align="center", spacing="2"
                    ),
                    on_click=State.download_renamed_zip,
                    width="100%",
                    size="3",
                    color_scheme="green",
                    variant="outline",
                    cursor="pointer",
                    font_weight="500",
                ),
                spacing="3",
                width="100%",
            ),
        ),
        spacing="4",
        width="100%",
    )


def solution_tools_form() -> rx.Component:
    return rx.center(
        rx.vstack(
            rx.vstack(
                rx.heading(
                    "Solution Tools",
                    size="7",
                    font_family=_MONO,
                    font_weight="600",
                    color="var(--gray-12)",
                    letter_spacing="-0.5px",
                ),
                rx.text(
                    "Check, validate, analyse dependencies, or rename a Power Platform solution ZIP",
                    size="2",
                    color="var(--gray-a9)",
                    text_align="center",
                ),
                spacing="2",
                align="center",
            ),
            rx.box(
                rx.vstack(
                    rx.cond(
                        State.sol_has_zip,
                        rx.hstack(
                            rx.icon("file-archive", size=16, color="var(--green-9)"),
                            rx.text(State.sol_zip_name, size="2", font_family=_MONO, color="var(--gray-11)", flex="1"),
                            rx.button(
                                rx.icon("x", size=14),
                                variant="ghost",
                                size="1",
                                color_scheme="gray",
                                on_click=State.sol_clear,
                                cursor="pointer",
                            ),
                            width="100%",
                            align="center",
                            padding="8px 12px",
                            background="var(--green-a2)",
                            border="1px solid var(--green-a5)",
                            border_radius="8px",
                        ),
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
                                        "Drop a solution ZIP or click to browse",
                                        size="3",
                                        color="var(--gray-11)",
                                        font_weight="500",
                                    ),
                                    rx.text("Power Platform solution export (.zip)", size="2", color="var(--gray-a8)"),
                                    align="center",
                                    spacing="3",
                                ),
                                id=SOL_UPLOAD_ID,
                                border="1.5px dashed var(--green-a6)",
                                border_radius="12px",
                                padding="48px 32px",
                                width="100%",
                                cursor="pointer",
                                multiple=False,
                                accept={".zip": ["application/zip"]},
                                background="var(--green-a1)",
                                transition="all 0.15s ease",
                            ),
                            rx.button(
                                rx.hstack(
                                    rx.icon("zap", size=15), rx.text("Upload & Analyse"), align="center", spacing="2"
                                ),
                                on_click=State.handle_solution_upload(rx.upload_files(upload_id=SOL_UPLOAD_ID)),
                                width="100%",
                                size="3",
                                color_scheme="green",
                                cursor="pointer",
                                font_weight="500",
                            ),
                            spacing="4",
                            width="100%",
                        ),
                    ),
                    rx.cond(
                        State.sol_has_zip,
                        rx.vstack(
                            rx.separator(size="4"),
                            rx.hstack(
                                _tab_button("Check", "check"),
                                _tab_button("Validate", "validate"),
                                _tab_button("Dependencies", "deps"),
                                _tab_button("Rename", "rename"),
                                spacing="2",
                                flex_wrap="wrap",
                            ),
                            rx.match(
                                State.sol_active_tab,
                                ("check", _sol_check_tab()),
                                ("validate", _sol_validate_tab()),
                                ("deps", _sol_deps_tab()),
                                ("rename", _sol_rename_tab()),
                                _sol_check_tab(),
                            ),
                            spacing="4",
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
