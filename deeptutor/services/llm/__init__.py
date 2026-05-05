"""LLM service exports.

The public names stay available from ``deeptutor.services.llm``, but the
underlying modules are imported only when a name is used.
"""

from importlib import import_module
from typing import Any

__all__ = [
    "LLMClient",
    "get_llm_client",
    "reset_llm_client",
    "LLMConfig",
    "get_llm_config",
    "clear_llm_config_cache",
    "reload_config",
    "uses_max_completion_tokens",
    "get_token_limit_kwargs",
    "PROVIDER_CAPABILITIES",
    "MODEL_OVERRIDES",
    "DEFAULT_CAPABILITIES",
    "get_capability",
    "supports_response_format",
    "supports_streaming",
    "system_in_messages",
    "has_thinking_tags",
    "supports_tools",
    "supports_vision",
    "requires_api_version",
    "MultimodalResult",
    "prepare_multimodal_messages",
    "LLMError",
    "LLMConfigError",
    "LLMProviderError",
    "LLMAPIError",
    "LLMTimeoutError",
    "LLMRateLimitError",
    "LLMAuthenticationError",
    "LLMModelNotFoundError",
    "complete",
    "stream",
    "fetch_models",
    "get_provider_presets",
    "API_PROVIDER_PRESETS",
    "LOCAL_PROVIDER_PRESETS",
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_RETRY_DELAY",
    "DEFAULT_EXPONENTIAL_BACKOFF",
    "cloud_provider",
    "local_provider",
    "sanitize_url",
    "is_local_llm_server",
    "build_chat_url",
    "build_auth_headers",
    "clean_thinking_tags",
    "extract_response_content",
]

_EXPORT_MODULES = {
    "LLMClient": "deeptutor.services.llm.client",
    "get_llm_client": "deeptutor.services.llm.client",
    "reset_llm_client": "deeptutor.services.llm.client",
    "LLMConfig": "deeptutor.services.llm.config",
    "get_llm_config": "deeptutor.services.llm.config",
    "clear_llm_config_cache": "deeptutor.services.llm.config",
    "reload_config": "deeptutor.services.llm.config",
    "uses_max_completion_tokens": "deeptutor.services.llm.config",
    "get_token_limit_kwargs": "deeptutor.services.llm.config",
    "PROVIDER_CAPABILITIES": "deeptutor.services.llm.capabilities",
    "MODEL_OVERRIDES": "deeptutor.services.llm.capabilities",
    "DEFAULT_CAPABILITIES": "deeptutor.services.llm.capabilities",
    "get_capability": "deeptutor.services.llm.capabilities",
    "supports_response_format": "deeptutor.services.llm.capabilities",
    "supports_streaming": "deeptutor.services.llm.capabilities",
    "system_in_messages": "deeptutor.services.llm.capabilities",
    "has_thinking_tags": "deeptutor.services.llm.capabilities",
    "supports_tools": "deeptutor.services.llm.capabilities",
    "supports_vision": "deeptutor.services.llm.capabilities",
    "requires_api_version": "deeptutor.services.llm.capabilities",
    "MultimodalResult": "deeptutor.services.llm.multimodal",
    "prepare_multimodal_messages": "deeptutor.services.llm.multimodal",
    "LLMError": "deeptutor.services.llm.exceptions",
    "LLMConfigError": "deeptutor.services.llm.exceptions",
    "LLMProviderError": "deeptutor.services.llm.exceptions",
    "LLMAPIError": "deeptutor.services.llm.exceptions",
    "LLMTimeoutError": "deeptutor.services.llm.exceptions",
    "LLMRateLimitError": "deeptutor.services.llm.exceptions",
    "LLMAuthenticationError": "deeptutor.services.llm.exceptions",
    "LLMModelNotFoundError": "deeptutor.services.llm.exceptions",
    "complete": "deeptutor.services.llm.factory",
    "stream": "deeptutor.services.llm.factory",
    "fetch_models": "deeptutor.services.llm.factory",
    "get_provider_presets": "deeptutor.services.llm.factory",
    "API_PROVIDER_PRESETS": "deeptutor.services.llm.factory",
    "LOCAL_PROVIDER_PRESETS": "deeptutor.services.llm.factory",
    "DEFAULT_MAX_RETRIES": "deeptutor.services.llm.factory",
    "DEFAULT_RETRY_DELAY": "deeptutor.services.llm.factory",
    "DEFAULT_EXPONENTIAL_BACKOFF": "deeptutor.services.llm.factory",
    "sanitize_url": "deeptutor.services.llm.utils",
    "is_local_llm_server": "deeptutor.services.llm.utils",
    "build_chat_url": "deeptutor.services.llm.utils",
    "build_auth_headers": "deeptutor.services.llm.utils",
    "clean_thinking_tags": "deeptutor.services.llm.utils",
    "extract_response_content": "deeptutor.services.llm.utils",
}


def __getattr__(name: str) -> Any:
    if name == "cloud_provider":
        return import_module("deeptutor.services.llm.cloud_provider")
    if name == "local_provider":
        return import_module("deeptutor.services.llm.local_provider")
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(module_name)
    return getattr(module, name)
