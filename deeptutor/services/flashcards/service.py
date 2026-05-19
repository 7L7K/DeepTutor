from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from typing import Any

from pydantic import BaseModel, Field

from deeptutor.services.llm import (
    LLMClient,
    get_llm_client,
    get_llm_config,
    get_token_limit_kwargs,
    supports_response_format,
)
from deeptutor.services.session import get_sqlite_session_store
from deeptutor.utils.json_parser import parse_json_response

logger = logging.getLogger(__name__)


class _GeneratedFlashcard(BaseModel):
    front: str = Field(description="A concise active-recall prompt.")
    back: str = Field(description="A concise answer, ideally one or two short sentences.")
    hint: str = ""
    tag: str = Field(description="One of Definition, Concept, Scenario, or Recall.")
    source_ref: str = ""


class _GeneratedFlashcardDeck(BaseModel):
    title: str
    cards: list[_GeneratedFlashcard]


class FlashcardService:
    def __init__(self) -> None:
        self._store = get_sqlite_session_store()
        flashcard_model = os.getenv("FLASHCARD_GENERATION_MODEL", "").strip()
        if flashcard_model:
            llm_config = get_llm_config().model_copy(update={"model": flashcard_model})
            self._llm = LLMClient(llm_config)
        else:
            self._llm = get_llm_client()
        self._reasoning_effort = self._resolve_reasoning_effort(self._llm.config)
        self._use_responses = self._resolve_use_responses(self._llm.config)
        self._rag: Any | None = None

    @staticmethod
    def build_generation_fingerprint(
        *,
        source_type: str,
        topic: str,
        knowledge_base_names: list[str],
        card_count: int,
        style: str,
    ) -> str:
        payload = {
            "source_type": source_type.strip().lower(),
            "topic": " ".join(topic.strip().lower().split()),
            "knowledge_base_names": sorted(name.strip().lower() for name in knowledge_base_names if name.strip()),
            "card_count": int(card_count),
            "style": style.strip().lower(),
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:24]

    async def generate_deck(
        self,
        *,
        source_type: str,
        topic: str,
        knowledge_base_names: list[str],
        card_count: int,
        style: str,
        reuse_existing: bool = True,
    ) -> tuple[dict[str, Any], bool]:
        normalized_topic = " ".join(topic.strip().split())
        normalized_kbs = [name.strip() for name in knowledge_base_names if name.strip()]
        if source_type not in {"topic", "knowledge"}:
            raise ValueError("source_type must be 'topic' or 'knowledge'")
        if source_type == "topic" and not normalized_topic:
            raise ValueError("topic is required for topic decks")
        if source_type == "knowledge" and not normalized_kbs:
            raise ValueError("Select at least one knowledge base")

        fingerprint = self.build_generation_fingerprint(
            source_type=source_type,
            topic=normalized_topic,
            knowledge_base_names=normalized_kbs,
            card_count=card_count,
            style=style,
        )
        if reuse_existing:
            existing = await self._store.find_flashcard_deck_by_fingerprint(fingerprint)
            if existing is not None:
                return existing, True

        source_context = await self._build_source_context(
            source_type=source_type,
            topic=normalized_topic,
            knowledge_base_names=normalized_kbs,
        )
        payload = await self._generate_cards_with_llm(
            source_type=source_type,
            topic=normalized_topic,
            knowledge_base_names=normalized_kbs,
            card_count=card_count,
            style=style,
            source_context=source_context,
        )
        cards = payload.get("cards")
        if not isinstance(cards, list) or not cards:
            raise ValueError("Flashcard generation returned no cards")

        cleaned_cards: list[dict[str, Any]] = []
        seen_fronts: set[str] = set()
        for index, card in enumerate(cards[:card_count], start=1):
            if not isinstance(card, dict):
                continue
            front = self._normalize_card_front(card.get("front"))
            back = self._normalize_card_back(card.get("back"))
            if not front or not back:
                continue
            dedupe_key = self._normalize_card_key(front)
            if dedupe_key in seen_fronts:
                continue
            seen_fronts.add(dedupe_key)
            cleaned_cards.append(
                {
                    "id": f"{fingerprint}_card_{index}",
                    "front": front,
                    "back": back,
                    "hint": self._normalize_hint(card.get("hint")),
                    "tag": self._normalize_tag(card.get("tag")),
                    "source_ref": str(card.get("source_ref") or "").strip(),
                }
            )
            if len(cleaned_cards) >= card_count:
                break
        self._log_cleaning_matrix(
            source_type=source_type,
            requested_count=card_count,
            raw_cards=cards,
            cleaned_cards=cleaned_cards,
            phase="generate_deck",
        )
        if not cleaned_cards:
            raise ValueError("Flashcard generation returned unusable cards")

        title = str(payload.get("title") or normalized_topic or "Knowledge deck").strip()[:200]
        source_summary = self._build_source_summary(
            source_type=source_type,
            knowledge_base_names=normalized_kbs,
        )
        deck = await self._store.save_flashcard_deck(
            {
                "id": f"deck_{fingerprint}",
                "source_type": source_type,
                "title": title,
                "topic": normalized_topic,
                "source_summary": source_summary,
                "source_kb_names": normalized_kbs,
                "style": style,
                "generation_fingerprint": fingerprint,
                "generation_settings": {
                    "card_count": card_count,
                    "style": style,
                    "reuse_existing": reuse_existing,
                },
                "source_context": source_context,
                "cards": cleaned_cards,
            }
        )
        return deck, False

    async def list_decks(self, *, limit: int = 12, offset: int = 0) -> list[dict[str, Any]]:
        return await self._store.list_flashcard_decks(limit=limit, offset=offset)

    async def get_deck(self, deck_id: str) -> dict[str, Any] | None:
        return await self._store.get_flashcard_deck(deck_id)

    async def record_review(self, *, deck_id: str, card_id: str, rating: str) -> dict[str, Any]:
        if rating not in {"got_it", "missed", "skipped"}:
            raise ValueError("rating must be got_it, missed, or skipped")
        return await self._store.record_flashcard_review(deck_id, card_id, rating)

    async def restart_deck(self, deck_id: str) -> dict[str, Any]:
        return await self._store.reset_flashcard_reviews(deck_id)

    async def complete_session(
        self,
        *,
        deck_id: str,
        review_mode: str,
        card_ids: list[str] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        deck = await self.get_deck(deck_id)
        if deck is None:
            raise ValueError(f"Flashcard deck not found: {deck_id}")
        if review_mode not in {"full_deck", "missed_only"}:
            raise ValueError("review_mode must be full_deck or missed_only")

        deck_cards = deck.get("cards") or []
        if not isinstance(deck_cards, list) or not deck_cards:
            raise ValueError("Flashcard deck has no cards")

        requested_ids = [
            str(card_id).strip()
            for card_id in (card_ids or [])
            if str(card_id).strip()
        ]
        if review_mode == "full_deck" or not requested_ids:
            review_cards = deck_cards
        else:
            allowed = {card["id"] for card in deck_cards if isinstance(card, dict) and card.get("id")}
            filtered_ids = [card_id for card_id in requested_ids if card_id in allowed]
            if not filtered_ids:
                raise ValueError("No valid cards were provided for the review pass")
            review_cards = [card for card in deck_cards if card.get("id") in filtered_ids]

        ratings = ((deck.get("summary") or {}).get("ratings") or {})
        counts = {"got_it": 0, "missed": 0, "skipped": 0}
        missed_cards: list[dict[str, Any]] = []
        got_it_cards: list[dict[str, Any]] = []
        skipped_cards: list[dict[str, Any]] = []
        tag_counts: dict[str, dict[str, int]] = {}

        for card in review_cards:
            card_id = str(card.get("id") or "")
            rating = str((ratings.get(card_id) or {}).get("rating") or "new")
            if rating not in {"got_it", "missed", "skipped"}:
                continue
            counts[rating] += 1
            tag = self._normalize_tag(card.get("tag"))
            tag_bucket = tag_counts.setdefault(tag, {"got_it": 0, "missed": 0, "skipped": 0})
            tag_bucket[rating] += 1
            if rating == "missed":
                missed_cards.append(card)
            elif rating == "got_it":
                got_it_cards.append(card)
            else:
                skipped_cards.append(card)

        review_card_ids = [str(card.get("id") or "") for card in review_cards if card.get("id")]
        analysis = await self._generate_session_analysis(
            deck=deck,
            review_mode=review_mode,
            review_cards=review_cards,
            missed_cards=missed_cards,
            got_it_cards=got_it_cards,
            skipped_cards=skipped_cards,
            tag_counts=tag_counts,
        )
        session_review = await self._store.save_flashcard_session_review(
            {
                "deck_id": deck_id,
                "review_mode": review_mode,
                "card_ids": review_card_ids,
                "cards_reviewed": len(review_card_ids),
                "got_it_count": counts["got_it"],
                "missed_count": counts["missed"],
                "skipped_count": counts["skipped"],
                "analysis_summary": analysis.get("summary") or "",
                "analysis_strengths": analysis.get("strengths") or [],
                "analysis_weak_spots": analysis.get("weak_spots") or [],
                "analysis_recommended_next_step": analysis.get("recommended_next_step") or "",
                "analysis_focus_topics": analysis.get("focus_topics") or [],
            }
        )
        refreshed_deck = await self.get_deck(deck_id)
        if refreshed_deck is None:
            raise ValueError(f"Flashcard deck not found: {deck_id}")
        return refreshed_deck, session_review

    async def get_topic_suggestions(
        self,
        *,
        knowledge_base_names: list[str],
        hint: str = "",
    ) -> list[str]:
        normalized_kbs = [name.strip() for name in knowledge_base_names if name.strip()]
        if not normalized_kbs:
            return []
        source_context = await self._build_source_context(
            source_type="knowledge",
            topic=hint,
            knowledge_base_names=normalized_kbs,
        )
        if not source_context:
            return []
        suggestions = await self._suggest_topics_with_llm(
            knowledge_base_names=normalized_kbs,
            hint=hint,
            source_context=source_context,
        )
        return suggestions[:6]

    async def _build_source_context(
        self,
        *,
        source_type: str,
        topic: str,
        knowledge_base_names: list[str],
    ) -> list[dict[str, Any]]:
        if source_type != "knowledge":
            return []
        if self._rag is None:
            from deeptutor.services.rag.service import RAGService

            self._rag = RAGService()
        query = topic.strip() or "Create high-yield study flashcards from this material."
        results: list[dict[str, Any]] = []
        total_started_at = time.perf_counter()
        for kb_name in knowledge_base_names:
            kb_started_at = time.perf_counter()
            try:
                rag_result = await self._rag.search(query=query, kb_name=kb_name, top_k=4)
            except Exception as exc:
                logger.warning("Flashcard RAG lookup failed for %s: %s", kb_name, exc)
                continue
            content = str(rag_result.get("content") or rag_result.get("answer") or "").strip()
            elapsed = time.perf_counter() - kb_started_at
            logger.info(
                "Flashcard RAG matrix: "
                + json.dumps(
                    {
                        "kb_name": kb_name,
                        "query_chars": len(query),
                        "elapsed_seconds": round(elapsed, 3),
                        "content_chars": len(content),
                        "source_count": len(rag_result.get("sources") or []),
                        "usable": bool(content),
                    },
                    sort_keys=True,
                )
            )
            if not content:
                continue
            results.append(
                {
                    "kb_name": kb_name,
                    "excerpt": content[:4000],
                    "sources": rag_result.get("sources") or [],
                }
            )
        if not results:
            logger.info(
                "Flashcard source matrix: "
                + json.dumps(
                    {
                        "source_type": source_type,
                        "kb_count": len(knowledge_base_names),
                        "usable_context_count": 0,
                        "elapsed_seconds": round(time.perf_counter() - total_started_at, 3),
                    },
                    sort_keys=True,
                )
            )
            raise ValueError(
                "The selected knowledge bases did not return usable study context. Try a topic deck or re-check the KBs."
            )
        logger.info(
            "Flashcard source matrix: "
            + json.dumps(
                {
                    "source_type": source_type,
                    "kb_count": len(knowledge_base_names),
                    "usable_context_count": len(results),
                    "excerpt_chars": sum(len(str(item.get("excerpt") or "")) for item in results),
                    "elapsed_seconds": round(time.perf_counter() - total_started_at, 3),
                },
                sort_keys=True,
            )
        )
        return results

    async def _generate_cards_with_llm(
        self,
        *,
        source_type: str,
        topic: str,
        knowledge_base_names: list[str],
        card_count: int,
        style: str,
        source_context: list[dict[str, Any]],
    ) -> dict[str, Any]:
        llm_config = self._llm.config
        system_prompt, user_prompt, candidate_count = self._build_generation_prompts(
            source_type=source_type,
            topic=topic,
            knowledge_base_names=knowledge_base_names,
            card_count=card_count,
            style=style,
            source_context=source_context,
        )
        if self._should_use_responses_api(llm_config):
            try:
                return await self._generate_cards_with_responses(
                    llm_config=llm_config,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    source_type=source_type,
                    card_count=card_count,
                    candidate_count=candidate_count,
                    source_context=source_context,
                )
            except Exception as exc:
                logger.warning(
                    "Flashcard Responses generation failed; falling back to chat completions: %s",
                    exc,
                )

        kwargs: dict[str, Any] = {}
        if supports_response_format(llm_config.binding, llm_config.model):
            kwargs["response_format"] = {"type": "json_object"}
        kwargs.update(
            get_token_limit_kwargs(
                llm_config.model,
                max_tokens=self._generation_token_limit(candidate_count),
            )
        )
        if self._reasoning_effort:
            kwargs["reasoning_effort"] = self._reasoning_effort

        llm_started_at = time.perf_counter()
        raw = await self._llm.complete(
            prompt=user_prompt,
            system_prompt=system_prompt,
            temperature=0.2,
            **kwargs,
        )
        elapsed = time.perf_counter() - llm_started_at
        payload = parse_json_response(raw, logger_instance=logger, fallback={})
        if not isinstance(payload, dict):
            raise ValueError("Flashcard generation returned invalid JSON")
        payload["_diagnostics"] = {
            "api": "chat_completions",
            "model": llm_config.model,
            "reasoning_effort": self._reasoning_effort or None,
            "elapsed_seconds": round(elapsed, 3),
            "requested_count": card_count,
            "candidate_count": candidate_count,
            "source_context_count": len(source_context),
            "source_excerpt_chars": sum(len(str(item.get("excerpt") or "")) for item in source_context),
            "raw_card_count": len(payload.get("cards")) if isinstance(payload.get("cards"), list) else 0,
        }
        self._log_generation_matrix(
            api="chat_completions",
            model=llm_config.model,
            source_type=source_type,
            requested_count=card_count,
            candidate_count=candidate_count,
            source_context=source_context,
            elapsed_seconds=elapsed,
            payload=payload,
        )
        return payload

    def _build_generation_prompts(
        self,
        *,
        source_type: str,
        topic: str,
        knowledge_base_names: list[str],
        card_count: int,
        style: str,
        source_context: list[dict[str, Any]],
        avoid_fronts: list[str] | None = None,
    ) -> tuple[str, str, int]:
        system_prompt = (
            "You create study-ready flashcard decks for learners. "
            "Return only a JSON object with keys title and cards. "
            "cards must be an array of objects with front, back, hint, tag, and source_ref. "
            "Keep cards concise, concrete, and useful for active recall. "
            "Do not include markdown fences."
        )

        context_block = ""
        if source_context:
            rendered = []
            for item in source_context:
                rendered.append(
                    f"KB: {item.get('kb_name','')}\nExcerpt:\n{item.get('excerpt','')}"
                )
            context_block = "\n\nGrounding context:\n" + "\n\n---\n\n".join(rendered)

        candidate_count = self._candidate_flashcard_count(card_count)
        user_prompt = (
            f"Generate {candidate_count} flashcards.\n"
            f"Source type: {source_type}\n"
            f"Topic: {topic or 'Use the knowledge-base material'}\n"
            f"Deck style: {style}\n"
            f"Knowledge bases: {', '.join(knowledge_base_names) if knowledge_base_names else 'none'}\n\n"
            "Return JSON in this shape:\n"
            '{"title":"...","cards":[{"front":"...","back":"...","hint":"...","tag":"...","source_ref":"..."}]}\n\n'
            "Rules:\n"
            "- front should be a clear recall prompt\n"
            "- back should be 1 to 2 short sentences and stay under 220 characters when possible\n"
            "- hint is optional but helpful\n"
            "- tag should be one of Definition, Concept, Scenario, Recall\n"
            "- source_ref should mention the KB name if grounded context was used, otherwise leave it empty\n"
            "- do not repeat the same card idea\n"
            "- avoid generic fronts like 'What is X?' unless the term is very specific\n"
            "- prefer specific, high-yield prompts over vague study-guide wording\n"
            "- mixed decks should include a real variety of definition, concept, scenario, and recall cards\n"
            "- make the deck feel like a focused study set, not a generic list"
            f"{context_block}"
        )
        if avoid_fronts:
            user_prompt += (
                "\n\nAvoid duplicating these existing card fronts:\n"
                + "\n".join(f"- {front}" for front in avoid_fronts[:20])
            )
        return system_prompt, user_prompt, candidate_count

    def _should_use_responses_api(self, llm_config: Any) -> bool:
        if not self._use_responses:
            return False
        binding = str(getattr(llm_config, "binding", "") or "").strip().lower()
        return binding == "openai" and bool(getattr(llm_config, "api_key", ""))

    @staticmethod
    def _resolve_reasoning_effort(llm_config: Any) -> str:
        configured = os.getenv("FLASHCARD_GENERATION_REASONING_EFFORT", "").strip()
        if configured:
            return configured
        model = str(getattr(llm_config, "model", "") or "").strip().lower()
        return "low" if model.startswith("gpt-5") else ""

    @staticmethod
    def _resolve_use_responses(llm_config: Any) -> bool:
        configured = os.getenv("FLASHCARD_USE_RESPONSES", "").strip().lower()
        if configured in {"0", "false", "no", "off"}:
            return False
        if configured in {"1", "true", "yes", "on"}:
            return True
        binding = str(getattr(llm_config, "binding", "") or "").strip().lower()
        return binding == "openai" and bool(getattr(llm_config, "api_key", ""))

    @staticmethod
    def _candidate_flashcard_count(card_count: int) -> int:
        safe_count = max(1, int(card_count))
        configured = os.getenv("FLASHCARD_EXTRA_CANDIDATES", "").strip()
        if configured:
            try:
                extra_candidates = int(configured)
            except ValueError:
                extra_candidates = 0
            extra_candidates = max(0, min(extra_candidates, 12))
        elif safe_count <= 12:
            extra_candidates = 0
        elif safe_count <= 20:
            extra_candidates = 2
        else:
            extra_candidates = 4
        return min(max(safe_count + extra_candidates, safe_count), 48)

    @staticmethod
    def _generation_token_limit(candidate_count: int) -> int:
        return min(2200, max(1200, int(candidate_count) * 180))

    async def _generate_cards_with_responses(
        self,
        *,
        llm_config: Any,
        system_prompt: str,
        user_prompt: str,
        source_type: str,
        card_count: int,
        candidate_count: int,
        source_context: list[dict[str, Any]],
    ) -> dict[str, Any]:
        from deeptutor.services.llm.structured_responses import generate_structured_response

        result = await generate_structured_response(
            model=llm_config.model,
            instructions=system_prompt,
            input_data=user_prompt,
            api_key=llm_config.api_key,
            base_url=llm_config.base_url,
            default_headers=llm_config.extra_headers,
            pydantic_model=_GeneratedFlashcardDeck,
            max_output_tokens=self._generation_token_limit(candidate_count),
            prompt_cache_key=self._prompt_cache_key(source_type=source_type),
            store=False,
            reasoning_effort=self._reasoning_effort or None,
        )
        elapsed = result.latency_ms / 1000.0
        payload = dict(result.parsed)
        usage = result.usage or {}
        input_details = usage.get("input_tokens_details") or {}
        output_details = usage.get("output_tokens_details") or {}
        payload["_diagnostics"] = {
            "api": "responses",
            "model": result.model,
            "reasoning_effort": self._reasoning_effort or None,
            "elapsed_seconds": round(elapsed, 3),
            "requested_count": card_count,
            "candidate_count": candidate_count,
            "source_context_count": len(source_context),
            "source_excerpt_chars": sum(len(str(item.get("excerpt") or "")) for item in source_context),
            "raw_card_count": len(payload.get("cards")) if isinstance(payload.get("cards"), list) else 0,
            "request_id": result.request_id,
            "input_tokens": usage.get("input_tokens"),
            "cached_tokens": input_details.get("cached_tokens"),
            "output_tokens": usage.get("output_tokens"),
            "reasoning_tokens": output_details.get("reasoning_tokens"),
        }
        self._log_generation_matrix(
            api="responses",
            model=llm_config.model,
            source_type=source_type,
            requested_count=card_count,
            candidate_count=candidate_count,
            source_context=source_context,
            elapsed_seconds=elapsed,
            payload=payload,
            request_id=result.request_id,
            usage=usage,
        )
        return payload

    @staticmethod
    def _prompt_cache_key(*, source_type: str) -> str:
        return f"deeptutor-flashcards-v1-{source_type}"

    def _log_generation_matrix(
        self,
        *,
        api: str,
        model: str,
        source_type: str,
        requested_count: int,
        candidate_count: int,
        source_context: list[dict[str, Any]],
        elapsed_seconds: float,
        payload: dict[str, Any],
        request_id: str | None = None,
        usage: dict[str, Any] | None = None,
    ) -> None:
        cards = payload.get("cards")
        raw_card_count = len(cards) if isinstance(cards, list) else 0
        usage = usage or {}
        input_details = usage.get("input_tokens_details") or {}
        output_details = usage.get("output_tokens_details") or {}
        logger.info(
            "Flashcard generation matrix: "
            + json.dumps(
                {
                    "api": api,
                    "model": model,
                    "reasoning_effort": self._reasoning_effort or None,
                    "source_type": source_type,
                    "requested_count": requested_count,
                    "candidate_count": candidate_count,
                    "source_context_count": len(source_context),
                    "source_excerpt_chars": sum(
                        len(str(item.get("excerpt") or "")) for item in source_context
                    ),
                    "elapsed_seconds": round(elapsed_seconds, 3),
                    "raw_card_count": raw_card_count,
                    "request_id": request_id,
                    "input_tokens": usage.get("input_tokens"),
                    "cached_tokens": input_details.get("cached_tokens"),
                    "output_tokens": usage.get("output_tokens"),
                    "reasoning_tokens": output_details.get("reasoning_tokens"),
                },
                sort_keys=True,
            )
        )

    def _log_cleaning_matrix(
        self,
        *,
        source_type: str,
        requested_count: int,
        raw_cards: Any,
        cleaned_cards: list[dict[str, Any]],
        phase: str,
    ) -> None:
        raw_count = len(raw_cards) if isinstance(raw_cards, list) else 0
        logger.info(
            "Flashcard cleaning matrix: "
            + json.dumps(
                {
                    "phase": phase,
                    "source_type": source_type,
                    "requested_count": requested_count,
                    "raw_card_count": raw_count,
                    "cleaned_card_count": len(cleaned_cards),
                    "dropped_count": max(0, raw_count - len(cleaned_cards)),
                    "status": "ok" if cleaned_cards else "empty_after_cleaning",
                },
                sort_keys=True,
            )
        )

    async def _generate_session_analysis(
        self,
        *,
        deck: dict[str, Any],
        review_mode: str,
        review_cards: list[dict[str, Any]],
        missed_cards: list[dict[str, Any]],
        got_it_cards: list[dict[str, Any]],
        skipped_cards: list[dict[str, Any]],
        tag_counts: dict[str, dict[str, int]],
    ) -> dict[str, Any]:
        fallback = self._build_fallback_session_analysis(
            deck=deck,
            review_mode=review_mode,
            missed_cards=missed_cards,
            got_it_cards=got_it_cards,
            skipped_cards=skipped_cards,
            tag_counts=tag_counts,
        )
        if not review_cards:
            return fallback

        llm_config = self._llm.config
        kwargs: dict[str, Any] = {}
        if supports_response_format(llm_config.binding, llm_config.model):
            kwargs["response_format"] = {"type": "json_object"}
        kwargs.update(get_token_limit_kwargs(llm_config.model, max_tokens=1200))
        if self._reasoning_effort:
            kwargs["reasoning_effort"] = self._reasoning_effort

        tag_summary = [
            {
                "tag": tag,
                "got_it": counts["got_it"],
                "missed": counts["missed"],
                "skipped": counts["skipped"],
            }
            for tag, counts in sorted(tag_counts.items())
        ]
        review_payload = {
            "deck_title": deck.get("title") or "",
            "topic": deck.get("topic") or "",
            "source_summary": deck.get("source_summary") or "",
            "review_mode": review_mode,
            "cards_reviewed": len(review_cards),
            "got_it_count": len(got_it_cards),
            "missed_count": len(missed_cards),
            "skipped_count": len(skipped_cards),
            "missed_cards": [
                {
                    "front": card.get("front") or "",
                    "tag": self._normalize_tag(card.get("tag")),
                }
                for card in missed_cards[:8]
            ],
            "strong_cards": [
                {
                    "front": card.get("front") or "",
                    "tag": self._normalize_tag(card.get("tag")),
                }
                for card in got_it_cards[:6]
            ],
            "tag_summary": tag_summary,
        }

        system_prompt = (
            "You write short, coach-style flashcard study reviews. "
            "Return only JSON with keys summary, strengths, weak_spots, recommended_next_step, and focus_topics. "
            "Keep the tone supportive, concrete, and modest. "
            "Do not overstate ability from one session. "
            "Do not include markdown fences."
        )
        user_prompt = (
            "Review this completed flashcard study pass and give a short, practical study write-up.\n\n"
            f"{json.dumps(review_payload, ensure_ascii=False)}\n\n"
            "Rules:\n"
            "- summary must be 1 to 2 short sentences\n"
            "- strengths must be a short list of real strengths if any, otherwise empty\n"
            "- weak_spots must be specific and actionable\n"
            "- recommended_next_step must be one concrete next move\n"
            "- focus_topics should be 2 to 4 short topic phrases\n"
        )
        try:
            raw = await self._llm.complete(
                prompt=user_prompt,
                system_prompt=system_prompt,
                temperature=0.2,
                **kwargs,
            )
            payload = parse_json_response(raw, logger_instance=logger, fallback={})
        except Exception as exc:
            logger.warning("Flashcard session analysis fell back to local summary: %s", exc)
            return fallback
        if not isinstance(payload, dict):
            return fallback

        return {
            "summary": str(payload.get("summary") or fallback["summary"]).strip() or fallback["summary"],
            "strengths": self._coerce_str_list(payload.get("strengths")) or fallback["strengths"],
            "weak_spots": self._coerce_str_list(payload.get("weak_spots")) or fallback["weak_spots"],
            "recommended_next_step": str(
                payload.get("recommended_next_step") or fallback["recommended_next_step"]
            ).strip()
            or fallback["recommended_next_step"],
            "focus_topics": self._coerce_str_list(payload.get("focus_topics")) or fallback["focus_topics"],
        }

    async def _suggest_topics_with_llm(
        self,
        *,
        knowledge_base_names: list[str],
        hint: str,
        source_context: list[dict[str, Any]],
    ) -> list[str]:
        llm_config = self._llm.config
        kwargs: dict[str, Any] = {}
        if supports_response_format(llm_config.binding, llm_config.model):
            kwargs["response_format"] = {"type": "json_object"}
        kwargs.update(get_token_limit_kwargs(llm_config.model, max_tokens=700))
        if self._reasoning_effort:
            kwargs["reasoning_effort"] = self._reasoning_effort

        rendered = []
        for item in source_context[:3]:
            rendered.append(f"KB: {item.get('kb_name','')}\nExcerpt:\n{item.get('excerpt','')}")
        system_prompt = (
            "You extract likely study-topic suggestions from knowledge base excerpts. "
            "Return only JSON with a suggestions array of short topic phrases. "
            "Prefer 2 to 4 word phrases and avoid generic filler."
        )
        user_prompt = (
            f"Knowledge bases: {', '.join(knowledge_base_names)}\n"
            f"Current hint: {hint or 'none'}\n\n"
            "Suggest up to 6 likely flashcard focus topics from these excerpts.\n\n"
            f"{chr(10).join(rendered)}\n\n"
            'Return JSON like {"suggestions":["topic one","topic two"]}'
        )
        try:
            raw = await self._llm.complete(
                prompt=user_prompt,
                system_prompt=system_prompt,
                temperature=0.2,
                **kwargs,
            )
            payload = parse_json_response(raw, logger_instance=logger, fallback={})
        except Exception as exc:
            logger.warning("Flashcard topic suggestions fell back to empty list: %s", exc)
            return []
        suggestions = self._coerce_str_list(payload.get("suggestions") if isinstance(payload, dict) else [])
        deduped: list[str] = []
        seen: set[str] = set()
        for item in suggestions:
            normalized = self._normalize_topic_chip(item)
            if not normalized:
                continue
            key = normalized.casefold()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(normalized)
        return deduped

    @staticmethod
    def _build_source_summary(*, source_type: str, knowledge_base_names: list[str]) -> str:
        if source_type == "knowledge":
            return f"Grounded in {', '.join(knowledge_base_names)}"
        return "AI-generated from topic"

    def _build_fallback_session_analysis(
        self,
        *,
        deck: dict[str, Any],
        review_mode: str,
        missed_cards: list[dict[str, Any]],
        got_it_cards: list[dict[str, Any]],
        skipped_cards: list[dict[str, Any]],
        tag_counts: dict[str, dict[str, int]],
    ) -> dict[str, Any]:
        weak_tags = [
            tag for tag, counts in sorted(tag_counts.items(), key=lambda item: (-item[1]["missed"], item[0]))
            if counts["missed"] > 0
        ][:3]
        strong_tags = [
            tag for tag, counts in sorted(tag_counts.items(), key=lambda item: (-item[1]["got_it"], item[0]))
            if counts["got_it"] > 0 and counts["missed"] == 0
        ][:3]
        mode_label = "missed-card review" if review_mode == "missed_only" else "full deck"
        if missed_cards:
            summary = (
                f"This {mode_label} showed stronger recall on direct cards, but the missed prompts clustered around "
                f"{', '.join(weak_tags) if weak_tags else 'a few specific concepts'}."
            )
        elif got_it_cards:
            summary = (
                f"You completed this {mode_label} without any remaining missed cards, which suggests the core ideas are landing."
            )
        else:
            summary = f"This {mode_label} ended without enough completed ratings to infer a strong pattern yet."
        strengths = strong_tags or ([self._normalize_tag(card.get("tag")) for card in got_it_cards[:2]] if got_it_cards else [])
        weak_spots = weak_tags or [self._shorten_card_front(card.get("front")) for card in missed_cards[:3]]
        focus_topics = weak_spots[:4] if weak_spots else ([deck.get("topic")] if deck.get("topic") else [])
        if missed_cards:
            next_step = "Review the missed cards first, then run one smaller focused deck on the same weak areas."
        elif skipped_cards:
            next_step = "Revisit the skipped cards next so you can turn undecided items into active recall wins."
        else:
            next_step = "Run another deck with a narrower focus if you want a harder second pass."
        return {
            "summary": summary,
            "strengths": [item for item in strengths if item][:3],
            "weak_spots": [item for item in weak_spots if item][:4],
            "recommended_next_step": next_step,
            "focus_topics": [item for item in focus_topics if item][:4],
        }

    @staticmethod
    def _coerce_str_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        result: list[str] = []
        for item in value:
            text = str(item or "").strip()
            if text:
                result.append(text)
        return result

    @staticmethod
    def _normalize_card_key(value: str) -> str:
        return re.sub(r"\s+", " ", value.strip().lower())

    @staticmethod
    def _normalize_card_front(value: Any) -> str:
        front = str(value or "").strip()
        front = re.sub(r"\s+", " ", front)
        return front[:220]

    @staticmethod
    def _normalize_card_back(value: Any) -> str:
        back = str(value or "").strip()
        back = re.sub(r"\s+", " ", back)
        return back[:320]

    @staticmethod
    def _normalize_hint(value: Any) -> str:
        hint = str(value or "").strip()
        hint = re.sub(r"\s+", " ", hint)
        return hint[:180]

    @staticmethod
    def _normalize_tag(value: Any) -> str:
        text = str(value or "").strip().lower()
        if "def" in text:
            return "Definition"
        if "concept" in text:
            return "Concept"
        if "scenario" in text or "application" in text:
            return "Scenario"
        return "Recall"

    @staticmethod
    def _normalize_topic_chip(value: str) -> str:
        text = re.sub(r"\s+", " ", str(value or "").strip(" -:,."))
        return text[:50]

    @staticmethod
    def _shorten_card_front(value: Any) -> str:
        text = str(value or "").strip()
        if len(text) <= 64:
            return text
        return text[:61].rstrip() + "..."


_instance: FlashcardService | None = None


def get_flashcard_service() -> FlashcardService:
    global _instance
    if _instance is None:
        _instance = FlashcardService()
    return _instance
