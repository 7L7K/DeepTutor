#!/usr/bin/env python
"""
Question Coordinator

Simplified architecture:
1) Template generation in batches (max 5 per batch)
2) Single-pass question generation per template
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime
import json
import logging
import os
from pathlib import Path
import time
from typing import Any

from deeptutor.agents.question.models import QAPair, QuestionTemplate
from deeptutor.services.config import PROJECT_ROOT, load_config_with_main
from deeptutor.services.path_service import get_path_service


DEFAULT_KB_PROGRESSIVE_QUIZ_FIRST_BATCH = 1
DEFAULT_KB_PROGRESSIVE_WARMUP_COUNT = 5
IDEA_BATCH_SIZE = 10
DEFAULT_REMAINING_QUIZ_BATCH_SIZE = 10
DEFAULT_REMAINING_QUIZ_CONCURRENCY = 2


class AgentCoordinator:
    """Coordinate topic-driven and paper-driven quiz generation."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        api_version: str | None = None,
        kb_name: str | None = None,
        output_dir: str | None = None,
        language: str = "en",
        tool_flags_override: dict[str, bool] | None = None,
        enable_idea_rag: bool = True,
        model: str | None = None,
    ) -> None:
        self.kb_name = kb_name
        self.output_dir = output_dir
        self.language = language
        self._api_key = api_key
        self._base_url = base_url
        self._api_version = api_version
        self._model = model or os.getenv("PRACTICE_QUIZ_MODEL") or os.getenv("QUESTION_GENERATION_MODEL")
        self._ws_callback: Callable | None = None
        self._trace_callback: Callable | None = None
        self.enable_idea_rag = enable_idea_rag

        self.config = load_config_with_main("main.yaml", PROJECT_ROOT)
        log_dir = self.config.get("paths", {}).get("user_log_dir") or self.config.get(
            "logging", {}
        ).get("log_dir")
        self.logger = logging.getLogger(__name__)

        question_cfg = self.config.get("capabilities", {}).get("question", {})
        generation_cfg = question_cfg.get("generation", {})
        default_tool_flags = generation_cfg.get(
            "tools",
            {"web_search": True, "rag": True, "code_execution": True},
        )
        self.tool_flags = (
            tool_flags_override if isinstance(tool_flags_override, dict) else default_tool_flags
        )
        self._current_batch_dir: Path | None = None

    def set_ws_callback(self, callback: Callable) -> None:
        self._ws_callback = callback

    def set_trace_callback(self, callback: Callable | None) -> None:
        self._trace_callback = callback

    async def _send_ws_update(self, update_type: str, data: dict[str, Any]) -> None:
        if self._ws_callback:
            try:
                await self._ws_callback({"type": update_type, **data})
            except Exception as exc:
                self.logger.debug(f"WS update failed: {exc}")

    def _create_idea_agent(self) -> IdeaAgent:
        from deeptutor.agents.question.agents.idea_agent import IdeaAgent

        agent = IdeaAgent(
            kb_name=self.kb_name,
            enable_rag=self.enable_idea_rag,
            language=self.language,
            api_key=self._api_key,
            base_url=self._base_url,
            api_version=self._api_version,
            model=self._model,
        )
        agent.set_trace_callback(self._trace_callback)
        return agent

    def _create_generator(self) -> Generator:
        from deeptutor.agents.question.agents.generator import Generator

        agent = Generator(
            kb_name=self.kb_name,
            language=self.language,
            tool_flags=self.tool_flags,
            api_key=self._api_key,
            base_url=self._base_url,
            api_version=self._api_version,
            model=self._model,
        )
        agent.set_trace_callback(self._trace_callback)
        return agent

    async def generate_from_topic(
        self,
        user_topic: str,
        preference: str,
        num_questions: int,
        difficulty: str = "",
        question_type: str = "",
        history_context: str = "",
        attachments: list[Any] | None = None,
    ) -> dict[str, Any]:
        started_at = time.perf_counter()
        self._current_batch_dir = self._create_batch_dir("custom")
        requested = max(1, int(num_questions or 1))
        if self._should_skip_topic_ideation():
            templates = self._build_direct_topic_templates(
                user_topic=user_topic,
                requested=requested,
                difficulty=difficulty,
                question_type=question_type,
            )
            await self._send_ws_update(
                "templates_ready",
                {
                    "stage": "ideation",
                    "count": len(templates),
                    "generated_total": len(templates),
                    "requested_total": requested,
                    "templates": [t.__dict__ for t in templates],
                    "skipped": True,
                },
            )
            generation_started_at = time.perf_counter()
            qa_pairs = await self._generation_loop(
                templates=templates,
                user_topic=user_topic,
                preference=preference,
                history_context=history_context,
            )
            generation_elapsed = time.perf_counter() - generation_started_at
            self.logger.info(
                f"Practice quiz direct generation complete: requested={requested} "
                f"questions={len(qa_pairs)} generation_elapsed={generation_elapsed:.2f}s "
                f"total_elapsed={time.perf_counter() - started_at:.2f}s"
            )
            return self._build_summary(
                source="topic",
                requested=requested,
                templates=templates,
                qa_pairs=qa_pairs,
                trace={"ideation_skipped": True, "batches": []},
            )

        idea_agent = self._create_idea_agent()
        templates: list[QuestionTemplate] = []
        batch_trace: list[dict[str, Any]] = []
        existing_concentrations: list[str] = []
        early_results: list[dict[str, Any]] = []
        preloaded_knowledge_context: str | None = None
        preloaded_retrieval_queries: list[str] | None = None

        normalized_difficulty = difficulty.strip().lower()
        normalized_question_type = question_type.strip().lower()
        target_difficulty = (
            normalized_difficulty
            if normalized_difficulty and normalized_difficulty != "auto"
            else ""
        )
        target_question_type = (
            normalized_question_type
            if normalized_question_type and normalized_question_type != "auto"
            else ""
        )

        early_count = self._early_kb_first_question_count(requested)
        if early_count:
            context_started_at = time.perf_counter()
            context_result = await idea_agent.retrieve_context_for_topic(
                user_topic,
                trace_id="early-first-question",
                batch_number=0,
            )
            preloaded_knowledge_context = str(
                context_result.get("knowledge_context") or ""
            )
            preloaded_retrieval_queries = [
                str(query)
                for query in context_result.get("retrieval_queries", [])
                if str(query).strip()
            ]
            first_template = self._build_direct_topic_templates(
                user_topic=user_topic,
                requested=1,
                difficulty=difficulty,
                question_type=question_type,
            )[0]
            first_template.question_id = "q_1"
            first_template.metadata = {
                **(first_template.metadata or {}),
                "knowledge_context": preloaded_knowledge_context[:6000],
                "retrieval_queries": preloaded_retrieval_queries,
                "direct_streamed_first": True,
            }
            await self._send_ws_update(
                "progress",
                {
                    "stage": "generation",
                    "status": "building_first_questions",
                    "current": 0,
                    "total": requested,
                },
            )
            generator = self._create_generator()
            first_result = await self._generate_one_question_result(
                generator=generator,
                idx=1,
                template=first_template,
                user_topic=user_topic,
                preference=preference,
                history_context=history_context,
                previous_questions=[],
                generation_mode="direct_kb_first",
            )
            early_results.append(first_result)
            templates.append(first_template)
            existing_concentrations.append(first_template.concentration)
            self.logger.info(
                f"First KB-backed quiz question streamed after "
                f"{time.perf_counter() - context_started_at:.2f}s"
            )

        if early_count and self._should_skip_kb_ideation():
            direct_templates = self._build_direct_topic_templates(
                user_topic=user_topic,
                requested=requested,
                difficulty=difficulty,
                question_type=question_type,
            )
            generated_templates: list[QuestionTemplate] = []
            for template in direct_templates[len(templates) : requested]:
                template.question_id = f"q_{len(templates) + 1}"
                template.metadata = {
                    **(template.metadata or {}),
                    "knowledge_context": (preloaded_knowledge_context or "")[:6000],
                    "retrieval_queries": preloaded_retrieval_queries or [],
                    "direct_kb_templates": True,
                }
                templates.append(template)
                generated_templates.append(template)
                existing_concentrations.append(template.concentration)

            batch_trace.append(
                {
                    "batch": "direct_kb_templates",
                    "requested": requested - early_count,
                    "generated": len(generated_templates),
                    "elapsed_seconds": 0.0,
                    "knowledge_context": preloaded_knowledge_context or "",
                }
            )
            await self._send_ws_update(
                "templates_ready",
                {
                    "stage": "ideation",
                    "count": len(generated_templates),
                    "generated_total": len(templates),
                    "requested_total": requested,
                    "templates": [t.__dict__ for t in generated_templates],
                    "skipped": True,
                    "source": "direct_kb_templates",
                },
            )

        batch_number = 0
        while len(templates) < requested:
            batch_number += 1
            batch_size = min(IDEA_BATCH_SIZE, requested - len(templates))
            await self._send_ws_update(
                "progress",
                {
                    "stage": "ideation",
                    "status": "running",
                    "batch": batch_number,
                    "current": len(templates),
                    "total": requested,
                    "batch_size": batch_size,
                },
            )

            batch_started_at = time.perf_counter()
            idea_result = await idea_agent.process(
                user_topic=user_topic,
                preference=preference,
                num_ideas=batch_size,
                target_difficulty=target_difficulty,
                target_question_type=target_question_type,
                existing_concentrations=existing_concentrations,
                batch_number=batch_number,
                attachments=attachments,
                knowledge_context_override=preloaded_knowledge_context,
                retrieval_queries_override=preloaded_retrieval_queries,
            )
            batch_templates = idea_result.get("templates", [])
            if not isinstance(batch_templates, list):
                batch_templates = []
            batch_elapsed = time.perf_counter() - batch_started_at

            for template in batch_templates:
                if not isinstance(template, QuestionTemplate):
                    continue
                template.question_id = f"q_{len(templates) + 1}"
                templates.append(template)
                existing_concentrations.append(template.concentration)

            batch_trace.append(
                {
                    "batch": batch_number,
                    "requested": batch_size,
                    "generated": len(batch_templates),
                    "elapsed_seconds": round(batch_elapsed, 3),
                    "knowledge_context": idea_result.get("knowledge_context", ""),
                }
            )
            self.logger.info(
                f"Practice quiz ideation batch complete: batch={batch_number} "
                f"requested={batch_size} generated={len(batch_templates)} "
                f"elapsed={batch_elapsed:.2f}s"
            )
            await self._send_ws_update(
                "templates_ready",
                {
                    "stage": "ideation",
                    "batch": batch_number,
                    "count": len(batch_templates),
                    "generated_total": len(templates),
                    "requested_total": requested,
                    "templates": [t.__dict__ for t in batch_templates],
                },
            )

            if not batch_templates:
                self.logger.warning("Template generation returned an empty batch; stopping early.")
                break

        await self._send_ws_update(
            "progress",
            {
                "stage": "ideation",
                "status": "complete",
                "current": len(templates),
                "total": requested,
                "batches": batch_number,
            },
        )

        generation_started_at = time.perf_counter()
        remaining_templates = templates[len(early_results) : requested]
        remaining_pairs = await self._generation_loop(
            templates=remaining_templates,
            user_topic=user_topic,
            preference=preference,
            history_context=history_context,
            progressive_count_override=0 if early_results else None,
            external_streamed_count=len(early_results),
        )
        qa_pairs = [*early_results, *remaining_pairs]
        generation_elapsed = time.perf_counter() - generation_started_at
        self.logger.info(
            f"Practice quiz generation complete: requested={requested} "
            f"templates={len(templates[:requested])} questions={len(qa_pairs)} "
            f"generation_elapsed={generation_elapsed:.2f}s total_elapsed={time.perf_counter() - started_at:.2f}s"
        )
        return self._build_summary(
            source="topic",
            requested=requested,
            templates=templates[:requested],
            qa_pairs=qa_pairs,
            trace={"batches": batch_trace},
        )

    async def generate_from_exam(
        self,
        exam_paper_path: str,
        max_questions: int,
        paper_mode: str = "upload",
        history_context: str = "",
    ) -> dict[str, Any]:
        if self._current_batch_dir is None:
            self._current_batch_dir = self._create_batch_dir("mimic")
        templates, parse_trace = await self._parse_exam_to_templates(
            exam_paper_path=exam_paper_path,
            max_questions=max_questions,
            paper_mode=paper_mode,
        )
        for idx, template in enumerate(templates, 1):
            template.question_id = f"q_{idx}"

        await self._send_ws_update(
            "templates_ready",
            {
                "stage": "ideation",
                "count": len(templates),
                "generated_total": len(templates),
                "requested_total": max_questions,
                "templates": [t.__dict__ for t in templates],
            },
        )

        qa_pairs = await self._generation_loop(
            templates=templates,
            user_topic="",
            preference="",
            history_context=history_context,
        )
        return self._build_summary(
            source="exam",
            requested=max_questions,
            templates=templates,
            qa_pairs=qa_pairs,
            trace=parse_trace,
        )

    async def _generation_loop(
        self,
        templates: list[QuestionTemplate],
        user_topic: str,
        preference: str,
        history_context: str = "",
        progressive_count_override: int | None = None,
        external_streamed_count: int = 0,
    ) -> list[dict[str, Any]]:
        generator = self._create_generator()
        results: list[dict[str, Any]] = []
        total = len(templates)
        await self._send_ws_update(
            "progress",
            {
                "stage": "generation",
                "status": "building_set",
                "current": 0,
                "total": total,
            },
        )

        async def emit_result(
            idx: int,
            template: QuestionTemplate,
            qa_pair: QAPair,
        ) -> None:
            result = self._build_question_result(template, qa_pair)
            results.append(result)
            await self._emit_question_result(idx, template, qa_pair, result["success"])

        accepted_questions: list[str] = []
        started_at = time.perf_counter()
        first_ready_at: float | None = None
        progressive_count = (
            min(max(0, progressive_count_override), total)
            if progressive_count_override is not None
            else self._progressive_first_batch_size(total)
        )
        if progressive_count == 0 and total:
            self.logger.info(
                f"Using fast quiz-set generation: kb={self.kb_name or '(none)'} questions={total}"
            )

        if self._should_use_parallel_direct_generation(templates):
            await self._send_ws_update(
                "progress",
                {
                    "stage": "generation",
                    "status": "building_parallel_questions",
                    "current": 0,
                    "total": total,
                },
            )

            async def build_single(
                idx: int,
                template: QuestionTemplate,
            ) -> tuple[int, QuestionTemplate, QAPair]:
                try:
                    qa_pair = await generator.process(
                        template=template,
                        user_topic=user_topic,
                        preference=preference,
                        history_context=history_context,
                        previous_questions=[],
                    )
                except Exception as exc:
                    self.logger.warning(f"Parallel question generation failed: {exc}")
                    qa_pair = QAPair(
                        question_id=template.question_id,
                        question=f"[Generation failed] {template.concentration}",
                        correct_answer="N/A",
                        explanation=str(exc),
                        question_type=template.question_type,
                        concentration=template.concentration,
                        difficulty=template.difficulty,
                        metadata={"error": str(exc), "generation_mode": "parallel_single"},
                    )
                return idx, template, qa_pair

            built_questions = await asyncio.gather(
                *[
                    build_single(idx, template)
                    for idx, template in enumerate(templates, 1)
                ]
            )
            for idx, template, qa_pair in sorted(built_questions, key=lambda item: item[0]):
                if first_ready_at is None:
                    first_ready_at = time.perf_counter() - started_at
                await emit_result(idx, template, qa_pair)

            await self._send_ws_update(
                "progress",
                {"stage": "complete", "completed": len(results), "total": total},
            )
            self.logger.info(
                f"Quiz parallel generation completed: first_ready={first_ready_at or 0.0:.2f}s "
                f"total={time.perf_counter() - started_at:.2f}s questions={len(results)}"
            )
            return results

        for idx, template in enumerate(templates[:progressive_count], 1):
            await self._send_ws_update(
                "progress",
                {
                    "stage": "generation",
                    "status": "building_first_questions",
                    "current": idx - 1,
                    "total": total,
                },
            )
            try:
                qa_pair = await generator.process(
                    template=template,
                    user_topic=user_topic,
                    preference=preference,
                    history_context=history_context,
                    previous_questions=accepted_questions,
                )
            except Exception as exc:
                self.logger.warning(f"Progressive question generation failed: {exc}")
                qa_pair = QAPair(
                    question_id=template.question_id,
                    question=f"[Generation failed] {template.concentration}",
                    correct_answer="N/A",
                    explanation=str(exc),
                    question_type=template.question_type,
                    concentration=template.concentration,
                    difficulty=template.difficulty,
                    metadata={"error": str(exc), "generation_mode": "progressive_single"},
                )

            question_text = str(qa_pair.question or "").strip()
            if question_text and not (qa_pair.metadata or {}).get("error"):
                accepted_questions.append(question_text)
            if first_ready_at is None:
                first_ready_at = time.perf_counter() - started_at
                self.logger.info(
                    f"First quiz question ready in {first_ready_at:.2f}s using progressive generation"
                )
            await emit_result(idx, template, qa_pair)

        remaining_templates = templates[progressive_count:]
        warmup_count = 0
        streamed_before_warmup = progressive_count + external_streamed_count
        if streamed_before_warmup:
            warmup_count = self._progressive_warmup_extra_count(
                total + external_streamed_count,
                streamed_before_warmup,
            )
            warmup_count = min(warmup_count, len(remaining_templates))
        if warmup_count:
            warmup_templates = remaining_templates[:warmup_count]
            await self._send_ws_update(
                "progress",
                {
                    "stage": "generation",
                    "status": "building_streamed_warmup",
                    "current": len(results),
                    "total": total,
                    "warmup_count": len(warmup_templates),
                },
            )

            async def build_warmup_single(
                idx: int,
                template: QuestionTemplate,
            ) -> tuple[int, QuestionTemplate, QAPair]:
                try:
                    qa_pair = await generator.process(
                        template=template,
                        user_topic=user_topic,
                        preference=preference,
                        history_context=history_context,
                        previous_questions=accepted_questions,
                    )
                    qa_pair.metadata = {
                        **(qa_pair.metadata or {}),
                        "generation_mode": "progressive_warmup_single",
                    }
                except Exception as exc:
                    self.logger.warning(f"Warmup question generation failed: {exc}")
                    qa_pair = QAPair(
                        question_id=template.question_id,
                        question=f"[Generation failed] {template.concentration}",
                        correct_answer="N/A",
                        explanation=str(exc),
                        question_type=template.question_type,
                        concentration=template.concentration,
                        difficulty=template.difficulty,
                        metadata={
                            "error": str(exc),
                            "generation_mode": "progressive_warmup_single",
                        },
                    )
                return idx, template, qa_pair

            pending_warmup = {
                asyncio.create_task(
                    build_warmup_single(progressive_count + offset, template)
                ): progressive_count + offset
                for offset, template in enumerate(warmup_templates, 1)
            }
            completed_warmup: dict[int, tuple[QuestionTemplate, QAPair]] = {}
            next_warmup_to_emit = progressive_count + 1

            while pending_warmup:
                done, _pending = await asyncio.wait(
                    pending_warmup.keys(),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in done:
                    pending_warmup.pop(task, None)
                    idx, template, qa_pair = task.result()
                    completed_warmup[idx] = (template, qa_pair)

                while next_warmup_to_emit in completed_warmup:
                    template, qa_pair = completed_warmup.pop(next_warmup_to_emit)
                    await emit_result(next_warmup_to_emit, template, qa_pair)
                    question_text = str(qa_pair.question or "").strip()
                    if question_text and not (qa_pair.metadata or {}).get("error"):
                        accepted_questions.append(question_text)
                    next_warmup_to_emit += 1

            remaining_templates = remaining_templates[warmup_count:]

        if remaining_templates:
            remaining_start_index = progressive_count + warmup_count
            remaining_history_context = history_context
            if accepted_questions:
                remaining_history_context = (
                    f"{history_context}\n\nAlready generated questions to avoid duplicating:\n"
                    + "\n".join(f"- {question}" for question in accepted_questions)
                ).strip()
            batch_size = self._remaining_quiz_batch_size()
            chunks = [
                (
                    chunk_index,
                    chunk_start,
                    remaining_templates[chunk_start : chunk_start + batch_size],
                )
                for chunk_index, chunk_start in enumerate(
                    range(0, len(remaining_templates), batch_size),
                    1,
                )
            ]
            concurrency = min(len(chunks), self._remaining_quiz_concurrency())
            semaphore = asyncio.Semaphore(max(1, concurrency))

            async def build_remaining_chunk(
                chunk_index: int,
                chunk_start: int,
                chunk: list[QuestionTemplate],
            ) -> tuple[int, int, list[QuestionTemplate], list[QAPair]]:
                async with semaphore:
                    await self._send_ws_update(
                        "progress",
                        {
                            "stage": "generation",
                            "status": "building_remaining_set",
                            "current": len(results),
                            "total": total,
                            "batch_size": len(chunk),
                            "batch": chunk_index,
                            "batches": len(chunks),
                            "concurrency": concurrency,
                        },
                    )
                    try:
                        qa_pairs = await generator.process_quiz_set(
                            templates=chunk,
                            user_topic=user_topic,
                            preference=preference,
                            history_context=remaining_history_context,
                        )
                    except Exception as exc:
                        self.logger.warning(f"Remaining quiz-set generation failed: {exc}")
                        qa_pairs = [
                            QAPair(
                                question_id=template.question_id,
                                question=f"[Generation failed] {template.concentration}",
                                correct_answer="N/A",
                                explanation=str(exc),
                                question_type=template.question_type,
                                concentration=template.concentration,
                                difficulty=template.difficulty,
                                metadata={"error": str(exc), "generation_mode": "quiz_set"},
                            )
                            for template in chunk
                        ]
                    return chunk_index, chunk_start, chunk, qa_pairs

            pending_tasks = {
                asyncio.create_task(build_remaining_chunk(*chunk)): chunk[0]
                for chunk in chunks
            }
            completed_chunks: dict[
                int,
                tuple[int, list[QuestionTemplate], list[QAPair]],
            ] = {}
            next_chunk_to_emit = 1

            while pending_tasks:
                done, _pending = await asyncio.wait(
                    pending_tasks.keys(),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in done:
                    pending_tasks.pop(task, None)
                    chunk_index, chunk_start, chunk, qa_pairs = task.result()
                    completed_chunks[chunk_index] = (chunk_start, chunk, qa_pairs)

                while next_chunk_to_emit in completed_chunks:
                    chunk_start, chunk, qa_pairs = completed_chunks.pop(next_chunk_to_emit)
                    await self._send_ws_update(
                        "progress",
                        {
                            "stage": "generation",
                            "status": "validating_set",
                            "current": len(results),
                            "total": total,
                            "batch_size": len(chunk),
                            "batch": next_chunk_to_emit,
                            "batches": len(chunks),
                            "concurrency": concurrency,
                        },
                    )
                    for offset, (template, qa_pair) in enumerate(
                        zip(chunk, qa_pairs, strict=False),
                        remaining_start_index + chunk_start + 1,
                    ):
                        await emit_result(offset, template, qa_pair)
                        question_text = str(qa_pair.question or "").strip()
                        if question_text and not (qa_pair.metadata or {}).get("error"):
                            accepted_questions.append(question_text)

                    next_chunk_to_emit += 1

        await self._send_ws_update(
            "progress",
            {"stage": "complete", "completed": len(results), "total": total},
        )
        self.logger.info(
            f"Quiz generation completed: first_ready={first_ready_at or 0.0:.2f}s "
            f"total={time.perf_counter() - started_at:.2f}s questions={len(results)}"
        )
        return results

    async def _generate_one_question_result(
        self,
        *,
        generator: Any,
        idx: int,
        template: QuestionTemplate,
        user_topic: str,
        preference: str,
        history_context: str,
        previous_questions: list[str],
        generation_mode: str,
    ) -> dict[str, Any]:
        try:
            qa_pair = await generator.process(
                template=template,
                user_topic=user_topic,
                preference=preference,
                history_context=history_context,
                previous_questions=previous_questions,
            )
            qa_pair.metadata = {
                **(qa_pair.metadata or {}),
                "generation_mode": generation_mode,
            }
        except Exception as exc:
            self.logger.warning(f"First question generation failed: {exc}")
            qa_pair = QAPair(
                question_id=template.question_id,
                question=f"[Generation failed] {template.concentration}",
                correct_answer="N/A",
                explanation=str(exc),
                question_type=template.question_type,
                concentration=template.concentration,
                difficulty=template.difficulty,
                metadata={"error": str(exc), "generation_mode": generation_mode},
            )
        result = self._build_question_result(template, qa_pair)
        await self._emit_question_result(idx, template, qa_pair, result["success"])
        return result

    @staticmethod
    def _build_question_result(
        template: QuestionTemplate,
        qa_pair: QAPair,
    ) -> dict[str, Any]:
        success = not bool((qa_pair.metadata or {}).get("error")) and bool(
            (qa_pair.validation or {}).get("schema_ok", True)
        )
        return {
            "template": template.__dict__,
            "qa_pair": qa_pair.__dict__,
            "success": success,
        }

    async def _emit_question_result(
        self,
        idx: int,
        template: QuestionTemplate,
        qa_pair: QAPair,
        success: bool,
    ) -> None:
        await self._send_ws_update(
            "result",
            {
                "question_id": template.question_id,
                "index": idx - 1,
                "question": qa_pair.__dict__,
                "success": success,
            },
        )

    def _progressive_first_batch_size(self, total_questions: int) -> int:
        """Return how many questions should stream before the remaining set call.

        Topic-only quizzes stay on the single set call because they are already
        much faster. KB-backed quizzes need a first usable question quickly so
        the Practice page is not blank while the grounded set finishes.
        """
        if total_questions <= 1:
            return 0

        raw = os.getenv("PRACTICE_QUIZ_PROGRESSIVE_FIRST_BATCH", "").strip().lower()
        if raw in {"0", "false", "no", "off", "none"}:
            configured = 0
        elif raw:
            try:
                configured = int(raw)
            except ValueError:
                configured = DEFAULT_KB_PROGRESSIVE_QUIZ_FIRST_BATCH if self.kb_name else 0
        else:
            configured = DEFAULT_KB_PROGRESSIVE_QUIZ_FIRST_BATCH if self.kb_name else 0
        return min(max(0, configured), total_questions)

    def _early_kb_first_question_count(self, total_questions: int) -> int:
        if not self.kb_name or not self.enable_idea_rag:
            return 0
        return min(1, self._progressive_first_batch_size(total_questions))

    def _progressive_warmup_extra_count(
        self,
        total_questions: int,
        already_streamed: int,
    ) -> int:
        if not self.kb_name or total_questions <= already_streamed:
            return 0
        raw = os.getenv("PRACTICE_QUIZ_PROGRESSIVE_WARMUP_COUNT", "").strip().lower()
        if raw in {"0", "false", "no", "off", "none"}:
            target = already_streamed
        elif raw:
            try:
                target = int(raw)
            except ValueError:
                target = DEFAULT_KB_PROGRESSIVE_WARMUP_COUNT
        else:
            target = DEFAULT_KB_PROGRESSIVE_WARMUP_COUNT
        target = min(max(0, target), total_questions, 10)
        return max(0, target - already_streamed)

    def _should_skip_kb_ideation(self) -> bool:
        if not self.kb_name or not self.enable_idea_rag:
            return False
        raw = os.getenv("PRACTICE_QUIZ_SKIP_KB_IDEATION", "").strip().lower()
        if raw in {"0", "false", "no", "off", "ideation"}:
            return False
        return True

    @staticmethod
    def _remaining_quiz_batch_size() -> int:
        raw = os.getenv("PRACTICE_QUIZ_REMAINING_BATCH_SIZE", "").strip().lower()
        if not raw:
            return DEFAULT_REMAINING_QUIZ_BATCH_SIZE
        try:
            configured = int(raw)
        except ValueError:
            return DEFAULT_REMAINING_QUIZ_BATCH_SIZE
        return min(12, max(1, configured))

    @staticmethod
    def _remaining_quiz_concurrency() -> int:
        raw = os.getenv("PRACTICE_QUIZ_REMAINING_CONCURRENCY", "").strip().lower()
        if not raw:
            return DEFAULT_REMAINING_QUIZ_CONCURRENCY
        try:
            configured = int(raw)
        except ValueError:
            return DEFAULT_REMAINING_QUIZ_CONCURRENCY
        return min(4, max(1, configured))

    @staticmethod
    def _should_use_parallel_direct_generation(templates: list[QuestionTemplate]) -> bool:
        raw = os.getenv("PRACTICE_QUIZ_PARALLEL_DIRECT", "").strip().lower()
        if not raw:
            return False
        if raw in {"0", "false", "no", "off"}:
            return False
        return len(templates) > 1 and all(
            bool((template.metadata or {}).get("ideation_skipped"))
            for template in templates
        )

    def _should_skip_topic_ideation(self) -> bool:
        raw = os.getenv("PRACTICE_QUIZ_SKIP_IDEATION", "").strip().lower()
        if raw in {"0", "false", "no", "off", "ideation"}:
            return False
        if raw in {"always", "force"}:
            return True
        if raw in {"1", "true", "yes", "on", "direct"}:
            return not bool(self.kb_name)
        return not bool(self.kb_name)

    @staticmethod
    def _build_direct_topic_templates(
        *,
        user_topic: str,
        requested: int,
        difficulty: str,
        question_type: str,
    ) -> list[QuestionTemplate]:
        normalized_difficulty = difficulty.strip().lower()
        normalized_question_type = question_type.strip().lower()
        resolved_difficulty = (
            normalized_difficulty
            if normalized_difficulty and normalized_difficulty != "auto"
            else "medium"
        )
        resolved_question_type = (
            normalized_question_type
            if normalized_question_type and normalized_question_type != "auto"
            else "choice"
        )
        topic = user_topic.strip() or "target study topic"
        lenses = [
            "professional orientation and ethical practice",
            "social and cultural diversity application",
            "human growth and lifespan development",
            "career development decision-making",
            "counseling and helping relationships",
            "group counseling process",
            "assessment and testing interpretation",
            "research and program evaluation",
            "diagnosis and treatment planning",
            "crisis, risk, and documentation judgment",
        ]
        templates: list[QuestionTemplate] = []
        for idx in range(1, requested + 1):
            lens = lenses[(idx - 1) % len(lenses)]
            templates.append(
                QuestionTemplate(
                    question_id=f"q_{idx}",
                    concentration=f"{topic} - {lens}",
                    question_type=resolved_question_type,
                    difficulty=resolved_difficulty,
                    source="custom",
                    metadata={
                        "idea_id": f"direct_{idx}",
                        "rationale": "Direct template generated to avoid a separate ideation LLM call.",
                        "knowledge_context": "Retrieval disabled.",
                        "retrieval_queries": [],
                        "ideation_skipped": True,
                    },
                )
            )
        return templates

    async def _parse_exam_to_templates(
        self,
        exam_paper_path: str,
        max_questions: int,
        paper_mode: str,
    ) -> tuple[list[QuestionTemplate], dict[str, Any]]:
        from deeptutor.tools.question.pdf_parser import parse_pdf_with_mineru
        from deeptutor.tools.question.question_extractor import extract_questions_from_paper

        await self._send_ws_update(
            "progress", {"stage": "parsing", "status": "running"}
        )

        paper_path = Path(exam_paper_path)
        output_base = (
            self._current_batch_dir
            or (Path(self.output_dir) if self.output_dir else None)
            or get_path_service().get_question_dir()
        )
        output_base.mkdir(parents=True, exist_ok=True)

        if paper_mode == "parsed":
            working_dir = paper_path
        else:
            parse_success = parse_pdf_with_mineru(str(paper_path), str(output_base))
            if not parse_success:
                raise RuntimeError("Failed to parse exam paper with MinerU")
            subdirs = sorted(
                [d for d in output_base.iterdir() if d.is_dir()],
                key=lambda d: d.stat().st_mtime,
                reverse=True,
            )
            if not subdirs:
                raise RuntimeError("No parsed exam directory found after MinerU parsing")
            working_dir = subdirs[0]

        await self._send_ws_update(
            "progress",
            {"stage": "extracting", "status": "running", "paper_dir": str(working_dir)},
        )

        json_files = list(working_dir.glob("*_questions.json"))
        if not json_files:
            extract_success = extract_questions_from_paper(str(working_dir), output_dir=None)
            if not extract_success:
                raise RuntimeError("Failed to extract questions from parsed exam")
            json_files = list(working_dir.glob("*_questions.json"))
        if not json_files:
            raise RuntimeError("Question extraction output not found")

        with open(json_files[0], encoding="utf-8") as f:
            payload = json.load(f)
        questions = payload.get("questions", [])
        if max_questions > 0:
            questions = questions[:max_questions]

        templates: list[QuestionTemplate] = []
        for i, item in enumerate(questions, 1):
            if not isinstance(item, dict):
                continue
            q_text = str(item.get("question_text", "")).strip()
            if not q_text:
                continue
            templates.append(
                QuestionTemplate(
                    question_id=f"q_{i}",
                    concentration=q_text[:240],
                    question_type=str(item.get("question_type", "written")).lower(),
                    difficulty="medium",
                    source="mimic",
                    reference_question=q_text,
                    reference_answer=str(item.get("answer", "")).strip() or None,
                    metadata={
                        "question_number": item.get("question_number", str(i)),
                        "images": item.get("images", []),
                    },
                )
            )

        await self._send_ws_update(
            "progress",
            {"stage": "extracting", "status": "complete", "templates": len(templates)},
        )
        return templates, {
            "paper_dir": str(working_dir),
            "question_file": str(json_files[0]),
            "template_count": len(templates),
        }

    def _build_summary(
        self,
        source: str,
        requested: int,
        templates: list[QuestionTemplate],
        qa_pairs: list[dict[str, Any]],
        trace: dict[str, Any],
    ) -> dict[str, Any]:
        completed = sum(1 for item in qa_pairs if item.get("success"))
        failed = len(qa_pairs) - completed
        summary = {
            "success": completed > 0 and failed == 0,
            "source": source,
            "requested": requested,
            "template_count": len(templates),
            "completed": completed,
            "failed": failed,
            "templates": [t.__dict__ for t in templates],
            "results": qa_pairs,
            "trace": trace,
            "batch_dir": str(self._current_batch_dir) if self._current_batch_dir else None,
        }
        self._persist_summary(summary)
        return summary

    def _create_batch_dir(self, prefix: str) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = Path(self.output_dir) if self.output_dir else get_path_service().get_question_dir()
        batch_dir = base / f"{prefix}_{timestamp}"
        batch_dir.mkdir(parents=True, exist_ok=True)
        return batch_dir

    def _persist_summary(self, summary: dict[str, Any]) -> None:
        if self._current_batch_dir is None:
            return
        summary_file = self._current_batch_dir / "summary.json"
        with open(summary_file, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
