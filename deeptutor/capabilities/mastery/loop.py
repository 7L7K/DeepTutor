"""Mastery path loop-capability hooks."""

from __future__ import annotations

from importlib import resources
from typing import Any

from deeptutor.capabilities.mastery.tools import MASTERY_TOOL_NAMES
from deeptutor.capabilities.protocol import PromptBlock
from deeptutor.core.context import UnifiedContext

_COURSE_MASTERY_ADDENDUM = """
[Course mastery restrictions]
Course map initialization happens only through the owned Course learning API/UI.
If mastery_status reports no objectives, tell the learner that Course initialization
is required; do not create a map yourself. Qualitative model-judgment assessment is
disabled: never request mastery_build or mastery_assess in a Course turn.
""".strip()


class MasteryLoopCapability:
    """Turn-scoped integration for mastery-path tutoring.

    Reuses the full chat tool surface (rag / read_source / ask_user / … under
    the same user toggles as chat) and adds the mastery engine tools on top.
    """

    name = "mastery"
    owned_tools = MASTERY_TOOL_NAMES
    _COURSE_SUPPRESSED_TOOLS = frozenset({"mastery_build", "mastery_assess"})

    def is_active(self, context: UnifiedContext) -> bool:
        return bool(context.metadata.get("mastery_mode"))

    @staticmethod
    def _is_course_turn(context: UnifiedContext) -> bool:
        return bool(context.metadata.get("course_context"))

    def owned_tools_for(self, context: UnifiedContext) -> tuple[str, ...]:
        """Keep Course mastery on the model-free status/quiz/grade contract."""
        if not self._is_course_turn(context):
            return self.owned_tools
        return tuple(name for name in self.owned_tools if name not in self._COURSE_SUPPRESSED_TOOLS)

    def forced_tools_for(self, context: UnifiedContext) -> tuple[str, ...]:
        """Course mastery needs the interactive answer handoff explicitly."""
        if self.is_active(context) and self._is_course_turn(context):
            return ("ask_user",)
        return ()

    def system_block(
        self,
        context: UnifiedContext,
        *,
        language: str,
        prompts: dict[str, Any],
    ) -> PromptBlock | None:
        if not self.is_active(context):
            return None
        override = _prompt_text(prompts, ("mastery", "system"))
        content = override or _load_system_prompt(language)
        if self._is_course_turn(context):
            content = f"{content}\n\n{_COURSE_MASTERY_ADDENDUM}"
        return PromptBlock("mastery_tutor", content)

    def augment_kwargs(
        self,
        tool_name: str,
        kwargs: dict[str, Any],
        context: UnifiedContext,
    ) -> dict[str, Any]:
        if self.is_active(context) and tool_name in MASTERY_TOOL_NAMES:
            updated = dict(kwargs)
            updated["_mastery_path_id"] = str(context.metadata.get("mastery_path_id") or "").strip()
            updated["_session_id"] = str(context.session_id or "").strip()
            updated["_turn_id"] = str(context.metadata.get("turn_id") or "").strip()
            course_context = context.metadata.get("course_context")
            if isinstance(course_context, dict):
                updated["_course_id"] = str(course_context.get("course_id") or "").strip()
            return updated
        return kwargs

    def pre_loop_seed(self, context: UnifiedContext) -> str:
        _ = context
        return ""


def _prompt_text(prompts: dict[str, Any], path: tuple[str, ...]) -> str:
    value: Any = prompts
    for key in path:
        if not isinstance(value, dict):
            return ""
        value = value.get(key)
    return value if isinstance(value, str) and value else ""


def _load_system_prompt(language: str) -> str:
    lang = "zh" if language.lower().startswith("zh") else "en"
    prompt = resources.files(__package__).joinpath("prompts", lang, "system.md")
    return prompt.read_text(encoding="utf-8").strip()


__all__ = ["MasteryLoopCapability"]
