#!/usr/bin/env python
"""
Single-call grading agent for answers submitted through the interactive quiz UI.
"""

from __future__ import annotations

from collections import defaultdict
from typing import cast
import re
from typing import Any

from deeptutor.agents.base_agent import BaseAgent
from deeptutor.core.trace import build_trace_metadata, new_call_id
from deeptutor.utils.json_parser import parse_json_response


QuizSubmissionResult = dict[str, Any]
_ANSWER_PATTERN = re.compile(r"(\d+)\s*[-:.)]?\s*([A-Za-z])")


class QuizSubmissionAgent(BaseAgent):
    """Grade a full quiz submission in one LLM call."""

    def __init__(self, language: str = "en", **kwargs: Any) -> None:
        super().__init__(
            module_name="question",
            agent_name="quiz_submission_agent",
            language=language,
            **kwargs,
        )

    async def process(
        self,
        *,
        submitted_answers: str,
        quiz_context: dict[str, Any],
        history_context: str = "",
    ) -> QuizSubmissionResult:
        parsed_answers = self._extract_answer_map(quiz_context) or self._parse_submitted_answers(
            submitted_answers=submitted_answers,
            question_count=len(quiz_context.get("questions") or []),
        )
        allow_incomplete = bool(quiz_context.get("allow_incomplete"))
        missing_question_numbers = self._find_missing_question_numbers(
            parsed_answers=parsed_answers,
            question_count=len(quiz_context.get("questions") or []),
        )
        if missing_question_numbers and not allow_incomplete:
            response = self._missing_answer_response(missing_question_numbers)
            return {
                "response": response,
                "structured_result": {
                    "submission_state": "incomplete",
                    "missing_question_numbers": missing_question_numbers,
                    "score": {
                        "correct": 0,
                        "total": len(quiz_context.get("questions") or []),
                        "percent": 0,
                    },
                    "domain_breakdown": [],
                    "question_results": [],
                },
            }

        system_prompt = self._system_prompt()
        user_prompt = self._user_prompt(
            submitted_answers=submitted_answers,
            parsed_answers=parsed_answers,
            quiz_context=quiz_context,
            history_context=history_context,
        )

        chunks: list[str] = []
        async for chunk in self.stream_llm(
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            stage="quiz_submission",
            trace_meta=build_trace_metadata(
                call_id=new_call_id("quiz-submission"),
                phase="generation",
                label="Grade quiz submission",
                call_kind="llm_generation",
                trace_id="quiz-submission",
            ),
            response_format={"type": "json_object"},
        ):
            chunks.append(chunk)
        payload = parse_json_response("".join(chunks), logger_instance=self.logger, fallback={})
        structured_result = self._normalize_model_result(
            payload if isinstance(payload, dict) else {},
            quiz_context=quiz_context,
            parsed_answers=parsed_answers,
        )
        return {
            "response": self._render_learner_response(structured_result),
            "structured_result": structured_result,
        }

    def _missing_answer_response(self, missing_question_numbers: list[int]) -> str:
        joined = ", ".join(str(number) for number in missing_question_numbers)
        if self.language.lower().startswith("zh"):
            return f"我还缺少这些题号的答案：{joined}。请只补充这些题目的答案。"
        return f"I’m still missing answers for question(s): {joined}. Please send just those missing items."

    def _system_prompt(self) -> str:
        if self.language.lower().startswith("zh"):
            return (
                "你正在批改学生通过交互式测验界面提交的答案。"
                "请直接面向学生作答，不要暴露内部流程。"
                "先判断提交是否完整；如果不完整，只说明缺少哪些题号。"
                "如果完整，则逐题推理答案并评分，给出总分、领域总结和清晰解释。"
            )
        return (
            "You are grading answers submitted through an interactive quiz UI. "
            "Reply directly to the learner and do not mention internal processing. "
            "First determine whether the submission is complete; if not, ask only for the missing question numbers. "
            "If it is complete, solve each question, score the submission, provide a domain-oriented summary when possible, "
            "and explain each item clearly."
        )

    def _user_prompt(
        self,
        *,
        submitted_answers: str,
        parsed_answers: dict[int, str],
        quiz_context: dict[str, Any],
        history_context: str,
    ) -> str:
        quiz_text = self._render_quiz_context(quiz_context)
        answer_lines = [
            f"Q{index}: {answer}"
            for index, answer in sorted(parsed_answers.items())
        ]
        answers_text = "\n".join(answer_lines) if answer_lines else submitted_answers.strip() or "(empty)"
        history_text = history_context.strip() or "(none)"

        if self.language.lower().startswith("zh"):
            return (
                f"学生提交答案：\n{answers_text}\n\n"
                f"测验内容：\n{quiz_text}\n\n"
                f"近期上下文：\n{history_text}\n\n"
                "请返回一个 JSON 对象，不要返回 Markdown 或代码块。字段要求：\n"
                '1. `overall_summary`: 1-2 句给学生的总体反馈。\n'
                '2. `question_results`: 数组，必须覆盖每一道题，并按原题顺序返回。\n'
                "3. 每个 question_result 至少包含：\n"
                "   - `question_id`\n"
                "   - `correct_answer`\n"
                "   - `is_correct`\n"
                "   - `is_answered`\n"
                "   - `domain`\n"
                "   - `explanation`（1-2 句，简洁完整）\n"
                "   - `coaching_note`（可选，1 句指出学生易错点）\n"
                "4. 领域名称尽量稳定且简洁，例如 Helping Relationships。\n"
                "5. 空白答案要标记为未作答且判错。\n"
                "6. 只返回 JSON。"
            )
        return (
            f"Learner submission:\n{answers_text}\n\n"
            f"Quiz:\n{quiz_text}\n\n"
            f"Recent context:\n{history_text}\n\n"
            "Return a JSON object only. Do not return markdown or code fences.\n"
            "Required fields:\n"
            '1. `overall_summary`: 1-2 learner-facing sentences summarizing performance.\n'
            '2. `question_results`: an array with one item for every quiz question, in the original order.\n'
            "3. Each `question_results` item must include:\n"
            "   - `question_id`\n"
            "   - `correct_answer`\n"
            "   - `is_correct`\n"
            "   - `is_answered`\n"
            "   - `domain`\n"
            "   - `explanation` (compact but complete, 1-2 sentences)\n"
            "   - `coaching_note` (optional, one short sentence about the likely misconception)\n"
            "4. Keep domain labels stable and short when possible.\n"
            "5. Treat blank answers as unanswered and incorrect.\n"
            "6. Return valid JSON only."
        )

    @staticmethod
    def _parse_submitted_answers(
        *,
        submitted_answers: str,
        question_count: int,
    ) -> dict[int, str]:
        parsed: dict[int, str] = {}
        for match in _ANSWER_PATTERN.finditer(submitted_answers):
            try:
                index = int(match.group(1))
            except ValueError:
                continue
            if not 1 <= index <= question_count:
                continue
            answer = match.group(2).strip()
            if not answer:
                continue
            parsed[index] = answer
        return parsed

    @staticmethod
    def _extract_answer_map(quiz_context: dict[str, Any]) -> dict[int, str]:
        raw_answer_map = quiz_context.get("answer_map") or []
        if not isinstance(raw_answer_map, list):
            return {}
        parsed: dict[int, str] = {}
        for item in raw_answer_map:
            if not isinstance(item, dict):
                continue
            try:
                index = int(item.get("index") or 0)
            except (TypeError, ValueError):
                continue
            answer = str(item.get("answer", "") or "").strip()
            if index > 0 and answer:
                parsed[index] = answer
        return parsed

    @staticmethod
    def _find_missing_question_numbers(
        *,
        parsed_answers: dict[int, str],
        question_count: int,
    ) -> list[int]:
        return [index for index in range(1, question_count + 1) if index not in parsed_answers]

    @staticmethod
    def _render_quiz_context(quiz_context: dict[str, Any]) -> str:
        title = str(quiz_context.get("title", "") or "").strip()
        intro = str(quiz_context.get("intro", "") or "").strip()
        questions = quiz_context.get("questions") or []

        lines: list[str] = []
        if title:
            lines.extend(["Title:", title, ""])
        if intro:
            lines.extend(["Intro:", intro, ""])

        lines.append("Questions:")
        if isinstance(questions, list):
            for index, question in enumerate(questions, start=1):
                if not isinstance(question, dict):
                    continue
                prompt = str(question.get("question", "") or "").strip()
                if not prompt:
                    continue
                question_id = str(question.get("question_id", "") or "").strip() or f"question_{index}"
                lines.append(f"{index}. [{question_id}] {prompt}")
                options = question.get("options") or {}
                if isinstance(options, dict):
                    for key, value in options.items():
                        if str(value or "").strip():
                            lines.append(f"   {str(key).strip().upper()[:1]}. {str(value).strip()}")
        return "\n".join(lines).strip()

    def _normalize_model_result(
        self,
        payload: dict[str, Any],
        *,
        quiz_context: dict[str, Any],
        parsed_answers: dict[int, str],
    ) -> dict[str, Any]:
        questions = quiz_context.get("questions") or []
        question_results_raw = payload.get("question_results") or []
        result_lookup = self._index_question_results(question_results_raw)

        normalized_question_results: list[dict[str, Any]] = []
        for index, question in enumerate(questions, start=1):
            if not isinstance(question, dict):
                continue
            question_id = str(question.get("question_id", "") or "").strip() or f"question_{index}"
            model_item = result_lookup.get(question_id) or result_lookup.get(str(index)) or {}
            if not isinstance(model_item, dict):
                model_item = {}
            user_answer = parsed_answers.get(index, "").strip()
            options = question.get("options")
            normalized_options = (
                {
                    str(key).strip().upper()[:1]: str(value or "").strip()
                    for key, value in options.items()
                    if str(value or "").strip()
                }
                if isinstance(options, dict)
                else {}
            )
            correct_answer = str(
                model_item.get("correct_answer")
                or question.get("correct_answer")
                or ""
            ).strip()
            is_correct = self._resolve_is_correct(
                provided=model_item.get("is_correct"),
                question_type=str(question.get("question_type") or "choice"),
                user_answer=user_answer,
                correct_answer=correct_answer,
                options=normalized_options,
            )
            normalized_question_results.append(
                {
                    "question_id": question_id,
                    "display_order": index,
                    "question_text": str(question.get("question", "") or "").strip(),
                    "question_type": str(question.get("question_type") or "choice"),
                    "options": normalized_options,
                    "user_answer": user_answer,
                    "correct_answer": correct_answer,
                    "is_correct": is_correct,
                    "is_answered": self._resolve_is_answered(
                        provided=model_item.get("is_answered"),
                        user_answer=user_answer,
                    ),
                    "explanation": str(
                        model_item.get("explanation")
                        or question.get("explanation")
                        or ""
                    ).strip(),
                    "coaching_note": str(model_item.get("coaching_note") or "").strip(),
                    "domain": str(
                        model_item.get("domain")
                        or question.get("domain")
                        or question.get("concentration")
                        or ""
                    ).strip(),
                    "difficulty": str(
                        model_item.get("difficulty")
                        or question.get("difficulty")
                        or ""
                    ).strip(),
                }
            )

        score = self._build_score(normalized_question_results)
        domain_breakdown = self._build_domain_breakdown(normalized_question_results)
        summary = str(payload.get("overall_summary") or "").strip()
        return {
            "submission_state": "graded",
            "overall_summary": summary,
            "missing_question_numbers": [],
            "score": score,
            "domain_breakdown": domain_breakdown,
            "question_results": normalized_question_results,
        }

    @staticmethod
    def _index_question_results(raw_results: Any) -> dict[str, dict[str, Any]]:
        lookup: dict[str, dict[str, Any]] = {}
        if not isinstance(raw_results, list):
            return lookup
        for index, item in enumerate(raw_results, start=1):
            if not isinstance(item, dict):
                continue
            question_id = str(item.get("question_id") or "").strip()
            question_number = str(item.get("question_number") or item.get("display_order") or index)
            if question_id:
                lookup[question_id] = item
            lookup.setdefault(question_number, item)
        return lookup

    @staticmethod
    def _resolve_is_correct(
        *,
        provided: Any,
        question_type: str,
        user_answer: str,
        correct_answer: str,
        options: dict[str, str],
    ) -> bool:
        if isinstance(provided, bool):
            return provided
        if not user_answer or not correct_answer:
            return False
        if question_type == "choice" or options:
            return QuizSubmissionAgent._normalize_choice_answer(
                user_answer,
                options,
            ) == QuizSubmissionAgent._normalize_choice_answer(correct_answer, options)
        return user_answer.strip().lower() == correct_answer.strip().lower()

    @staticmethod
    def _resolve_is_answered(*, provided: Any, user_answer: str) -> bool:
        if isinstance(provided, bool):
            return provided
        return bool(user_answer.strip())

    @staticmethod
    def _normalize_choice_answer(answer: str, options: dict[str, str]) -> str:
        cleaned = answer.strip()
        if not cleaned:
            return ""
        upper = cleaned.upper()
        if upper[:1] in options:
            return upper[:1]
        normalized = cleaned.lower()
        for key, value in options.items():
            if normalized == str(value or "").strip().lower():
                return key
        return upper[:1]

    @staticmethod
    def _build_score(question_results: list[dict[str, Any]]) -> dict[str, Any]:
        total = len(question_results)
        correct = sum(1 for item in question_results if bool(item.get("is_correct")))
        percent = round((correct / total) * 100, 2) if total else 0.0
        return {"correct": correct, "total": total, "percent": percent}

    @staticmethod
    def _build_domain_breakdown(question_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in question_results:
            domain = str(item.get("domain") or "").strip()
            if domain:
                grouped[domain].append(item)

        breakdown: list[dict[str, Any]] = []
        for domain, items in grouped.items():
            correct = sum(1 for item in items if bool(item.get("is_correct")))
            total = len(items)
            breakdown.append(
                {
                    "domain": domain,
                    "correct": correct,
                    "total": total,
                    "percent": round((correct / total) * 100, 2) if total else 0.0,
                    "question_numbers": [int(item.get("display_order") or 0) for item in items],
                }
            )
        breakdown.sort(key=lambda item: item["domain"].lower())
        return breakdown

    def _render_learner_response(self, structured_result: dict[str, Any]) -> str:
        state = str(structured_result.get("submission_state") or "").strip().lower()
        if state == "incomplete":
            return self._missing_answer_response(
                cast(list[int], structured_result.get("missing_question_numbers") or [])
            )

        score = structured_result.get("score") or {}
        score_line = (
            f"Scored {int(score.get('correct') or 0)}/{int(score.get('total') or 0)} "
            f"({float(score.get('percent') or 0):g}%)"
        )
        lines = [score_line]

        summary = str(structured_result.get("overall_summary") or "").strip()
        if summary:
            lines.extend(["", summary])

        domain_breakdown = structured_result.get("domain_breakdown") or []
        if isinstance(domain_breakdown, list) and domain_breakdown:
            lines.extend(["", "Domain breakdown"])
            for item in domain_breakdown:
                if not isinstance(item, dict):
                    continue
                domain = str(item.get("domain") or "").strip()
                if not domain:
                    continue
                lines.append(
                    f"- {domain}: {int(item.get('correct') or 0)}/{int(item.get('total') or 0)} "
                    f"({float(item.get('percent') or 0):g}%)"
                )

        question_results = structured_result.get("question_results") or []
        if isinstance(question_results, list) and question_results:
            lines.extend(["", "Question review"])
            for item in question_results:
                if not isinstance(item, dict):
                    continue
                number = int(item.get("display_order") or 0)
                status = "Correct" if bool(item.get("is_correct")) else "Incorrect"
                user_answer = str(item.get("user_answer") or "").strip() or "No answer"
                correct_answer = str(item.get("correct_answer") or "").strip() or "Not provided"
                explanation = str(item.get("explanation") or "").strip()
                coaching_note = str(item.get("coaching_note") or "").strip()
                lines.append(
                    f"{number}. {status}. Your answer: {user_answer}. Correct answer: {correct_answer}."
                )
                if explanation:
                    lines.append(explanation)
                if coaching_note:
                    lines.append(f"Coach note: {coaching_note}")
                lines.append("")

        return "\n".join(line for line in lines if line is not None).strip()
