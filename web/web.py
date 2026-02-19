import reflex as rx

from web.components import login_form, navbar, report_viewer, upload_form
from web.mermaid import mermaid_script
from web.state import State


def login_page() -> rx.Component:
    return rx.center(
        login_form(),
        height="100vh",
    )


def upload_page() -> rx.Component:
    return rx.vstack(
        navbar(),
        mermaid_script(),
        rx.cond(
            State.has_report,
            report_viewer(),
            upload_form(),
        ),
        width="100%",
        min_height="100vh",
        spacing="0",
    )


app = rx.App(theme=rx.theme(appearance="light", accent_color="blue", radius="medium"))
app.add_page(login_page, route="/", on_load=State.check_already_authed)
app.add_page(upload_page, route="/upload", on_load=State.check_auth)
