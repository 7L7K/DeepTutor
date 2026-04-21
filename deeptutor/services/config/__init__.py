"""Configuration helpers backed by runtime YAML and the project `.env` file."""

from __future__ import annotations

import importlib
from typing import Any

from .env_store import ConfigSummary, EnvStore, get_env_store

__all__ = [
    "ConfigSummary",
    "EnvStore",
    "get_env_store",
    "LaunchSettings",
    "load_launch_settings",
    "loader",
    "PROJECT_ROOT",
    "get_runtime_settings_dir",
    "load_config_with_main",
    "resolve_config_path",
    "get_path_from_config",
    "parse_language",
    "get_agent_params",
    "get_chat_params",
    "DEFAULT_CHAT_PARAMS",
    "ResolvedLLMConfig",
    "ResolvedEmbeddingConfig",
    "ResolvedSearchConfig",
    "resolve_llm_runtime_config",
    "resolve_embedding_runtime_config",
    "resolve_search_runtime_config",
    "search_provider_state",
    "NANOBOT_LLM_PROVIDERS",
    "SUPPORTED_SEARCH_PROVIDERS",
    "DEPRECATED_SEARCH_PROVIDERS",
    "KnowledgeBaseConfigService",
    "get_kb_config_service",
    "ModelCatalogService",
    "get_model_catalog_service",
    "ConfigTestRunner",
    "TestRun",
    "get_config_test_runner",
]

_EXPORT_MODULES = {
    "LaunchSettings": "deeptutor.services.config.launch_settings",
    "load_launch_settings": "deeptutor.services.config.launch_settings",
    "PROJECT_ROOT": "deeptutor.services.config.loader",
    "get_runtime_settings_dir": "deeptutor.services.config.loader",
    "load_config_with_main": "deeptutor.services.config.loader",
    "resolve_config_path": "deeptutor.services.config.loader",
    "get_path_from_config": "deeptutor.services.config.loader",
    "parse_language": "deeptutor.services.config.loader",
    "get_agent_params": "deeptutor.services.config.loader",
    "get_chat_params": "deeptutor.services.config.loader",
    "DEFAULT_CHAT_PARAMS": "deeptutor.services.config.loader",
    "KnowledgeBaseConfigService": "deeptutor.services.config.knowledge_base_config",
    "get_kb_config_service": "deeptutor.services.config.knowledge_base_config",
    "ModelCatalogService": "deeptutor.services.config.model_catalog",
    "get_model_catalog_service": "deeptutor.services.config.model_catalog",
    "DEPRECATED_SEARCH_PROVIDERS": "deeptutor.services.config.provider_runtime",
    "NANOBOT_LLM_PROVIDERS": "deeptutor.services.config.provider_runtime",
    "SUPPORTED_SEARCH_PROVIDERS": "deeptutor.services.config.provider_runtime",
    "ResolvedLLMConfig": "deeptutor.services.config.provider_runtime",
    "ResolvedEmbeddingConfig": "deeptutor.services.config.provider_runtime",
    "ResolvedSearchConfig": "deeptutor.services.config.provider_runtime",
    "resolve_embedding_runtime_config": "deeptutor.services.config.provider_runtime",
    "resolve_llm_runtime_config": "deeptutor.services.config.provider_runtime",
    "resolve_search_runtime_config": "deeptutor.services.config.provider_runtime",
    "search_provider_state": "deeptutor.services.config.provider_runtime",
    "ConfigTestRunner": "deeptutor.services.config.test_runner",
    "TestRun": "deeptutor.services.config.test_runner",
    "get_config_test_runner": "deeptutor.services.config.test_runner",
}


def __getattr__(name: str) -> Any:
    """Lazy-load config helpers to keep API startup imports small."""
    if name == "loader":
        return importlib.import_module("deeptutor.services.config.loader")
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = importlib.import_module(module_name)
    return getattr(module, name)
