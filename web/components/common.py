import reflex as rx

from web.state import State

UPLOAD_ID = "file_upload"
_MONO = "JetBrains Mono, monospace"
_BODY = "Outfit, sans-serif"


def login_form() -> rx.Component:
    return rx.card(
        rx.form(
            rx.vstack(
                # Icon badge
                rx.box(
                    rx.icon("scan-search", size=24, color="var(--green-9)"),
                    padding="12px",
                    background="var(--green-a3)",
                    border_radius="10px",
                    border="1px solid var(--green-a5)",
                    display="inline-flex",
                    align_self="center",
                ),
                rx.vstack(
                    rx.heading(
                        "Agent Analyser",
                        size="6",
                        font_family=_MONO,
                        font_weight="600",
                        letter_spacing="-0.5px",
                        color="var(--gray-12)",
                    ),
                    rx.text(
                        "Copilot Studio Intelligence",
                        size="2",
                        color="var(--gray-a9)",
                        font_family=_BODY,
                    ),
                    spacing="1",
                    align="center",
                    width="100%",
                ),
                rx.separator(size="4"),
                rx.input(
                    placeholder="Username",
                    value=State.username,
                    on_change=State.set_username,
                    width="100%",
                    size="3",
                ),
                rx.input(
                    placeholder="Password",
                    type="password",
                    value=State.password,
                    on_change=State.set_password,
                    width="100%",
                    size="3",
                ),
                rx.cond(
                    State.auth_error != "",
                    rx.callout(
                        State.auth_error,
                        icon="triangle_alert",
                        color_scheme="red",
                        size="1",
                        width="100%",
                    ),
                ),
                rx.button(
                    "Sign In",
                    type="submit",
                    width="100%",
                    size="3",
                    color_scheme="green",
                    font_weight="500",
                    cursor="pointer",
                ),
                spacing="4",
                width="100%",
                align="center",
            ),
            on_submit=lambda _: State.login(),
            reset_on_submit=False,
        ),
        # Community counter badge — shared with GitHub README
        rx.image(
            src="https://komarev.com/ghpvc/?username=Roelzz&label=Community%20Views&color=0e75b6&style=flat",
            alt="Community Views",
            height="20px",
            margin_top="12px",
            opacity="0.6",
        ),
        width="380px",
        padding="32px",
        background="var(--gray-a2)",
        border="1px solid var(--gray-a4)",
        box_shadow=rx.color_mode_cond(
            "0 0 0 1px rgba(34,197,94,0.15), 0 8px 24px rgba(0,0,0,0.1)",
            "0 0 0 1px var(--green-a3), 0 24px 48px rgba(0,0,0,0.5)",
        ),
        border_radius="16px",
    )


def _nav_link(icon_name: str, label: str, href: str) -> rx.Component:
    is_active = State.router.page.path == href
    return rx.link(
        rx.hstack(
            rx.icon(icon_name, size=14, color=rx.cond(is_active, "var(--green-9)", "var(--gray-a9)")),
            rx.text(
                label,
                size="2",
                color=rx.cond(is_active, "var(--green-11)", "var(--gray-a9)"),
                font_weight=rx.cond(is_active, "500", "400"),
            ),
            spacing="1",
            align="center",
        ),
        href=href,
        underline="none",
    )


