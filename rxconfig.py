import os

import reflex as rx

_port = int(os.environ.get("PORT", "2009"))
_api_url = os.environ.get("API_URL")

config = rx.Config(
    app_name="web",
    frontend_port=_port,
    backend_port=_port,
    **{"api_url": _api_url} if _api_url else {},
)
