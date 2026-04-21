"""Configuration helpers backed by runtime YAML and the project `.env` file."""

from .env_store import ConfigSummary, EnvStore, get_env_store

__all__ = [
    "ConfigSummary",
    "EnvStore",
    "get_env_store",
    "PROJECT_ROOT",
    "get_runtime_settings_dir",
    "load_config_with_main",
    "resolve_config_path",
    "get_path_from_config",
    "parse_language",
    "get_agent_params",
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


def __getattr__(name: str):
    """Lazy-load config helpers to keep import-time startup work small."""
    if name in {
        "PROJECT_ROOT",
        "get_runtime_settings_dir",
        "load_config_with_main",
        "resolve_config_path",
        "get_path_from_config",
        "parse_language",
        "get_agent_params",
    }:
        import importlib

        loader = importlib.import_module(f"{__name__}.loader")
        return getattr(loader, name)

    if name in {"KnowledgeBaseConfigService", "get_kb_config_service"}:
        import importlib

        kb_config = importlib.import_module(f"{__name__}.knowledge_base_config")
        return getattr(kb_config, name)

    if name in {"ModelCatalogService", "get_model_catalog_service"}:
        import importlib

        model_catalog = importlib.import_module(f"{__name__}.model_catalog")
        return getattr(model_catalog, name)

    if name in {
        "DEPRECATED_SEARCH_PROVIDERS",
        "NANOBOT_LLM_PROVIDERS",
        "SUPPORTED_SEARCH_PROVIDERS",
        "ResolvedLLMConfig",
        "ResolvedEmbeddingConfig",
        "ResolvedSearchConfig",
        "resolve_embedding_runtime_config",
        "resolve_llm_runtime_config",
        "resolve_search_runtime_config",
        "search_provider_state",
    }:
        import importlib

        provider_runtime = importlib.import_module(f"{__name__}.provider_runtime")
        return getattr(provider_runtime, name)

    if name in {"ConfigTestRunner", "TestRun", "get_config_test_runner"}:
        import importlib

        test_runner = importlib.import_module(f"{__name__}.test_runner")
        return getattr(test_runner, name)

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
