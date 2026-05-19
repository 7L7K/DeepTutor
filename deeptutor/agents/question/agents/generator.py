#!/usr/bin/env python
"""
Generator - Generate Q-A pairs from QuestionTemplate in a single LLM call.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from pydantic import BaseModel, Field

from deeptutor.agents.base_agent import BaseAgent
from deeptutor.agents.question.models import QAPair, QuestionTemplate
from deeptutor.core.trace import build_trace_metadata, new_call_id
from deeptutor.runtime.registry.tool_registry import get_tool_registry
from deeptutor.services.prompt.language import append_language_directive


class _GeneratedQuizOptions(BaseModel):
    A: str
    B: str
    C: str
    D: str


class _GeneratedQuizQuestion(BaseModel):
    question_id: str
    question_type: str
    question: str = Field(description="The question stem.")
    options: _GeneratedQuizOptions
    correct_answer: str
    explanation: str


class _GeneratedQuizSet(BaseModel):
    questions: list[_GeneratedQuizQuestion]


class _GeneratedStarterQuizQuestion(BaseModel):
    question_id: str
    question: str = Field(description="The question stem.")
    options: _GeneratedQuizOptions
    correct_answer: str
    concentration: str = ""
    difficulty: str = ""


class _GeneratedStarterQuizSet(BaseModel):
    questions: list[_GeneratedStarterQuizQuestion]


class Generator(BaseAgent):
    """
    Generate a question/answer pair from one template.

    The simplified pipeline injects the user's enabled tools as prompt guidance
    and relies on the knowledge context already prepared upstream.
    """

    def __init__(
        self,
        kb_name: str | None = None,
        language: str = "en",
        tool_flags: dict[str, bool] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            module_name="question",
            agent_name="generator",
            language=language,
            **kwargs,
        )
        self.kb_name = kb_name
        self.tool_flags = tool_flags or {}
        self._tool_registry = get_tool_registry()

    MAX_PREVIOUS_QUESTIONS = 20

    async def process(
        self,
        template: QuestionTemplate,
        user_topic: str = "",
        preference: str = "",
        history_context: str = "",
        previous_questions: list[str] | None = None,
    ) -> QAPair:
        """
        Generate one Q-A pair from a template in a single call.
        """
        available_tools = self._build_available_tools_text()
        knowledge_context = str(template.metadata.get("knowledge_context", "")).strip()
        prev_q_text = self._format_previous_questions(previous_questions)
        payload = await self._generate_payload(
            template=template,
            user_topic=user_topic,
            preference=preference,
            history_context=history_context,
            knowledge_context=knowledge_context,
            available_tools=available_tools,
            previous_questions=prev_q_text,
        )
        payload, validation = await self._validate_and_repair_payload(
            template=template,
            payload=payload,
            user_topic=user_topic,
            preference=preference,
            history_context=history_context,
            knowledge_context=knowledge_context,
            available_tools=available_tools,
            previous_questions=prev_q_text,
        )

        return QAPair(
            question_id=template.question_id,
            question=payload.get("question", ""),
            correct_answer=payload.get("correct_answer", ""),
            explanation=payload.get("explanation", ""),
            question_type=payload.get("question_type", template.question_type),
            options=(payload.get("options") if isinstance(payload.get("options"), dict) else None),
            concentration=template.concentration,
            difficulty=template.difficulty,
            validation=validation,
            metadata={
                "source": template.source,
                "reference_question": template.reference_question,
                "enabled_tools": self._enabled_tool_names(),
                "available_tools": available_tools,
                "knowledge_context": knowledge_context,
            },
        )

    async def process_quiz_set(
        self,
        templates: list[QuestionTemplate],
        user_topic: str = "",
        preference: str = "",
        history_context: str = "",
        generation_api: str | None = None,
    ) -> list[QAPair]:
        """
        Generate a complete quiz set in one structured LLM call, then repair
        only the specific items that fail validation.
        """
        if not templates:
            return []

        available_tools = self._build_available_tools_text()
        raw_set_response, set_payload = await self._generate_quiz_set_payload(
            templates=templates,
            user_topic=user_topic,
            preference=preference,
            history_context=history_context,
            available_tools=available_tools,
            generation_api=generation_api,
        )
        if self._quiz_set_needs_repair(set_payload, templates):
            repaired_payload = await self._repair_quiz_set_payload(
                raw_response=raw_set_response,
                templates=templates,
                user_topic=user_topic,
                preference=preference,
                history_context=history_context,
                available_tools=available_tools,
            )
            if repaired_payload:
                set_payload = repaired_payload
        item_payloads = self._extract_quiz_set_items(set_payload, templates)
        diagnostics = set_payload.get("_diagnostics", {})
        deferred_explanations = bool(
            isinstance(diagnostics, dict) and diagnostics.get("deferred_explanations")
        )

        qa_pairs: list[QAPair] = []
        accepted_questions: list[str] = []
        enabled_tools = self._enabled_tool_names()

        for template, payload in zip(templates, item_payloads):
            knowledge_context = str(template.metadata.get("knowledge_context", "")).strip()
            normalized, validation = await self._validate_and_repair_payload(
                template=template,
                payload=payload,
                user_topic=user_topic,
                preference=preference,
                history_context=history_context,
                knowledge_context=knowledge_context,
                available_tools=available_tools,
                previous_questions=self._format_previous_questions(accepted_questions),
                set_level_seen_questions=accepted_questions,
                allow_deferred_explanation=deferred_explanations,
            )

            question_text = str(normalized.get("question", "") or "").strip()
            if question_text:
                accepted_questions.append(question_text)

            qa_pairs.append(
                QAPair(
                    question_id=template.question_id,
                    question=question_text,
                    correct_answer=str(normalized.get("correct_answer", "") or "").strip(),
                    explanation=str(normalized.get("explanation", "") or "").strip(),
                    question_type=str(
                        normalized.get("question_type", template.question_type)
                    ).strip()
                    or template.question_type,
                    options=(
                        normalized.get("options")
                        if isinstance(normalized.get("options"), dict)
                        else None
                    ),
                    concentration=template.concentration,
                    difficulty=template.difficulty,
                    validation=validation,
                    metadata={
                        "source": template.source,
                        "reference_question": template.reference_question,
                        "enabled_tools": enabled_tools,
                        "available_tools": available_tools,
                        "knowledge_context": knowledge_context,
                        "generation_mode": "quiz_set",
                        "generation_api": diagnostics.get("api")
                        or "chat_completions",
                        "explanation_deferred": deferred_explanations,
                    },
                )
            )

        return qa_pairs

    def _build_available_tools_text(self) -> str:
        enabled_tools = self._enabled_tool_names()
        if not enabled_tools:
            return "(no tools available)"
        return self._tool_registry.build_prompt_text(
            enabled_tools,
            format="list",
            language=self.language,
            kb_name=self.kb_name or "",
        )

    async def _generate_quiz_set_payload(
        self,
        templates: list[QuestionTemplate],
        user_topic: str,
        preference: str,
        history_context: str,
        available_tools: str,
        generation_api: str | None = None,
    ) -> tuple[str, dict[str, Any]]:
        system_prompt = self.get_prompt("system", "")
        user_prompt_template = self.get_prompt("generate_set", "")
        if not user_prompt_template:
            user_prompt_template = (
                "Templates:\n{templates}\n\n"
                "User topic: {user_topic}\n"
                "Preference: {preference}\n"
                "Conversation context: {history_context}\n"
                "Knowledge context by template:\n{knowledge_context_bundle}\n"
                "Enabled tools: {available_tools}\n\n"
                'Return JSON {"questions":[{"question_id":"","question_type":"","question":"","options":{},"correct_answer":"","explanation":""}]}'
            )

        template_dicts = [
            self._strip_template_knowledge_context(template) for template in templates
        ]
        user_prompt = user_prompt_template.format(
            templates=json.dumps(template_dicts, ensure_ascii=False, indent=2),
            user_topic=user_topic or "(none)",
            preference=preference or "(none)",
            history_context=history_context or "(none)",
            knowledge_context_bundle=self._format_template_knowledge_contexts(templates),
            available_tools=available_tools,
        )

        if self._should_use_quiz_responses_api(generation_api):
            try:
                if self._responses_profile(generation_api) == "minimal":
                    return await self._generate_starter_quiz_set_payload_with_responses(
                        templates=templates,
                        user_topic=user_topic,
                        preference=preference,
                        history_context=history_context,
                    )
                return await self._generate_quiz_set_payload_with_responses(
                    templates=templates,
                    user_prompt=user_prompt,
                    system_prompt=system_prompt or "",
                )
            except Exception as exc:
                self.logger.warning(f"Quiz Responses generation failed; falling back to chat completions: {exc}")

        chunks: list[str] = []
        async for chunk in self.stream_llm(
            user_prompt=user_prompt,
            system_prompt=system_prompt or "",
            response_format={"type": "json_object"},
            stage="generator_build_quiz_set",
            trace_meta=build_trace_metadata(
                call_id=new_call_id("quiz-set"),
                phase="generation",
                label=f"Generate quiz set ({len(templates)} questions)",
                call_kind="llm_generation",
                trace_id="quiz-set",
            ),
            max_tokens=max(4096, min(12000, len(templates) * 900)),
        ):
            chunks.append(chunk)
        raw_response = "".join(chunks)
        return raw_response, self._parse_json_like(raw_response)

    async def _generate_quiz_set_payload_with_responses(
        self,
        *,
        templates: list[QuestionTemplate],
        user_prompt: str,
        system_prompt: str,
    ) -> tuple[str, dict[str, Any]]:
        from deeptutor.services.llm.structured_responses import generate_structured_response

        result = await generate_structured_response(
            model=self.get_model(),
            instructions=system_prompt or "Generate a valid practice quiz JSON set.",
            input_data=user_prompt,
            api_key=self.api_key,
            base_url=self.base_url,
            pydantic_model=_GeneratedQuizSet,
            max_output_tokens=max(2048, min(8000, len(templates) * 650)),
            prompt_cache_key="deeptutor-practice-quiz-v1",
            store=False,
            reasoning_effort=self.get_reasoning_effort(),
        )
        payload = dict(result.parsed)
        usage = result.usage or {}
        input_details = usage.get("input_tokens_details") or {}
        output_details = usage.get("output_tokens_details") or {}
        payload["_diagnostics"] = {
            "api": "responses",
            "model": result.model,
            "latency_ms": round(result.latency_ms, 3),
            "request_id": result.request_id,
            "input_tokens": usage.get("input_tokens"),
            "cached_tokens": input_details.get("cached_tokens"),
            "output_tokens": usage.get("output_tokens"),
            "reasoning_tokens": output_details.get("reasoning_tokens"),
        }
        return result.raw_text, payload

    async def _generate_starter_quiz_set_payload_with_responses(
        self,
        *,
        templates: list[QuestionTemplate],
        user_topic: str,
        preference: str,
        history_context: str,
    ) -> tuple[str, dict[str, Any]]:
        from deeptutor.services.llm.structured_responses import generate_structured_response

        compact_templates = [
            {
                "question_id": template.question_id,
                "concentration": template.concentration,
                "question_type": template.question_type,
                "difficulty": template.difficulty,
                "knowledge_context": str((template.metadata or {}).get("knowledge_context") or "")[:900],
            }
            for template in templates
        ]
        user_prompt = (
            "Generate the first visible page of a Practice quiz.\n"
            "Return exactly one multiple-choice question for each template.\n"
            "Do not generate explanations yet; explanations are deferred until review.\n\n"
            f"Topic: {user_topic or '(none)'}\n"
            f"Preference: {preference or '(none)'}\n"
            f"Conversation context: {history_context or '(none)'}\n"
            f"Templates:\n{json.dumps(compact_templates, ensure_ascii=False)}\n\n"
            "Rules:\n"
            "- Write realistic NCE-style application questions.\n"
            "- Keep stems concise but specific.\n"
            "- Provide exactly four plausible options A-D.\n"
            "- correct_answer must be the correct option key.\n"
            "- Preserve question_id exactly.\n"
        )
        result = await generate_structured_response(
            model=self.get_model(),
            instructions=(
                "You generate fast first-page Practice quiz questions as strict JSON. "
                "Return no prose and no explanations."
            ),
            input_data=user_prompt,
            api_key=self.api_key,
            base_url=self.base_url,
            pydantic_model=_GeneratedStarterQuizSet,
            max_output_tokens=max(1200, min(3600, len(templates) * 430)),
            prompt_cache_key="deeptutor-practice-starter-minimal-v1",
            store=False,
            reasoning_effort=self.get_reasoning_effort(),
        )
        payload = dict(result.parsed)
        for item in payload.get("questions") or []:
            if isinstance(item, dict):
                item["question_type"] = "choice"
                item.setdefault("explanation", "")
        usage = result.usage or {}
        input_details = usage.get("input_tokens_details") or {}
        output_details = usage.get("output_tokens_details") or {}
        payload["_diagnostics"] = {
            "api": "responses_minimal",
            "model": result.model,
            "latency_ms": round(result.latency_ms, 3),
            "request_id": result.request_id,
            "deferred_explanations": True,
            "input_tokens": usage.get("input_tokens"),
            "cached_tokens": input_details.get("cached_tokens"),
            "output_tokens": usage.get("output_tokens"),
            "reasoning_tokens": output_details.get("reasoning_tokens"),
        }
        return result.raw_text, payload

    def _should_use_quiz_responses_api(self, generation_api: str | None = None) -> bool:
        configured = str(generation_api or "").strip().lower()
        if not configured:
            configured = os.getenv("PRACTICE_QUIZ_USE_RESPONSES", "").strip().lower()
        if configured in {"chat", "0", "false", "no", "off"}:
            return False
        if configured in {"responses", "responses_minimal", "responses-starter-minimal", "1", "true", "yes", "on"}:
            return bool(self.api_key)
        return False

    @staticmethod
    def _responses_profile(generation_api: str | None = None) -> str:
        configured = str(generation_api or "").strip().lower()
        if configured in {"responses_minimal", "responses-starter-minimal"}:
            return "minimal"
        return "full"

    async def _repair_quiz_set_payload(
        self,
        raw_response: str,
        templates: list[QuestionTemplate],
        user_topic: str,
        preference: str,
        history_context: str,
        available_tools: str,
    ) -> dict[str, Any]:
        repair_prompt = (
            "You are repairing an invalid full-quiz JSON response.\n\n"
            f"Templates:\n{json.dumps([self._strip_template_knowledge_context(t) for t in templates], ensure_ascii=False, indent=2)}\n\n"
            f"User topic:\n{user_topic or '(none)'}\n\n"
            f"User preference:\n{preference or '(none)'}\n\n"
            f"Conversation context:\n{history_context or '(none)'}\n\n"
            f"Enabled tools:\n{available_tools}\n\n"
            f"Invalid or incomplete quiz-set response:\n{raw_response or '(empty)'}\n\n"
            "Rewrite this as valid JSON for the complete quiz set.\n"
            "Hard rules:\n"
            "- Return exactly one question for each template.\n"
            "- Preserve each template.question_id.\n"
            "- Respect each template.question_type exactly.\n"
            "- For choice questions, provide exactly 4 options (A-D), a correct option key, and a concise explanation.\n"
            "- For written/coding questions, provide no options.\n"
            "- Avoid duplicate or near-duplicate questions across the set.\n"
            "- Return JSON only in the form {\"questions\": [...]}.\n"
        )

        chunks: list[str] = []
        async for chunk in self.stream_llm(
            user_prompt=repair_prompt,
            system_prompt="You repair malformed full-quiz JSON and return valid JSON only.",
            response_format={"type": "json_object"},
            stage="generator_repair_quiz_set",
            trace_meta=build_trace_metadata(
                call_id=new_call_id("quiz-set-repair"),
                phase="generation",
                label="Repair quiz set format",
                call_kind="llm_generation",
                trace_id="quiz-set",
            ),
            max_tokens=max(4096, min(12000, len(templates) * 900)),
        ):
            chunks.append(chunk)
        return self._parse_json_like("".join(chunks))

    async def _generate_payload(
        self,
        template: QuestionTemplate,
        user_topic: str,
        preference: str,
        history_context: str,
        knowledge_context: str,
        available_tools: str,
        previous_questions: str = "",
    ) -> dict[str, Any]:
        system_prompt = append_language_directive(
            self.get_prompt("system", ""),
            self.language,
        )
        user_prompt_template = self.get_prompt("generate", "")
        if not user_prompt_template:
            user_prompt_template = (
                "Template: {template}\n"
                "User topic: {user_topic}\n"
                "Preference: {preference}\n"
                "Conversation context: {history_context}\n"
                "Previously generated questions (do not repeat):\n{previous_questions}\n"
                "Knowledge context: {knowledge_context}\n"
                "Enabled tools: {available_tools}\n\n"
                'Return JSON {{"question_type":"","question":"","options":{{}},"correct_answer":"","explanation":""}}'
            )

        template_dict = self._strip_template_knowledge_context(template)

        user_prompt = user_prompt_template.format(
            template=json.dumps(template_dict, ensure_ascii=False, indent=2),
            user_topic=user_topic,
            preference=preference or "(none)",
            history_context=history_context or "(none)",
            previous_questions=previous_questions or "(none)",
            knowledge_context=knowledge_context or "(none)",
            available_tools=available_tools,
        )

        _chunks: list[str] = []
        async for _c in self.stream_llm(
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            response_format={"type": "json_object"},
            stage="generator_build_qa",
            trace_meta=build_trace_metadata(
                call_id=new_call_id(f"quiz-{template.question_id}"),
                phase="generation",
                label=f"Generate {template.question_id}",
                call_kind="llm_generation",
                trace_id=template.question_id,
                question_id=template.question_id,
            ),
            max_tokens=900,
        ):
            _chunks.append(_c)
        response = "".join(_chunks)
        payload = self._parse_json_like(response)

        if "question" not in payload or not str(payload.get("question", "")).strip():
            payload["question"] = (
                f"Based on {template.concentration}, answer this {template.difficulty} "
                f"{template.question_type} question."
            )
        if "correct_answer" not in payload:
            payload["correct_answer"] = "N/A"
        if "explanation" not in payload:
            payload["explanation"] = "N/A"
        if "question_type" not in payload:
            payload["question_type"] = template.question_type

        return payload

    async def _validate_and_repair_payload(
        self,
        template: QuestionTemplate,
        payload: dict[str, Any],
        user_topic: str,
        preference: str,
        history_context: str,
        knowledge_context: str,
        available_tools: str,
        previous_questions: str = "",
        set_level_seen_questions: list[str] | None = None,
        allow_deferred_explanation: bool = False,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        expected_type = self._normalize_question_type(template.question_type)
        normalized = self._normalize_payload_shape(expected_type, payload)
        issues = self._collect_payload_issues(
            expected_type,
            normalized,
            seen_questions=set_level_seen_questions or [],
            allow_deferred_explanation=allow_deferred_explanation,
        )
        repaired = False

        if issues:
            repaired_payload = await self._repair_payload(
                template=template,
                payload=normalized,
                issues=issues,
                user_topic=user_topic,
                preference=preference,
                history_context=history_context,
                knowledge_context=knowledge_context,
                available_tools=available_tools,
                previous_questions=previous_questions,
            )
            if repaired_payload:
                candidate = self._normalize_payload_shape(expected_type, repaired_payload)
                candidate_issues = self._collect_payload_issues(
                    expected_type,
                    candidate,
                    seen_questions=set_level_seen_questions or [],
                    allow_deferred_explanation=allow_deferred_explanation,
                )
                if not candidate_issues or len(candidate_issues) <= len(issues):
                    normalized = candidate
                    issues = candidate_issues
                    repaired = True

        fallback_generated = False
        original_issues = list(issues)
        if issues and expected_type == "choice":
            normalized = self._build_choice_fallback_payload(template)
            issues = []
            fallback_generated = True

        validation = {
            "requested_question_type": expected_type,
            "schema_ok": not issues,
            "repaired": repaired,
            "issues": issues,
            "explanation_deferred": allow_deferred_explanation,
        }
        if fallback_generated:
            validation["fallback_generated"] = True
            validation["fallback_reason"] = "invalid_choice_payload_after_repair"
            validation["fallback_from_issues"] = original_issues
        return normalized, validation

    @staticmethod
    def _build_choice_fallback_payload(template: QuestionTemplate) -> dict[str, Any]:
        concentration = str(template.concentration or "the counseling scenario").strip()
        difficulty = str(template.difficulty or "practice").strip()
        answer_key = ("A", "B", "C", "D")[
            sum(ord(char) for char in (template.question_id or concentration)) % 4
        ]
        correct_text = (
            "Clarify the client's concern, apply the relevant ethical and clinical "
            "standard, document the rationale, and seek consultation when needed."
        )
        distractors = [
            "Give directive advice before assessing context or client goals.",
            "Ignore documentation and rely only on memory after the session.",
            "Prioritize speed over informed consent, client welfare, and consultation.",
        ]
        options: dict[str, str] = {}
        distractor_index = 0
        for key in ("A", "B", "C", "D"):
            if key == answer_key:
                options[key] = correct_text
            else:
                options[key] = distractors[distractor_index]
                distractor_index += 1

        return {
            "question_type": "choice",
            "question": (
                f"A counselor is addressing {concentration}. Which {difficulty} "
                "response best reflects sound counseling practice?"
            ),
            "options": options,
            "correct_answer": answer_key,
            "explanation": (
                f"Option {answer_key} is best because it protects client welfare, "
                "uses the relevant standard, preserves documentation, and brings in "
                "consultation when the situation is complex."
            ),
        }

    async def _repair_payload(
        self,
        template: QuestionTemplate,
        payload: dict[str, Any],
        issues: list[str],
        user_topic: str,
        preference: str,
        history_context: str,
        knowledge_context: str,
        available_tools: str,
        previous_questions: str = "",
    ) -> dict[str, Any]:
        expected_type = self._normalize_question_type(template.question_type)
        template_dict = self._strip_template_knowledge_context(template)
        repair_prompt = (
            "You are repairing an invalid quiz question JSON.\n\n"
            f"QuestionTemplate:\n{json.dumps(template_dict, ensure_ascii=False, indent=2)}\n\n"
            f"User topic:\n{user_topic or '(none)'}\n\n"
            f"User preference:\n{preference or '(none)'}\n\n"
            f"Conversation context:\n{history_context or '(none)'}\n\n"
            f"Previously generated questions:\n{previous_questions or '(none)'}\n\n"
            f"Knowledge context:\n{knowledge_context or '(none)'}\n\n"
            f"Enabled tools:\n{available_tools}\n\n"
            f"Invalid payload:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
            f"Detected issues:\n{json.dumps(issues, ensure_ascii=False)}\n\n"
            f"Rewrite the payload so it strictly matches question_type='{expected_type}'.\n"
            "Hard rules:\n"
            "- Keep the same concentration and difficulty intent.\n"
            "- question_type must exactly match the template.\n"
            "- If question_type is choice: provide exactly 4 options (A-D), and correct_answer must be the correct option key.\n"
            "- If question_type is written: do not provide options, and the learner must write an explanation or short answer.\n"
            "- If question_type is coding: do not provide options, and the learner must write code, pseudocode, or an algorithmic solution.\n"
            "- For written/coding questions, never ask the learner to select, choose, or pick among options.\n"
            "- Return JSON only with keys: question_type, question, options, correct_answer, explanation.\n"
        )

        _chunks: list[str] = []
        async for _c in self.stream_llm(
            user_prompt=repair_prompt,
            system_prompt=append_language_directive(
                "You fix malformed quiz payloads and return valid JSON only.",
                self.language,
            ),
            response_format={"type": "json_object"},
            stage="generator_repair_qa",
            trace_meta=build_trace_metadata(
                call_id=new_call_id(f"quiz-repair-{template.question_id}"),
                phase="generation",
                label=f"Repair question {self._humanize_question_id(template.question_id)} format",
                call_kind="llm_generation",
                trace_id=template.question_id,
                question_id=template.question_id,
            ),
        ):
            _chunks.append(_c)
        response = "".join(_chunks)
        return self._parse_json_like(response)

    @classmethod
    def _normalize_question_type(cls, question_type: str) -> str:
        normalized = str(question_type or "").strip().lower()
        return normalized if normalized in {"choice", "written", "coding"} else "written"

    @classmethod
    def _normalize_payload_shape(
        cls,
        expected_type: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        normalized = dict(payload or {})
        normalized["question_type"] = expected_type
        normalized["question"] = str(normalized.get("question", "") or "").strip()
        normalized["correct_answer"] = str(normalized.get("correct_answer", "") or "").strip()
        normalized["explanation"] = str(normalized.get("explanation", "") or "").strip()

        raw_options = normalized.get("options")
        if expected_type == "choice":
            clean_options: dict[str, str] = {}
            if isinstance(raw_options, dict):
                for key, value in raw_options.items():
                    option_key = str(key or "").strip().upper()[:1]
                    option_value = str(value or "").strip()
                    if option_key in {"A", "B", "C", "D"} and option_value:
                        clean_options[option_key] = option_value
            normalized["options"] = clean_options if clean_options else None
            if normalized["correct_answer"] and clean_options:
                answer_upper = normalized["correct_answer"].upper()
                if answer_upper in clean_options:
                    normalized["correct_answer"] = answer_upper
                else:
                    for key, value in clean_options.items():
                        if normalized["correct_answer"].strip().lower() == value.lower():
                            normalized["correct_answer"] = key
                            break
        else:
            normalized["options"] = None

        return normalized

    @classmethod
    def _collect_payload_issues(
        cls,
        expected_type: str,
        payload: dict[str, Any],
        seen_questions: list[str] | None = None,
        allow_deferred_explanation: bool = False,
    ) -> list[str]:
        issues: list[str] = []
        question = str(payload.get("question", "") or "")
        correct_answer = str(payload.get("correct_answer", "") or "").strip()
        options = payload.get("options")
        normalized_question = cls._normalize_question_text(question)

        if not question:
            issues.append("missing_question")
        elif normalized_question and any(
            normalized_question == cls._normalize_question_text(existing)
            for existing in (seen_questions or [])
        ):
            issues.append("duplicate_question")

        if expected_type == "choice":
            option_keys = set(options.keys()) if isinstance(options, dict) else set()
            if not option_keys:
                issues.append("choice_missing_options")
            elif option_keys != {"A", "B", "C", "D"}:
                issues.append("choice_options_must_be_a_to_d")
            if correct_answer.upper() not in {"A", "B", "C", "D"}:
                issues.append("choice_correct_answer_must_be_option_key")
        else:
            if cls._payload_looks_like_choice(
                question=question, correct_answer=correct_answer, options=options
            ):
                issues.append("non_choice_payload_looks_like_multiple_choice")

        if not correct_answer:
            issues.append("missing_correct_answer")
        if not allow_deferred_explanation and not str(payload.get("explanation", "") or "").strip():
            issues.append("missing_explanation")
        return issues

    @staticmethod
    def _normalize_question_text(question: str) -> str:
        return re.sub(r"\W+", " ", str(question or "").strip().lower()).strip()

    @staticmethod
    def _payload_looks_like_choice(
        question: str,
        correct_answer: str,
        options: Any,
    ) -> bool:
        if isinstance(options, dict) and bool(options):
            return True
        lowered = question.lower()
        if re.search(
            r"\b(select|choose|pick|which of the following|which option|multiple[- ]choice)\b",
            lowered,
        ):
            return True
        if re.search(r"(^|\n)\s*[A-D][\.\):]\s+", question):
            return True
        return correct_answer.upper() in {"A", "B", "C", "D"}

    @staticmethod
    def _humanize_question_id(question_id: str) -> str:
        match = re.fullmatch(r"q_(\d+)", str(question_id or "").strip().lower())
        if match:
            return f"question {match.group(1)}"
        return str(question_id or "question").strip() or "question"

    def _is_tool_enabled(self, tool_name: str) -> bool:
        aliases = {
            "rag": ["rag", "rag_tool"],
            "web_search": ["web_search"],
            "code_execution": ["code_execution", "write_code"],
        }
        keys = aliases.get(tool_name, [tool_name])
        present = [key for key in keys if key in self.tool_flags]
        if not present:
            return True
        return any(bool(self.tool_flags.get(key)) for key in present)

    def _enabled_tool_names(self) -> list[str]:
        enabled_tools: list[str] = []
        if self._is_tool_enabled("rag"):
            enabled_tools.append("rag")
        if self._is_tool_enabled("web_search"):
            enabled_tools.append("web_search")
        if self._is_tool_enabled("code_execution"):
            enabled_tools.append("code_execution")
        return enabled_tools

    @staticmethod
    def _strip_template_knowledge_context(template: QuestionTemplate) -> dict[str, Any]:
        """Strip knowledge_context from template metadata to avoid prompt duplication."""
        template_dict = template.__dict__.copy()
        if isinstance(template_dict.get("metadata"), dict):
            template_dict["metadata"] = {
                k: v for k, v in template_dict["metadata"].items() if k != "knowledge_context"
            }
        return template_dict

    @staticmethod
    def _extract_quiz_set_items(
        payload: dict[str, Any],
        templates: list[QuestionTemplate],
    ) -> list[dict[str, Any]]:
        raw_items = payload.get("questions")
        if not isinstance(raw_items, list):
            raw_items = []

        by_id: dict[str, dict[str, Any]] = {}
        ordered: list[dict[str, Any]] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            question_id = str(item.get("question_id", "") or "").strip()
            if question_id:
                by_id[question_id] = item
            ordered.append(item)

        extracted: list[dict[str, Any]] = []
        for index, template in enumerate(templates):
            payload_item = by_id.get(template.question_id)
            if payload_item is None and index < len(ordered):
                payload_item = ordered[index]
            extracted.append(payload_item if isinstance(payload_item, dict) else {})
        return extracted

    @classmethod
    def _quiz_set_needs_repair(
        cls,
        payload: dict[str, Any],
        templates: list[QuestionTemplate],
    ) -> bool:
        items = cls._extract_quiz_set_items(payload, templates)
        non_empty = sum(1 for item in items if isinstance(item, dict) and item)
        if non_empty < len(templates):
            return True
        return False

    @staticmethod
    def _format_template_knowledge_contexts(
        templates: list[QuestionTemplate],
    ) -> str:
        sections: list[str] = []
        for template in templates:
            knowledge_context = str(template.metadata.get("knowledge_context", "")).strip()
            if not knowledge_context:
                continue
            sections.append(
                f"{template.question_id} ({template.concentration}):\n{knowledge_context}"
            )
        return "\n\n".join(sections) if sections else "(none)"

    @classmethod
    def _format_previous_questions(cls, questions: list[str] | None) -> str:
        if not questions:
            return ""
        capped = questions[-cls.MAX_PREVIOUS_QUESTIONS :]
        return "\n".join(f"{i}. {q}" for i, q in enumerate(capped, 1))

    @staticmethod
    def _parse_json_like(content: str) -> dict[str, Any]:
        if not content or not content.strip():
            return {}

        cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]", "", content.strip())
        block_match = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL)
        if block_match:
            cleaned = block_match.group(1).strip()

        try:
            payload = json.loads(cleaned)
            return payload if isinstance(payload, dict) else {}
        except Exception:
            pass

        obj_match = re.search(r"\{[\s\S]*\}", cleaned)
        if obj_match:
            try:
                payload = json.loads(obj_match.group(0))
                return payload if isinstance(payload, dict) else {}
            except Exception:
                return {}
        return {}
