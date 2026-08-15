import importlib
import json
import logging
from pathlib import Path

import pytest

from deeptutor.integrations.blueway.observability import emit_blueway_event
from deeptutor.logging import LoggingConfig, bind_log_context


@pytest.fixture(autouse=True)
def _clean_logging_handlers():
    configure_module = importlib.import_module("deeptutor.logging.configure")
    configure_module._remove_managed_handlers(logging.getLogger())
    yield
    configure_module._remove_managed_handlers(logging.getLogger())


def _flush_root_handlers() -> None:
    for handler in logging.getLogger().handlers:
        handler.flush()


def test_configure_logging_writes_jsonl_and_respects_level(monkeypatch, tmp_path: Path):
    configure_module = importlib.import_module("deeptutor.logging.configure")
    monkeypatch.setattr(
        configure_module,
        "load_logging_config",
        lambda: LoggingConfig(
            level="WARNING",
            console_output=False,
            file_output=True,
            log_dir=str(tmp_path),
            max_bytes=1024 * 1024,
            backup_count=1,
        ),
    )

    configure_module.configure_logging(force=True)
    logger = logging.getLogger("deeptutor.tests.config")
    with bind_log_context(request_id="req-1", task_id="task-1"):
        logger.info("filtered")
        logger.warning("written")
    _flush_root_handlers()

    lines = (tmp_path / "deeptutor.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["level"] == "WARNING"
    assert entry["logger"] == "deeptutor.tests.config"
    assert entry["message"] == "written"
    assert entry["context"] == {"request_id": "req-1", "task_id": "task-1"}


def test_configure_logging_uses_rotation_settings(monkeypatch, tmp_path: Path):
    configure_module = importlib.import_module("deeptutor.logging.configure")
    monkeypatch.setattr(
        configure_module,
        "load_logging_config",
        lambda: LoggingConfig(
            level="INFO",
            console_output=False,
            file_output=True,
            log_dir=str(tmp_path),
            max_bytes=220,
            backup_count=1,
        ),
    )

    configure_module.configure_logging(force=True)
    logger = logging.getLogger("deeptutor.tests.rotation")
    for index in range(20):
        logger.info("rotation line %02d %s", index, "x" * 40)
    _flush_root_handlers()

    assert (tmp_path / "deeptutor.jsonl").exists()
    assert (tmp_path / "deeptutor.jsonl.1").exists()


def test_blueway_lifecycle_event_survives_warning_default(monkeypatch, tmp_path: Path):
    configure_module = importlib.import_module("deeptutor.logging.configure")
    monkeypatch.setattr(
        configure_module,
        "load_logging_config",
        lambda: LoggingConfig(
            level="WARNING",
            console_output=False,
            file_output=True,
            log_dir=str(tmp_path),
        ),
    )

    configure_module.configure_logging(force=True)
    emitted = emit_blueway_event(
        "blueway_connection_revoke_failed",
        trace_id="bwr_11111111-1111-4111-8111-111111111111",
        connection_ref="bwc_connection",
        state_from="revocation_pending",
        state_to="revocation_pending",
        reason_code="provider_failure",
        outcome="failed",
    )
    _flush_root_handlers()

    assert emitted is not None
    entries = [
        json.loads(line)
        for line in (tmp_path / "deeptutor.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert entries[-1]["message"] == "blueway_connection_revoke_failed"
    assert entries[-1]["level"] == "INFO"
    assert entries[-1]["context"]["blueway_event"]["trace_id"] == emitted["trace_id"]


def test_console_formatter_includes_allowlisted_blueway_payload() -> None:
    from deeptutor.logging.formatters import ConsoleFormatter, ContextFilter

    record = logging.LogRecord(
        "deeptutor.integrations.blueway.observability",
        logging.WARNING,
        __file__,
        1,
        "blueway_sync_failed",
        (),
        None,
    )
    with bind_log_context(
        blueway_event={"trace_id": "bwr_safe", "state_to": "failed"},
    ):
        ContextFilter().filter(record)
    rendered = ConsoleFormatter().format(record)

    assert '"trace_id":"bwr_safe"' in rendered
    assert '"state_to":"failed"' in rendered
