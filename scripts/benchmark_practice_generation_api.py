from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

from deeptutor.agents.question.agents.generator import Generator
from deeptutor.agents.question.models import QuestionTemplate
from deeptutor.services.flashcards.service import FlashcardService


CASE_COUNTS = {
    "starter_5": 5,
    "background_10": 10,
    "full_exam_25": 25,
    "flashcard_10": 10,
}


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip().strip('"').strip("'")


def _json_line(row: dict[str, Any]) -> str:
    return json.dumps(row, sort_keys=True, ensure_ascii=False)


def _templates(count: int) -> list[QuestionTemplate]:
    domains = [
        "ethical boundaries",
        "group counseling dynamics",
        "career development",
        "human growth and development",
        "assessment and diagnosis",
        "helping relationships",
        "research and program evaluation",
        "social and cultural foundations",
        "professional orientation",
        "crisis response",
    ]
    templates: list[QuestionTemplate] = []
    for index in range(count):
        domain = domains[index % len(domains)]
        templates.append(
            QuestionTemplate(
                question_id=f"q_{index + 1}",
                concentration=domain,
                question_type="choice",
                difficulty="medium",
                source="benchmark",
                metadata={
                    "benchmark": True,
                    "knowledge_context": (
                        "NCE-style counseling review context. Prioritize realistic "
                        "application questions, balanced distractors, and concise teaching."
                    ),
                },
            )
        )
    return templates


def _extract_quiz_diagnostics(items: list[Any]) -> dict[str, Any]:
    generated_count = len(items)
    schema_ok = all(bool((item.validation or {}).get("schema_ok")) for item in items)
    repair_needed = any(bool((item.validation or {}).get("repaired")) for item in items)
    first_meta = items[0].metadata if items else {}
    return {
        "generated_count": generated_count,
        "schema_validation_success": schema_ok,
        "repair_needed": repair_needed,
        "repair_latency_ms": None,
        "tokens_in": None,
        "tokens_out": None,
        "request_id": None,
        "generation_api_seen": first_meta.get("generation_api") if isinstance(first_meta, dict) else None,
    }


async def _run_quiz_case(case: str, api: str, model: str) -> dict[str, Any]:
    count = CASE_COUNTS[case]
    generator = Generator(
        kb_name=None,
        language="en",
        tool_flags={"rag": False, "web_search": False, "code_execution": False},
        api_key=os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY"),
        base_url=os.getenv("LLM_HOST") or os.getenv("OPENAI_BASE_URL"),
        api_version=os.getenv("LLM_API_VERSION") or None,
        model=model,
    )
    started = time.perf_counter()
    try:
        items = await generator.process_quiz_set(
            templates=_templates(count),
            user_topic="NBCC NCE diagnostic practice",
            preference="NCE-style application questions for exam prep",
            history_context="",
            generation_api=api,
        )
        latency_ms = round((time.perf_counter() - started) * 1000.0, 3)
        diagnostics = _extract_quiz_diagnostics(items)
        return {
            "case": case,
            "api": api,
            "model": model,
            "requested_count": count,
            "latency_ms": latency_ms,
            "parse_success": True,
            "cost": None,
            "quality_spot_check_notes": "manual_review_required",
            **diagnostics,
        }
    except Exception as exc:
        return {
            "case": case,
            "api": api,
            "model": model,
            "requested_count": count,
            "generated_count": 0,
            "latency_ms": round((time.perf_counter() - started) * 1000.0, 3),
            "parse_success": False,
            "schema_validation_success": False,
            "repair_needed": None,
            "repair_latency_ms": None,
            "tokens_in": None,
            "tokens_out": None,
            "cost": None,
            "quality_spot_check_notes": "manual_review_required",
            "error": f"{type(exc).__name__}: {exc}",
        }


async def _run_flashcard_case(api: str, model: str) -> dict[str, Any]:
    count = CASE_COUNTS["flashcard_10"]
    service = FlashcardService()
    service._use_responses = api == "responses"
    if hasattr(service._llm.config, "model_copy"):
        service._llm.config = service._llm.config.model_copy(update={"model": model})
    started = time.perf_counter()
    try:
        payload = await service._generate_cards_with_llm(
            source_type="topic",
            topic="NBCC NCE ethics boundaries",
            knowledge_base_names=[],
            card_count=count,
            style="mixed",
            source_context=[],
        )
        latency_ms = round((time.perf_counter() - started) * 1000.0, 3)
        cards = payload.get("cards")
        generated_count = len(cards) if isinstance(cards, list) else 0
        diagnostics = payload.get("_diagnostics") if isinstance(payload.get("_diagnostics"), dict) else {}
        return {
            "case": "flashcard_10",
            "api": api,
            "model": model,
            "requested_count": count,
            "generated_count": generated_count,
            "latency_ms": latency_ms,
            "parse_success": isinstance(payload, dict),
            "schema_validation_success": generated_count >= count,
            "repair_needed": False,
            "repair_latency_ms": None,
            "tokens_in": diagnostics.get("input_tokens"),
            "tokens_out": diagnostics.get("output_tokens"),
            "cost": None,
            "quality_spot_check_notes": "manual_review_required",
            "request_id": diagnostics.get("request_id"),
            "cached_tokens": diagnostics.get("cached_tokens"),
            "reasoning_tokens": diagnostics.get("reasoning_tokens"),
        }
    except Exception as exc:
        return {
            "case": "flashcard_10",
            "api": api,
            "model": model,
            "requested_count": count,
            "generated_count": 0,
            "latency_ms": round((time.perf_counter() - started) * 1000.0, 3),
            "parse_success": False,
            "schema_validation_success": False,
            "repair_needed": None,
            "repair_latency_ms": None,
            "tokens_in": None,
            "tokens_out": None,
            "cost": None,
            "quality_spot_check_notes": "manual_review_required",
            "error": f"{type(exc).__name__}: {exc}",
        }


async def _run_case(case: str, api: str, model: str) -> dict[str, Any]:
    if case == "flashcard_10":
        return await _run_flashcard_case(api, model)
    return await _run_quiz_case(case, api, model)


async def main() -> int:
    _load_dotenv(Path(".env"))

    parser = argparse.ArgumentParser(description="Benchmark Practice generation chat vs Responses paths.")
    parser.add_argument("--case", choices=[*CASE_COUNTS.keys(), "all"], default="all")
    parser.add_argument(
        "--api",
        choices=["chat", "responses", "responses_minimal", "both", "all"],
        default="both",
    )
    parser.add_argument("--model", default=os.getenv("PRACTICE_QUIZ_MODEL") or os.getenv("LLM_MODEL") or "gpt-5-mini")
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    cases = list(CASE_COUNTS) if args.case == "all" else [args.case]
    if args.api == "all":
        apis = ["chat", "responses", "responses_minimal"]
    elif args.api == "both":
        apis = ["chat", "responses"]
    else:
        apis = [args.api]

    output_path = Path(args.output) if args.output else None
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    for case in cases:
        for api in apis:
            row = await _run_case(case, api, args.model)
            rows.append(row)
            print(_json_line(row), flush=True)

    if output_path:
        output_path.write_text(
            "\n".join(_json_line(row) for row in rows) + "\n",
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
