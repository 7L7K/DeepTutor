from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

from deeptutor.agents.question.coordinator import AgentCoordinator
from deeptutor.services.flashcards.service import FlashcardService
from deeptutor.services.llm.client import LLMClient
from deeptutor.services.llm.config import get_llm_config


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


def _extract_quiz_diagnostics(items: list[Any]) -> dict[str, Any]:
    generated_count = len(items)
    schema_ok = True
    repair_needed = any(
        bool((item.get("validation") or {}).get("repaired"))
        for item in items
        if isinstance(item, dict)
    )
    first_meta = items[0].get("metadata", {}) if items and isinstance(items[0], dict) else {}
    return {
        "generated_count": generated_count,
        "schema_validation_success": schema_ok,
        "repair_needed": repair_needed,
        "repair_latency_ms": None,
        "tokens_in": None,
        "tokens_out": None,
        "request_id": None,
        "generation_api_seen": first_meta.get("generation_api") if isinstance(first_meta, dict) else None,
        "model_path": first_meta.get("model_path") if isinstance(first_meta, dict) else None,
    }


async def _run_quiz_case(case: str, api: str, model: str) -> dict[str, Any]:
    count = CASE_COUNTS[case]
    old_env = {
        "PRACTICE_QUIZ_MODEL": os.environ.get("PRACTICE_QUIZ_MODEL"),
        "PRACTICE_GENERATION_API": os.environ.get("PRACTICE_GENERATION_API"),
        "PRACTICE_QUIZ_PROGRESSIVE_FIRST_BATCH": os.environ.get("PRACTICE_QUIZ_PROGRESSIVE_FIRST_BATCH"),
    }
    os.environ["PRACTICE_QUIZ_MODEL"] = model
    os.environ["PRACTICE_GENERATION_API"] = api
    os.environ["PRACTICE_QUIZ_PROGRESSIVE_FIRST_BATCH"] = "0"
    coordinator = AgentCoordinator(
        kb_name=None,
        language="en",
        tool_flags_override={"rag": False, "web_search": False, "code_execution": False},
        api_key=os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY"),
        base_url=os.getenv("LLM_HOST") or os.getenv("OPENAI_BASE_URL"),
        api_version=os.getenv("LLM_API_VERSION") or None,
    )
    first_result_ms: float | None = None
    started = time.perf_counter()
    async def _on_event(update: dict[str, Any]) -> None:
        nonlocal first_result_ms
        if update.get("type") == "result" and first_result_ms is None:
            first_result_ms = round((time.perf_counter() - started) * 1000.0, 3)

    coordinator.set_ws_callback(_on_event)
    try:
        result = await coordinator.generate_from_topic(
            user_topic="NBCC NCE diagnostic practice",
            preference="NCE-style application questions for exam prep",
            num_questions=count,
            difficulty="medium",
            question_type="choice",
            history_context="",
        )
        latency_ms = round((time.perf_counter() - started) * 1000.0, 3)
        items = result.get("results") if isinstance(result, dict) else []
        items = items if isinstance(items, list) else []
        diagnostics = _extract_quiz_diagnostics(items)
        return {
            "case": case,
            "api": api,
            "model": model,
            "requested_count": count,
            "latency_ms": latency_ms,
            "first_useful_output_ms": first_result_ms or latency_ms,
            "total_completion_ms": latency_ms,
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
            "first_useful_output_ms": None,
            "total_completion_ms": round((time.perf_counter() - started) * 1000.0, 3),
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
    finally:
        for key, value in old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


async def _run_flashcard_case(api: str, model: str) -> dict[str, Any]:
    count = CASE_COUNTS["flashcard_10"]
    service = FlashcardService.__new__(FlashcardService)
    llm_config = get_llm_config().model_copy(update={"model": model})
    service._llm = LLMClient(llm_config)
    service._reasoning_effort = service._resolve_reasoning_effort(llm_config)
    service._use_responses = api == "responses"
    service._rag = None
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
            "model_path": (
                "/practice/flashcards -> flashcards router -> "
                f"FlashcardService._generate_cards_with_llm(model={model})"
            ),
            "requested_count": count,
            "generated_count": generated_count,
            "latency_ms": latency_ms,
            "first_useful_output_ms": latency_ms,
            "total_completion_ms": latency_ms,
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
            "model_path": (
                "/practice/flashcards -> flashcards router -> "
                f"FlashcardService._generate_cards_with_llm(model={model})"
            ),
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
    parser.add_argument("--quiz-model", default="")
    parser.add_argument("--flashcard-model", default="")
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
            model = (
                args.flashcard_model
                if case == "flashcard_10" and args.flashcard_model
                else args.quiz_model
                if case != "flashcard_10" and args.quiz_model
                else args.model
            )
            row = await _run_case(case, api, model)
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
