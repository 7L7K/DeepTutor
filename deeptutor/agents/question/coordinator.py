from __future__ import annotations

import os
import time
from typing import Any, Awaitable, Callable

from deeptutor.agents.question.agents.generator import Generator
from deeptutor.agents.question.models import QAPair, QuestionTemplate
from deeptutor.services.llm.config import get_llm_config


TraceCallback = Callable[[dict[str, Any]], Awaitable[None] | None]
WSCallback = Callable[[dict[str, Any]], Awaitable[None] | None]


class AgentCoordinator:
    """Thin coordinator for chat and Practice quiz generation.

    The old multi-agent coordinator was removed from this checkout, but
    ``deep_question`` still imports it. This implementation keeps the live
    route on the current fast path: direct templates plus set-level generation.
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        api_version: str | None = None,
        kb_name: str | None = None,
        language: str = "en",
        output_dir: str | None = None,
        tool_flags_override: dict[str, bool] | None = None,
        enable_idea_rag: bool = False,
        **_: Any,
    ) -> None:
        llm_config = get_llm_config()
        self.api_key = api_key or llm_config.api_key
        self.base_url = base_url or llm_config.base_url
        self.api_version = api_version or llm_config.api_version
        self.kb_name = kb_name
        self.language = language
        self.output_dir = output_dir or ""
        self.tool_flags_override = tool_flags_override or {}
        self.enable_idea_rag = enable_idea_rag
        self._ws_callback: WSCallback | None = None
        self._trace_callback: TraceCallback | None = None
        self._model = self._resolve_quiz_model(llm_config.model)

    def set_ws_callback(self, callback: WSCallback | None) -> None:
        self._ws_callback = callback

    def set_trace_callback(self, callback: TraceCallback | None) -> None:
        self._trace_callback = callback

    async def generate_from_topic(
        self,
        user_topic: str,
        preference: str = "",
        num_questions: int = 1,
        difficulty: str = "",
        question_type: str = "",
        history_context: str = "",
        attachments: list[Any] | None = None,
    ) -> dict[str, Any]:
        requested = max(1, int(num_questions or 1))
        templates = self._build_templates(
            user_topic=user_topic,
            preference=preference,
            count=requested,
            difficulty=difficulty,
            question_type=question_type,
            attachments=attachments or [],
        )
        await self._emit(
            {
                "type": "templates_ready",
                "stage": "ideation",
                "count": len(templates),
                "templates": [template.__dict__ for template in templates],
                "model": self._model,
            }
        )

        started_at = time.perf_counter()
        results: list[dict[str, Any]] = []
        first_useful_ms: float | None = None
        batches = self._planned_batches(templates)
        for batch_index, (batch_templates, generation_api) in enumerate(batches, start=1):
            await self._emit(
                {
                    "type": "progress",
                    "stage": "generation",
                    "status": "building_set",
                    "batch": batch_index,
                    "current": len(results),
                    "total": len(templates),
                    "model": self._model,
                    "generation_api": generation_api,
                }
            )
            qa_pairs = await self._build_generator().process_quiz_set(
                templates=batch_templates,
                user_topic=user_topic,
                preference=preference,
                history_context=history_context,
                generation_api=generation_api,
            )
            for qa_pair in qa_pairs:
                item = self._result_item(qa_pair)
                results.append(item)
                if first_useful_ms is None:
                    first_useful_ms = (time.perf_counter() - started_at) * 1000.0
                await self._emit(
                    {
                        "type": "result",
                        "stage": "generation",
                        "question_id": qa_pair.question_id,
                        "index": len(results) - 1,
                        "success": True,
                        "question": item["qa_pair"],
                        "model": self._model,
                        "generation_api": item["metadata"].get("generation_api"),
                    }
                )

        elapsed_ms = (time.perf_counter() - started_at) * 1000.0
        return {
            "results": results,
            "metadata": {
                "model_path": self.model_path,
                "model": self._model,
                "batch_count": len(batches),
                "first_useful_output_ms": round(first_useful_ms or elapsed_ms, 3),
                "total_completion_ms": round(elapsed_ms, 3),
            },
        }

    async def generate_from_exam(
        self,
        exam_paper_path: str,
        max_questions: int = 10,
        paper_mode: str = "parsed",
        history_context: str = "",
    ) -> dict[str, Any]:
        return await self.generate_from_topic(
            user_topic=f"Practice questions from {paper_mode} exam paper: {exam_paper_path}",
            preference="Mimic the exam paper style and assessed concepts.",
            num_questions=max_questions,
            difficulty="mixed",
            question_type="choice",
            history_context=history_context,
        )

    @property
    def model_path(self) -> str:
        return (
            "deep_question -> AgentCoordinator -> Generator("
            f"module=question, model={self._model}, source=PRACTICE_QUIZ_MODEL)"
        )

    def _build_generator(self) -> Generator:
        generator = Generator(
            kb_name=self.kb_name,
            language=self.language,
            tool_flags=self.tool_flags_override,
            api_key=self.api_key,
            base_url=self.base_url,
            api_version=self.api_version,
            model=self._model,
        )
        generator.set_trace_callback(self._trace_callback)
        return generator

    def _planned_batches(
        self,
        templates: list[QuestionTemplate],
    ) -> list[tuple[list[QuestionTemplate], str]]:
        if not templates:
            return []
        first_batch_size = self._env_int("PRACTICE_QUIZ_PROGRESSIVE_FIRST_BATCH", 0)
        if first_batch_size <= 0 or first_batch_size >= len(templates):
            return [(templates, self._generation_api("PRACTICE_GENERATION_API", "chat"))]
        starter = templates[:first_batch_size]
        remaining = templates[first_batch_size:]
        return [
            (starter, self._generation_api("PRACTICE_STARTER_PAGE_API", "chat")),
            (remaining, self._generation_api("PRACTICE_BACKGROUND_PAGE_API", "chat")),
        ]

    def _build_templates(
        self,
        *,
        user_topic: str,
        preference: str,
        count: int,
        difficulty: str,
        question_type: str,
        attachments: list[Any],
    ) -> list[QuestionTemplate]:
        domains = [
            "ethical and legal practice",
            "helping relationships",
            "assessment and testing",
            "human growth and development",
            "career development",
            "group counseling",
            "social and cultural foundations",
            "research and program evaluation",
            "professional orientation",
            "crisis response",
        ]
        requested_type = question_type.strip() or "choice"
        requested_difficulty = difficulty.strip() or "medium"
        knowledge_context = self._knowledge_context(user_topic, preference, attachments)
        return [
            QuestionTemplate(
                question_id=f"q_{index + 1}",
                concentration=domains[index % len(domains)],
                question_type=requested_type,
                difficulty=requested_difficulty,
                source="direct_template",
                metadata={
                    "knowledge_context": knowledge_context,
                    "model_path": self.model_path,
                },
            )
            for index in range(count)
        ]

    def _knowledge_context(
        self,
        user_topic: str,
        preference: str,
        attachments: list[Any],
    ) -> str:
        attachment_hint = ""
        if attachments:
            attachment_hint = f"\nAttached source count: {len(attachments)}."
        return (
            f"Topic: {user_topic.strip() or '(none)'}\n"
            f"Preference: {preference.strip() or '(none)'}"
            f"{attachment_hint}"
        )

    def _result_item(self, qa_pair: QAPair) -> dict[str, Any]:
        metadata = dict(qa_pair.metadata or {})
        metadata.setdefault("model_path", self.model_path)
        metadata.setdefault("model", self._model)
        return {
            "qa_pair": {
                "question_id": qa_pair.question_id,
                "question": qa_pair.question,
                "question_type": qa_pair.question_type,
                "options": qa_pair.options or {},
                "correct_answer": qa_pair.correct_answer,
                "explanation": qa_pair.explanation,
                "difficulty": qa_pair.difficulty,
                "concentration": qa_pair.concentration,
            },
            "validation": qa_pair.validation,
            "metadata": metadata,
        }

    async def _emit(self, payload: dict[str, Any]) -> None:
        if self._ws_callback is None:
            return
        result = self._ws_callback(payload)
        if hasattr(result, "__await__"):
            await result

    @staticmethod
    def _resolve_quiz_model(default_model: str) -> str:
        for key in ("PRACTICE_QUIZ_MODEL", "QUESTION_GENERATION_MODEL"):
            value = os.getenv(key, "").strip()
            if value:
                return value
        return default_model

    @staticmethod
    def _generation_api(key: str, fallback: str) -> str:
        return os.getenv(key, "").strip() or fallback

    @staticmethod
    def _env_int(key: str, fallback: int) -> int:
        raw = os.getenv(key, "").strip()
        if not raw:
            return fallback
        try:
            return int(raw)
        except ValueError:
            return fallback
