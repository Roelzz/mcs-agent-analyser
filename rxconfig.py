import os

import reflex as rx

_port = int(os.environ.get("PORT", "2009"))

config = rx.Config(
    app_name="web",
    frontend_port=_port,
    backend_port=_port,
)