def navbar() -> rx.Component:
    return rx.hstack(
        # Logo
        rx.link(
            rx.hstack(
                rx.icon("scan-search", size=17, color="var(--green-9)"),
                rx.text(
                    "Agent Analyser",
                    size="3",
                    font_family=_MONO,
                    font_weight="600",
                    color="var(--gray-12)",
                    letter_spacing="-0.3px",
                ),
                align="center",
                spacing="2",
            ),
            href="/dashboard",
            underline="none",
        ),
        # Nav links
        rx.hstack(
            _nav_link("layout-dashboard", "Dashboard", "/dashboard"),
            _nav_link("upload", "Upload", "/upload"),
            _nav_link("database", "Dataverse", "/import"),
            _nav_link("wrench", "Solution Tools", "/tools"),
            _nav_link("shield-check", "Rules", "/rules"),
            _nav_link("bar-chart-3", "Batch", "/batch"),
            rx.cond(
                State.has_report,
                rx.fragment(
                    _nav_link("activity", "Dynamic", "/analysis/dynamic"),
                    _nav_link("file-text", "Document", "/analysis/document"),
                ),
            ),
            spacing="4",
            align="center",
        ),
        # Counter badge
        rx.hstack(
            rx.text(State.cat_emoji, font_size="18px"),
            rx.text(
                State.analyses_count,
                font_family=_MONO,
                font_weight="600",
                color="var(--amber-11)",
                class_name=rx.cond(State.counter_animating, "counter-pop", ""),
            ),
            rx.text(
                State.cat_title,
                size="1",
                color="var(--gray-a8)",
                font_family=_BODY,
            ),
            rx.cond(
                State.milestone_reached,
                rx.text(
                    "\U0001f389 NEW RANK!",
                    size="1",
                    color="var(--amber-9)",
                    font_weight="600",
                    class_name="milestone-flash",
                ),
            ),
            align="center",
            spacing="2",
            padding="4px 12px",
            background="var(--amber-a2)",
            border="1px solid var(--amber-a4)",
            border_radius="20px",
        ),
        rx.spacer(),
        # Right side
        rx.hstack(
            rx.box(
                rx.text(
                    State.username,
                    size="1",
                    color="var(--green-11)",
                    font_family=_MONO,
                ),
                padding="4px 10px",
                background="var(--green-a3)",
                border="1px solid var(--green-a5)",
                border_radius="20px",
            ),
            rx.color_mode.button(size="2", variant="ghost", color_scheme="gray"),
            rx.button(
                "Logout",
                variant="ghost",
                size="2",
                color_scheme="gray",
                on_click=State.logout,
                cursor="pointer",
            ),
            align="center",
            spacing="3",
        ),
        width="100%",
        padding="13px 28px",
        border_bottom="1px solid var(--gray-a4)",
        background=rx.color_mode_cond(
            "rgba(255, 255, 255, 0.75)",  # light
            "rgba(12, 14, 20, 0.75)",  # dark
        ),
        backdrop_filter="blur(12px)",
        align="center",
        position="sticky",
        top="0",
        z_index="100",
    )


def _dashboard_card(icon_name: str, title: str, description: str, href: str) -> rx.Component:
    return rx.link(
        rx.vstack(
            rx.box(
                rx.icon(icon_name, size=24, color="var(--green-9)"),
                padding="12px",
                background="var(--green-a3)",
                border_radius="10px",
                border="1px solid var(--green-a5)",
                display="inline-flex",
            ),
            rx.text(title, size="4", font_weight="500", color="var(--gray-12)"),
            rx.text(description, size="2", color="var(--gray-a9)", line_height="1.5"),
            spacing="3",
            padding="24px",
            background="var(--gray-a2)",
            border="1px solid var(--gray-a4)",
            border_radius="16px",
            width="280px",
            min_height="180px",
            _hover={
                "border_color": "var(--green-a6)",
                "background": "var(--gray-a3)",
            },
            transition="all 0.15s ease",
        ),
        href=href,
        underline="none",
    )


def dashboard_cards() -> rx.Component:
    return rx.center(
        rx.hstack(
            _dashboard_card(
                "upload",
                "Upload & Analyse",
                "Upload a bot export (.zip) or paste a conversation transcript (.json)",
                "/upload",
            ),
            _dashboard_card(
                "database",
                "Dataverse Import",
                "Connect to Dataverse and fetch transcripts live from your environment",
                "/import",
            ),
            _dashboard_card(
                "wrench",
                "Solution Tools",
                "Check, validate, rename, and inspect solution exports",
                "/tools",
            ),
            _dashboard_card(
                "bar-chart-3",
                "Batch Analytics",
                "Upload multiple transcripts to see aggregate patterns",
                "/batch",
            ),
            spacing="5",
            flex_wrap="wrap",
            justify="center",
        ),
        width="100%",
        padding_top="80px",
        padding_x="24px",
    )
