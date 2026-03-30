import reflex as rx

from web.components import (
    batch_form,
    compare_form,
    dashboard_cards,
    import_form,
    login_form,
    navbar,
    report_viewer,
    rules_editor,
    solution_tools_form,
    upload_form,
)
from web.components.dynamic_analysis import dynamic_analysis_viewer
from web.mermaid import json_tree_script, mermaid_script
from web.state import State

_BODY_FONT = "Outfit, sans-serif"
_MONO_FONT = "JetBrains Mono, monospace"


def login_page() -> rx.Component:
    return rx.box(
        # Dot-grid texture
        rx.box(
            position="fixed",
            top="0",
            left="0",
            right="0",
            bottom="0",
            background_image=rx.color_mode_cond(
                "radial-gradient(rgba(34, 197, 94, 0.12) 1px, transparent 1px)",
                "radial-gradient(rgba(34, 197, 94, 0.07) 1px, transparent 1px)",
            ),
            background_size="28px 28px",
            pointer_events="none",
            z_index="0",
        ),
        # Central radial glow
        rx.box(
            position="fixed",
            top="50%",
            left="50%",
            transform="translate(-50%, -50%)",
            width="700px",
            height="700px",
            background=rx.color_mode_cond(
                "radial-gradient(circle, rgba(34, 197, 94, 0.08) 0%, transparent 65%)",
                "radial-gradient(circle, rgba(34, 197, 94, 0.06) 0%, transparent 65%)",
            ),
            pointer_events="none",
            z_index="0",
        ),
        rx.center(
            login_form(),
            height="100vh",
            position="relative",
            z_index="1",
        ),
        position="relative",
        min_height="100vh",
    )


def _counter_styles() -> rx.Component:
    return rx.el.style(
        """
        @keyframes counter-pop {
            0% { transform: scale(1); }
            50% { transform: scale(1.4); color: var(--amber-9); }
            100% { transform: scale(1); }
        }
        @keyframes milestone-flash {
            0% { opacity: 1; transform: translateY(0); }
            70% { opacity: 1; transform: translateY(-4px); }
            100% { opacity: 0; transform: translateY(-8px); }
        }
        .counter-pop {
            animation: counter-pop 0.4s ease-out;
        }
        .milestone-flash {
            animation: milestone-flash 2s ease-out forwards;
        }
        """
    )


def dashboard_page() -> rx.Component:
    return rx.vstack(
        navbar(),
        _counter_styles(),
        dashboard_cards(),
        width="100%",
        min_height="100vh",
        spacing="0",
    )


def upload_page() -> rx.Component:
    return rx.vstack(
        navbar(),
        mermaid_script(),
        _counter_styles(),
        upload_form(),
        width="100%",
        min_height="100vh",
        spacing="0",
    )


app = rx.App(
    theme=rx.theme(
        appearance="inherit",
        accent_color="green",
        radius="medium",
        scaling="100%",
    ),
    stylesheets=[
        "https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&family=Outfit:wght@300;400;500;600&display=swap",
    ],
    style={
        "font_family": _BODY_FONT,
    },
)


def import_page() -> rx.Component:
    return rx.vstack(
        navbar(),
        mermaid_script(),
        _counter_styles(),
        import_form(),
        width="100%",
        min_height="100vh",
        spacing="0",
    )


def dynamic_analysis_page() -> rx.Component:
    return rx.vstack(
        navbar(),
        mermaid_script(),
        json_tree_script(),
        _counter_styles(),
        dynamic_analysis_viewer(),
        width="100%",
        min_height="100vh",
        spacing="0",
    )


def document_analysis_page() -> rx.Component:
    return rx.vstack(
        navbar(),
        mermaid_script(),
        _counter_styles(),
        report_viewer(),
        width="100%",
        min_height="100vh",
        spacing="0",
    )


def tools_page() -> rx.Component:
    return rx.vstack(
        navbar(),
        mermaid_script(),
        _counter_styles(),
        solution_tools_form(),
        width="100%",
        min_height="100vh",
        spacing="0",
    )


def rules_page() -> rx.Component:
    return rx.vstack(
        navbar(),
        mermaid_script(),
        _counter_styles(),
        rules_editor(),
        width="100%",
        min_height="100vh",
        spacing="0",
    )


def compare_page() -> rx.Component:
    return rx.vstack(
        navbar(),
        mermaid_script(),
        _counter_styles(),
        compare_form(),
        width="100%",
        min_height="100vh",
        spacing="0",
    )


def batch_page() -> rx.Component:
    return rx.vstack(
        navbar(),
        mermaid_script(),
        _counter_styles(),
        batch_form(),
        width="100%",
        min_height="100vh",
        spacing="0",
    )


app.add_page(login_page, route="/", on_load=State.check_already_authed)
app.add_page(dashboard_page, route="/dashboard", on_load=State.check_auth)
app.add_page(upload_page, route="/upload", on_load=State.check_auth)
app.add_page(import_page, route="/import", on_load=State.init_import_page)
app.add_page(dynamic_analysis_page, route="/analysis/dynamic", on_load=State.check_analysis_page)
app.add_page(document_analysis_page, route="/analysis/document", on_load=State.check_analysis_page)
app.add_page(tools_page, route="/tools", on_load=State.check_auth)
app.add_page(rules_page, route="/rules", on_load=State.on_load_rules_page)
app.add_page(compare_page, route="/compare", on_load=State.check_auth)
app.add_page(batch_page, route="/batch", on_load=State.check_auth)
