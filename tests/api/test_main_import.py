from __future__ import annotations


def test_api_main_imports_app() -> None:
    from deeptutor.api.main import app

    assert app.title == "TEEECHR API"
