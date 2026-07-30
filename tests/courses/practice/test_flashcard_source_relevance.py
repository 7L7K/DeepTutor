from __future__ import annotations

import json
from pathlib import Path

import pytest

from deeptutor.courses.flashcard_generation_models import FlashcardSourceReceipt
from deeptutor.courses.flashcard_generation_provider import (
    DeterministicIndexFlashcardSourceTextResolver,
    FlashcardGenerationFocusUnsupported,
    _focus_score_terms,
    _focus_terms,
)
from deeptutor.courses.service import source_kb_name
from deeptutor.integrations.blueway.snapshot import DATASETS
from deeptutor.services.path_service import PathService


def _write_blueway_index(
    tmp_path: Path,
    *,
    course_id: str,
    receipt: FlashcardSourceReceipt,
) -> PathService:
    paths = PathService(tmp_path / "workspace")
    root = paths.get_knowledge_bases_root()
    index_dir = root / source_kb_name(course_id, receipt.source_id)
    index_dir.mkdir(parents=True)
    bundle = {
        "schema": "teeechr.blueway.course-bundle.v1",
        "records": [
            {
                "kind": "transcripts",
                "record": {
                    "title": "Cellular respiration lecture",
                    "text": "ATP stores cellular energy during respiration.",
                },
            },
            {
                "kind": "capture_metadata",
                "record": {
                    "title": "QR setup recording",
                    "text": "The speaker opened a QR code during setup.",
                },
            },
        ],
    }
    (index_dir / "deterministic-index.json").write_text(
        json.dumps(
            {
                "course_source_content_sha256": receipt.content_sha256,
                "chunks": [{"text": json.dumps(bundle)}],
            }
        ),
        encoding="utf-8",
    )
    return paths


def test_blueway_bundle_records_are_ranked_by_learner_focus(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    course_id = "crs_" + ("c" * 32)
    receipt = FlashcardSourceReceipt(
        source_id="src_" + ("s" * 32),
        source_revision=1,
        content_sha256="a" * 64,
    )
    paths = _write_blueway_index(
        tmp_path,
        course_id=course_id,
        receipt=receipt,
    )
    monkeypatch.setattr(
        "deeptutor.courses.flashcard_generation_provider.get_personal_path_service",
        lambda _owner: paths,
    )

    material = DeterministicIndexFlashcardSourceTextResolver().resolve_for_focus(
        owner_user_id="u_alice",
        course_id=course_id,
        receipts=[receipt],
        context_char_limit=12_000,
        focus="cellular energy",
    )

    assert len(material) == 1
    assert "ATP stores cellular energy" in material[0].text
    assert "QR code" not in material[0].text


def test_unsupported_focus_stops_before_provider_material_is_returned(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    course_id = "crs_" + ("c" * 32)
    receipt = FlashcardSourceReceipt(
        source_id="src_" + ("s" * 32),
        source_revision=1,
        content_sha256="a" * 64,
    )
    paths = _write_blueway_index(
        tmp_path,
        course_id=course_id,
        receipt=receipt,
    )
    monkeypatch.setattr(
        "deeptutor.courses.flashcard_generation_provider.get_personal_path_service",
        lambda _owner: paths,
    )

    with pytest.raises(FlashcardGenerationFocusUnsupported):
        DeterministicIndexFlashcardSourceTextResolver().resolve_for_focus(
            owner_user_id="u_alice",
            course_id=course_id,
            receipts=[receipt],
            context_char_limit=12_000,
            focus="how to bake sourdough bread",
        )


def test_plain_course_source_selects_the_relevant_bounded_window() -> None:
    text = ("unrelated introduction " * 900) + (
        "The citric acid cycle produces electron carriers for respiration."
    )

    excerpt, score = DeterministicIndexFlashcardSourceTextResolver._ranked_excerpt(
        text,
        focus="citric acid cycle",
        limit=12_000,
    )

    assert score > 0
    assert "citric acid cycle" in excerpt


def test_blueway_learner_content_ranks_ahead_of_capture_metadata() -> None:
    bundle = json.dumps(
        {
            "schema": "teeechr.blueway.course-bundle.v1",
            "records": [
                {
                    "kind": "capture_metadata",
                    "record": {"recording_name": "General course overview"},
                },
                {
                    "kind": "source_texts",
                    "record": {
                        "title": "General course overview",
                        "text": "Mitochondria produce ATP through cellular respiration.",
                    },
                },
                {
                    "kind": "capture_notes",
                    "record": {
                        "body": "General course overview includes cellular respiration."
                    },
                },
                {
                    "kind": "syllabus_facts",
                    "record": {
                        "title": "General course overview",
                        "value": "Cellular respiration is a learning objective.",
                    },
                },
            ],
        }
    )

    excerpt, score = DeterministicIndexFlashcardSourceTextResolver._ranked_excerpt(
        bundle,
        focus="general course overview",
        limit=260,
    )

    assert score > 0
    assert '"kind":"source_texts"' in excerpt
    assert '"kind":"capture_metadata"' not in excerpt


def test_blueway_ranking_explicitly_covers_every_export_dataset() -> None:
    priorities = DeterministicIndexFlashcardSourceTextResolver._BLUEWAY_KIND_PRIORITY

    assert set(priorities) == DATASETS
    assert priorities["source_texts"] > priorities["course_profiles"]
    assert priorities["course_profiles"] > priorities["schedule_events"]
    assert priorities["schedule_events"] > priorities["capture_metadata"]


@pytest.mark.parametrize(
    ("focus", "material"),
    [
        ("pH regulation", "The pH changes when hydrogen ion levels rise."),
        ("RNA transcription", "RNA carries the transcribed sequence."),
        ("C++ templates", "C++ templates support generic programming."),
        ("respiración celular", "La respiración celular produce ATP."),
        ("mitochondria", "Mitochondrial membranes support respiration."),
    ],
)
def test_focus_matching_handles_short_symbolic_unicode_and_inflected_terms(
    focus: str,
    material: str,
) -> None:
    assert _focus_score_terms(_focus_terms(focus), material) > 0


def test_focus_matching_does_not_accept_unrelated_shared_prefixes() -> None:
    assert _focus_score_terms(_focus_terms("cellular"), "Celluloid film history.") == 0
