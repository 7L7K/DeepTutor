"""Runtime helpers for request-scoped model selection."""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Any

from deeptutor.services.config.provider_runtime import ResolvedLLMConfig, resolve_llm_runtime_config
from deeptutor.services.llm import config as llm_config_module
from deeptutor.services.llm.config import LLMConfig

_TEXT_GENERATION_FEATURE: ContextVar[str | None] = ContextVar(
    "text_generation_feature", default=None
)


def llm_config_from_resolved(resolved: ResolvedLLMConfig) -> LLMConfig:
    """Convert provider-runtime output into the LLM service config shape."""
    return LLMConfig(
        model=resolved.model,
        api_key=resolved.api_key,
        base_url=resolved.base_url,
        effective_url=resolved.effective_url,
        binding=resolved.binding,
        provider_name=resolved.provider_name,
        provider_mode=resolved.provider_mode,
        api_version=resolved.api_version,
        extra_headers=resolved.extra_headers,
        reasoning_effort=resolved.reasoning_effort,
        context_window=resolved.context_window,
    )


def resolve_llm_config_for_selection(
    selection: Any, *, text_generation_feature: str | None = None
) -> LLMConfig:
    """Resolve the LLM config for a chat/session selection reference."""
    if selection is None and text_generation_feature is None:
        return llm_config_module.get_llm_config()
    return llm_config_from_resolved(
        resolve_llm_runtime_config(
            llm_selection=selection,
            text_generation_feature=text_generation_feature,
        )
    )


def activate_llm_selection(
    selection: Any, *, text_generation_feature: str | None = None
) -> tuple[LLMConfig, Token[LLMConfig | None]]:
    """Resolve and install a scoped LLM config for the current async context."""
    config = resolve_llm_config_for_selection(
        selection,
        # Phase 1 preserves explicit per-session selections. The feature
        # policy supplies the server default only when no selection is pinned.
        text_generation_feature=(
            text_generation_feature or _TEXT_GENERATION_FEATURE.get() if selection is None else None
        ),
    )
    token = llm_config_module.set_scoped_llm_config(config)
    return config, token


def reset_llm_selection(token: Token[LLMConfig | None] | None) -> None:
    if token is not None:
        llm_config_module.reset_scoped_llm_config(token)


def set_text_generation_feature(feature: str | None) -> Token[str | None]:
    return _TEXT_GENERATION_FEATURE.set(feature)


def reset_text_generation_feature(token: Token[str | None] | None) -> None:
    if token is not None:
        _TEXT_GENERATION_FEATURE.reset(token)


__all__ = [
    "activate_llm_selection",
    "llm_config_from_resolved",
    "reset_llm_selection",
    "reset_text_generation_feature",
    "resolve_llm_config_for_selection",
    "set_text_generation_feature",
]
