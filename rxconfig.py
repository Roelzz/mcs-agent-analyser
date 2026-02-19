import os

import reflex as rx

_api_url = os.environ.get("API_URL")

config = rx.Config(
    app_name="web",
    frontend_port=int(os.environ.get("FRONTEND_PORT", "2009")),
    backend_port=int(os.environ.get("BACKEND_PORT", "8000")),
    **{"api_url": _api_url} if _api_url else {},
)
