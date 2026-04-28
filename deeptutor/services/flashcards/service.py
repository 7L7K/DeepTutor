from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Any

from deeptutor.logging import get_logger
from deeptutor.services.knowledge_scope import to_internal_kb_names
from deeptutor.services.llm import get_llm_client, get_token_limit_kwargs, supports_response_format
from deeptutor.services.rag.service import RAGService
from deeptutor.services.session import get_sqlite_session_store
from deeptutor.utils.json_parser import parse_json_response

logger = get_logger("FlashcardService")


class FlashcardService:
    def __init__(self) -> None:
        self._store = get_sqlite_session_store()
        self._llm = get_llm_client()
        self._rag = RAGService()

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
        tester_id: str = "local-default",
    ) -> tuple[dict[str, Any], bool]:
        normalized_topic = " ".join(topic.strip().split())
        normalized_kbs = [name.strip() for name in knowledge_base_names if name.strip()]
        internal_kbs = to_internal_kb_names(normalized_kbs, tester_id)
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
            existing = await self._store.find_flashcard_deck_by_fingerprint(fingerprint, tester_id=tester_id)
            if existing is not None:
                logger.info(
                    f"Flashcard deck reused: source_type={source_type} "
                    f"requested={card_count} deck_id={existing.get('id')}"
                )
                return existing, True

        started_at = time.perf_counter()
        source_started_at = time.perf_counter()
        source_context = await self._build_source_context(
            source_type=source_type,
            topic=normalized_topic,
            knowledge_base_names=internal_kbs,
        )
        logger.info(
            f"Flashcard source context ready: source_type={source_type} "
            f"requested={card_count} kb_count={len(normalized_kbs)} "
            f"elapsed={time.perf_counter() - source_started_at:.2f}s"
        )
        payload = await self._generate_cards_with_llm(
            source_type=source_type,
            topic=normalized_topic,
            knowledge_base_names=internal_kbs,
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
                    "id": f"{tester_id}_{fingerprint}_card_{index}",
                    "front": front,
                    "back": back,
                    "hint": self._normalize_hint(card.get("hint")),
                    "tag": self._normalize_tag(card.get("tag")),
                    "source_ref": str(card.get("source_ref") or "").strip(),
                }
            )
            if len(cleaned_cards) >= card_count:
                break
        if not cleaned_cards:
            raise ValueError("Flashcard generation returned unusable cards")

        title = str(payload.get("title") or normalized_topic or "Knowledge deck").strip()[:200]
        source_summary = self._build_source_summary(
            source_type=source_type,
            knowledge_base_names=normalized_kbs,
        )
        deck = await self._store.save_flashcard_deck(
            {
                "id": f"deck_{tester_id}_{fingerprint}",
                "tester_id": tester_id,
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
        logger.info(
            f"Flashcard deck generated: source_type={source_type} "
            f"requested={card_count} saved={len(cleaned_cards)} "
            f"deck_id={deck.get('id')} elapsed={time.perf_counter() - started_at:.2f}s"
        )
        return deck, False

    async def generate_progressive_deck(
        self,
        *,
        source_type: str,
        topic: str,
        knowledge_base_names: list[str],
        card_count: int,
        style: str,
        reuse_existing: bool = True,
        first_batch_size: int = 5,
        tester_id: str = "local-default",
    ) -> tuple[dict[str, Any], bool, bool]:
        normalized_topic = " ".join(topic.strip().split())
        normalized_kbs = [name.strip() for name in knowledge_base_names if name.strip()]
        internal_kbs = to_internal_kb_names(normalized_kbs, tester_id)
        requested_count = max(5, int(card_count or 10))
        first_count = min(max(1, int(first_batch_size or 5)), requested_count)
        if requested_count <= first_count:
            deck, reused = await self.generate_deck(
                source_type=source_type,
                topic=normalized_topic,
                knowledge_base_names=normalized_kbs,
                card_count=requested_count,
                style=style,
                reuse_existing=reuse_existing,
                tester_id=tester_id,
            )
            return deck, reused, False

        fingerprint = self.build_generation_fingerprint(
            source_type=source_type,
            topic=normalized_topic,
            knowledge_base_names=normalized_kbs,
            card_count=requested_count,
            style=style,
        )
        if reuse_existing:
            existing = await self._store.find_flashcard_deck_by_fingerprint(fingerprint, tester_id=tester_id)
            if existing is not None:
                return existing, True, False

        source_context = await self._build_source_context(
            source_type=source_type,
            topic=normalized_topic,
            knowledge_base_names=internal_kbs,
        )
        payload = await self._generate_cards_with_llm(
            source_type=source_type,
            topic=normalized_topic,
            knowledge_base_names=internal_kbs,
            card_count=first_count,
            style=style,
            source_context=source_context,
        )
        cards = self._clean_generated_cards(
            payload.get("cards"),
            fingerprint=f"{tester_id}_{fingerprint}",
            card_count=first_count,
            start_index=1,
        )
        if not cards:
            raise ValueError("Flashcard generation returned unusable cards")

        title = str(payload.get("title") or normalized_topic or "Knowledge deck").strip()[:200]
        deck = await self._store.save_flashcard_deck(
            {
                "id": f"deck_{tester_id}_{fingerprint}",
                "tester_id": tester_id,
                "source_type": source_type,
                "title": title,
                "topic": normalized_topic,
                "source_summary": self._build_source_summary(
                    source_type=source_type,
                    knowledge_base_names=normalized_kbs,
                ),
                "source_kb_names": normalized_kbs,
                "style": style,
                "generation_fingerprint": fingerprint,
                "generation_settings": {
                    "card_count": requested_count,
                    "style": style,
                    "reuse_existing": reuse_existing,
                    "progressive": True,
                    "status": "partial",
                    "requested_count": requested_count,
                    "ready_count": len(cards),
                },
                "source_context": source_context,
                "cards": cards,
            }
        )
        return deck, False, True

    async def complete_progressive_deck(
        self,
        *,
        deck_id: str,
        source_type: str,
        topic: str,
        knowledge_base_names: list[str],
        card_count: int,
        style: str,
        tester_id: str = "local-default",
    ) -> dict[str, Any]:
        deck = await self._store.get_flashcard_deck(deck_id, tester_id=tester_id)
        if deck is None:
            raise ValueError(f"Flashcard deck not found: {deck_id}")
        existing_cards = deck.get("cards") if isinstance(deck.get("cards"), list) else []
        ready_count = len(existing_cards)
        remaining = max(0, int(card_count or 0) - ready_count)
        if remaining <= 0:
            return deck
        source_context = deck.get("source_context") if isinstance(deck.get("source_context"), list) else []
        avoid_fronts = [
            str(card.get("front") or "").strip()
            for card in existing_cards
            if isinstance(card, dict) and str(card.get("front") or "").strip()
        ]
        payload = await self._generate_cards_with_llm(
            source_type=source_type,
            topic=topic,
            knowledge_base_names=to_internal_kb_names(knowledge_base_names, tester_id),
            card_count=remaining,
            style=style,
            source_context=source_context,
            avoid_fronts=avoid_fronts,
        )
        cards = self._clean_generated_cards(
            payload.get("cards"),
            fingerprint=deck_id.removeprefix("deck_"),
            card_count=remaining,
            start_index=ready_count + 1,
            seen_fronts={self._normalize_card_key(front) for front in avoid_fronts},
        )
        status = "complete" if cards else "failed"
        next_ready_count = ready_count + len(cards)
        return await self._store.append_flashcard_cards(
            deck_id,
            cards,
            {
                **(deck.get("generation_settings") or {}),
                "progressive": True,
                "status": status if next_ready_count >= int(card_count or 0) else "partial",
                "requested_count": int(card_count or 0),
                "ready_count": next_ready_count,
            },
            tester_id=tester_id,
        )

    def _clean_generated_cards(
        self,
        cards: Any,
        *,
        fingerprint: str,
        card_count: int,
        start_index: int = 1,
        seen_fronts: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        if not isinstance(cards, list):
            return []
        cleaned_cards: list[dict[str, Any]] = []
        seen = set(seen_fronts or set())
        for offset, card in enumerate(cards[:card_count], start=0):
            if not isinstance(card, dict):
                continue
            front = self._normalize_card_front(card.get("front"))
            back = self._normalize_card_back(card.get("back"))
            if not front or not back:
                continue
            dedupe_key = self._normalize_card_key(front)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            card_number = start_index + offset
            cleaned_cards.append(
                {
                    "id": f"{fingerprint}_card_{card_number}",
                    "front": front,
                    "back": back,
                    "hint": self._normalize_hint(card.get("hint")),
                    "tag": self._normalize_tag(card.get("tag")),
                    "source_ref": str(card.get("source_ref") or "").strip(),
                }
            )
            if len(cleaned_cards) >= card_count:
                break
        return cleaned_cards

    async def list_decks(self, *, limit: int = 12, offset: int = 0, tester_id: str = "local-default") -> list[dict[str, Any]]:
        return await self._store.list_flashcard_decks(limit=limit, offset=offset, tester_id=tester_id)

    async def get_deck(self, deck_id: str, tester_id: str = "local-default") -> dict[str, Any] | None:
        return await self._store.get_flashcard_deck(deck_id, tester_id=tester_id)

    async def record_review(self, *, deck_id: str, card_id: str, rating: str, tester_id: str = "local-default") -> dict[str, Any]:
        if rating not in {"got_it", "missed", "skipped"}:
            raise ValueError("rating must be got_it, missed, or skipped")
        return await self._store.record_flashcard_review(deck_id, card_id, rating, tester_id=tester_id)

    async def restart_deck(self, deck_id: str, tester_id: str = "local-default") -> dict[str, Any]:
        return await self._store.reset_flashcard_reviews(deck_id, tester_id=tester_id)

    async def complete_session(
        self,
        *,
        deck_id: str,
        review_mode: str,
        card_ids: list[str] | None = None,
        tester_id: str = "local-default",
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        deck = await self.get_deck(deck_id, tester_id=tester_id)
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
            },
            tester_id=tester_id,
        )
        refreshed_deck = await self.get_deck(deck_id, tester_id=tester_id)
        if refreshed_deck is None:
            raise ValueError(f"Flashcard deck not found: {deck_id}")
        return refreshed_deck, session_review

    async def get_topic_suggestions(
        self,
        *,
        knowledge_base_names: list[str],
        hint: str = "",
        tester_id: str = "local-default",
    ) -> list[str]:
        normalized_kbs = [name.strip() for name in knowledge_base_names if name.strip()]
        if not normalized_kbs:
            return []
        source_context = await self._build_source_context(
            source_type="knowledge",
            topic=hint,
            knowledge_base_names=to_internal_kb_names(normalized_kbs, tester_id),
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

        query = topic.strip() or "Create high-yield study flashcards from this material."
        results: list[dict[str, Any]] = []
        for kb_name in knowledge_base_names:
            try:
                rag_result = await self._rag.search(query=query, kb_name=kb_name, top_k=4)
            except Exception as exc:
                logger.warning("Flashcard RAG lookup failed for %s: %s", kb_name, exc)
                continue
            content = str(rag_result.get("content") or rag_result.get("answer") or "").strip()
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
            raise ValueError(
                "The selected knowledge bases did not return usable study context. Try a topic deck or re-check the KBs."
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
        avoid_fronts: list[str] | None = None,
    ) -> dict[str, Any]:
        llm_config = self._llm.config
        kwargs: dict[str, Any] = {}
        if supports_response_format(llm_config.binding, llm_config.model):
            kwargs["response_format"] = {"type": "json_object"}
        kwargs.update(get_token_limit_kwargs(llm_config.model, max_tokens=2200))

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

        candidate_count = min(max(card_count, 1), 48)
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

        llm_started_at = time.perf_counter()
        raw = await self._llm.complete(
            prompt=user_prompt,
            system_prompt=system_prompt,
            temperature=0.2,
            **kwargs,
        )
        logger.info(
            f"Flashcard LLM generation complete: source_type={source_type} "
            f"requested={card_count} candidate_count={candidate_count} "
            f"model={llm_config.model} elapsed={time.perf_counter() - llm_started_at:.2f}s"
        )
        payload = parse_json_response(raw, logger_instance=logger, fallback={})
        if not isinstance(payload, dict):
            raise ValueError("Flashcard generation returned invalid JSON")
        return payload

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
