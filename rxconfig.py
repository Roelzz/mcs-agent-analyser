import os

import reflex as rx

config = rx.Config(
    app_name="web",
    frontend_port=int(os.environ.get("FRONTEND_PORT", "2009")),
    backend_port=int(os.environ.get("BACKEND_PORT", "8000")),
)
