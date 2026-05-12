"""Reflex compile-time smoke test.

`pytest tests/test_web.py` passes a smoke-import of every state class, but
Reflex evaluates `rx.foreach` lambdas only at compile time — so concatenations
like `"prefix " + item["key"]` or nested `foreach` over `list[dict]` slip past
import-time checks and crash `reflex run` at startup.

This test forces evaluation of every registered page so those bugs surface in
CI rather than when a user runs the dev server.
"""

import pytest


@pytest.fixture(scope="module")
def app():
    from web.web import app

    return app


def test_every_page_compiles(app):
    """Invoke each page component once, the same path `reflex run` takes."""
    for route, page in app._unevaluated_pages.items():
        page.component()
