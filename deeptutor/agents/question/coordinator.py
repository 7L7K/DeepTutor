#!/usr/bin/env python
"""
Question Coordinator

Simplified architecture:
1) Template generation in batches (max 5 per batch)
2) Single-pass question generation per template
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
import json
import os
from pathlib import Path
import time
from typing import Any

from deeptutor.agents.question.agents.generator import Generator
from deeptutor.agents.question.agents.idea_agent import BATCH_SIZE, IdeaAgent
from deeptutor.agents.question.models import QAPair, QuestionTemplate
from deeptutor.logging import Logger, get_logger
from deeptutor.services.config import PROJECT_ROOT, load_config_with_main
from deeptutor.services.path_service import get_path_service
from deeptutor.tools.question.pdf_parser import parse_pdf_with_mineru
from deeptutor.tools.question.question_extractor import extract_questions_from_paper


PROGRESSIVE_QUIZ_FIRST_BATCH = 3


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
        self.logger: Logger = get_logger("QuestionCoordinator", log_dir=log_dir)

        question_cfg = self.config.get("capabilities", {}).get("question", {})
        generation_cfg = question_cfg.get("generation", {})
        default_tool_flags = generation_cfg.get(
            "tools",
            {"web_search": True, "rag": True, "code_execution": True},
        )
        self.tool_flags = (
            tool_flags_override
            if isinstance(tool_flags_override, dict)
            else default_tool_flags
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
    ) -> dict[str, Any]:
        started_at = time.perf_counter()
        self._current_batch_dir = self._create_batch_dir("custom")
        requested = max(1, int(num_questions or 1))
        idea_agent = self._create_idea_agent()
        templates: list[QuestionTemplate] = []
        batch_trace: list[dict[str, Any]] = []
        existing_concentrations: list[str] = []

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

        batch_number = 0
        while len(templates) < requested:
            batch_number += 1
            batch_size = min(BATCH_SIZE, requested - len(templates))
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
                self.logger.warning(
                    "Template generation returned an empty batch; stopping early."
                )
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
        qa_pairs = await self._generation_loop(
            templates=templates[:requested],
            user_topic=user_topic,
            preference=preference,
            history_context=history_context,
        )
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
            success = not bool((qa_pair.metadata or {}).get("error")) and bool(
                (qa_pair.validation or {}).get("schema_ok", True)
            )
            result = {
                "template": template.__dict__,
                "qa_pair": qa_pair.__dict__,
                "success": success,
            }
            results.append(result)
            await self._send_ws_update(
                "result",
                {
                    "question_id": template.question_id,
                    "index": idx - 1,
                    "question": qa_pair.__dict__,
                    "success": success,
                },
            )

        accepted_questions: list[str] = []
        started_at = time.perf_counter()
        first_ready_at: float | None = None
        progressive_count = 0 if self._should_use_fast_kb_set_generation(total) else min(
            PROGRESSIVE_QUIZ_FIRST_BATCH,
            total,
        )
        if progressive_count == 0 and total:
            self.logger.info(
                f"Using fast KB-backed quiz-set generation: kb={self.kb_name} questions={total}"
            )

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
        if remaining_templates:
            await self._send_ws_update(
                "progress",
                {
                    "stage": "generation",
                    "status": "building_remaining_set",
                    "current": len(results),
                    "total": total,
                },
            )
            remaining_history_context = history_context
            if accepted_questions:
                remaining_history_context = (
                    f"{history_context}\n\nAlready generated questions to avoid duplicating:\n"
                    + "\n".join(f"- {question}" for question in accepted_questions)
                ).strip()
            try:
                qa_pairs = await generator.process_quiz_set(
                    templates=remaining_templates,
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
                    for template in remaining_templates
                ]

            await self._send_ws_update(
                "progress",
                {
                    "stage": "generation",
                    "status": "validating_set",
                    "current": len(results),
                    "total": total,
                },
            )
            for offset, (template, qa_pair) in enumerate(
                zip(remaining_templates, qa_pairs, strict=False),
                progressive_count + 1,
            ):
                await emit_result(offset, template, qa_pair)

        await self._send_ws_update(
            "progress",
            {"stage": "complete", "completed": len(results), "total": total},
        )
        self.logger.info(
            f"Quiz generation completed: first_ready={first_ready_at or 0.0:.2f}s "
            f"total={time.perf_counter() - started_at:.2f}s questions={len(results)}"
        )
        return results

    def _should_use_fast_kb_set_generation(self, total_questions: int) -> bool:
        """Skip per-question progressive calls for KB-backed quizzes.

        With a selected KB, retrieval already happened during ideation and each
        template carries its knowledge context. Generating the full set in one
        structured call avoids the slow first-three single-call warmup that made
        KB-backed practice feel stuck on later questions.
        """
        return bool(self.kb_name) and total_questions > 1

    async def _parse_exam_to_templates(
        self,
        exam_paper_path: str,
        max_questions: int,
        paper_mode: str,
    ) -> tuple[list[QuestionTemplate], dict[str, Any]]:
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
            extract_success = extract_questions_from_paper(
                str(working_dir), output_dir=None
            )
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
        base = (
            Path(self.output_dir)
            if self.output_dir
            else get_path_service().get_question_dir()
        )
        batch_dir = base / f"{prefix}_{timestamp}"
        batch_dir.mkdir(parents=True, exist_ok=True)
        return batch_dir

    def _persist_summary(self, summary: dict[str, Any]) -> None:
        if self._current_batch_dir is None:
            return
        summary_file = self._current_batch_dir / "summary.json"
        with open(summary_file, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
