"""Unified logging exports.

Exports are resolved lazily so focused imports do not pull optional logging
adapters or external-library integrations into latency-sensitive paths.
"""

from importlib import import_module
from typing import Any

__all__ = [
    "LOG_CONTEXT_FIELDS",
    "LoggingConfig",
    "configure_logging",
    "bind_log_context",
    "current_log_context",
    "capture_process_logs",
    "ProcessLogEvent",
    "Logger",
    "LogLevel",
    "get_logger",
    "reset_logger",
    "set_default_service_prefix",
    "ConsoleFormatter",
    "FileFormatter",
    "LlamaIndexLogContext",
    "LlamaIndexLogForwarder",
    "LLMStats",
    "LLMCall",
    "get_pricing",
    "estimate_tokens",
    "MODEL_PRICING",
    "load_logging_config",
    "get_default_log_dir",
    "get_global_log_level",
]

_EXPORT_MODULES = {
    "LOG_CONTEXT_FIELDS": "deeptutor.logging.context",
    "LoggingConfig": "deeptutor.logging.config",
    "configure_logging": "deeptutor.logging.configure",
    "bind_log_context": "deeptutor.logging.context",
    "current_log_context": "deeptutor.logging.context",
    "capture_process_logs": "deeptutor.logging.process_stream",
    "ProcessLogEvent": "deeptutor.logging.process_stream",
    "Logger": "deeptutor.logging.logger",
    "LogLevel": "deeptutor.logging.logger",
    "get_logger": "deeptutor.logging.logger",
    "reset_logger": "deeptutor.logging.logger",
    "set_default_service_prefix": "deeptutor.logging.logger",
    "ConsoleFormatter": "deeptutor.logging.logger",
    "FileFormatter": "deeptutor.logging.logger",
    "LlamaIndexLogContext": "deeptutor.logging.adapters",
    "LlamaIndexLogForwarder": "deeptutor.logging.adapters",
    "LLMStats": "deeptutor.logging.stats",
    "LLMCall": "deeptutor.logging.stats",
    "get_pricing": "deeptutor.logging.stats",
    "estimate_tokens": "deeptutor.logging.stats",
    "MODEL_PRICING": "deeptutor.logging.stats",
    "LoggingConfig": "deeptutor.logging.config",
    "load_logging_config": "deeptutor.logging.config",
    "get_default_log_dir": "deeptutor.logging.config",
    "get_global_log_level": "deeptutor.logging.config",
}


def __getattr__(name: str) -> Any:
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(module_name)
    return getattr(module, name)
