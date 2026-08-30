from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi import HTTPException
import pytest

from deeptutor.courses import ingestion
from deeptutor.courses.ingestion import (
    _admit_source_batch,
    _private_tree_size,
    _remove_owned_kb_shard,
    _seal_and_verify_source_storage,
)


def _preflight(*sizes: int) -> list[dict[str, int | str | None]]:
    return [{"path": f"source-{index}.txt", "size_bytes": size} for index, size in enumerate(sizes)]


def test_batch_admission_reserves_index_growth_against_the_full_private_tree(
    tmp_path: Path,
) -> None:
    root = tmp_path / "knowledge"
    (root / "archived-source").mkdir(parents=True)
    (root / "archived-source" / "retained.bin").write_bytes(b"a" * 17)
    (root / "failed-source").mkdir()
    (root / "failed-source" / "partial.bin").write_bytes(b"b" * 23)

    admission = _admit_source_batch(_preflight(1024, 2048), storage_root=root)

    assert admission.input_bytes == 3072
    assert admission.tree_bytes_before == 40
    assert admission.reserved_growth_bytes == ingestion.COURSE_SOURCE_MIN_STORAGE_RESERVATION_BYTES


def test_batch_admission_enforces_file_and_aggregate_boundaries(tmp_path: Path) -> None:
    exact = _admit_source_batch(
        _preflight(ingestion.COURSE_SOURCE_MAX_BATCH_BYTES),
        storage_root=tmp_path / "exact",
    )
    assert exact.input_bytes == ingestion.COURSE_SOURCE_MAX_BATCH_BYTES

    with pytest.raises(HTTPException) as too_large:
        _admit_source_batch(
            _preflight(ingestion.COURSE_SOURCE_MAX_BATCH_BYTES + 1),
            storage_root=tmp_path / "large",
        )
    assert too_large.value.status_code == 413

    with pytest.raises(HTTPException) as too_many:
        _admit_source_batch(
            _preflight(*([1] * (ingestion.COURSE_SOURCE_MAX_FILES + 1))),
            storage_root=tmp_path / "many",
        )
    assert too_many.value.status_code == 413


def test_private_tree_measurement_fails_closed_on_symbolic_links(tmp_path: Path) -> None:
    root = tmp_path / "knowledge"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.write_bytes(b"not owned")
    (root / "unsafe-link").symlink_to(outside)

    with pytest.raises(HTTPException) as failure:
        _private_tree_size(root)
    assert failure.value.status_code == 503


def test_private_tree_measurement_fails_closed_on_hard_links(tmp_path: Path) -> None:
    root = tmp_path / "knowledge"
    root.mkdir()
    source = root / "source.bin"
    source.write_bytes(b"shared inode")
    (root / "linked.bin").hardlink_to(source)

    with pytest.raises(HTTPException) as failure:
        _private_tree_size(root)
    assert failure.value.status_code == 503


def test_index_growth_overflow_removes_only_the_exact_owned_shard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "knowledge"
    owned = root / "course_crs_one_src_one"
    other = root / "course_crs_other_src_other"
    owned.mkdir(parents=True)
    other.mkdir(parents=True)
    (owned / "provider-index.bin").write_bytes(b"x" * 65)
    (other / "retained.bin").write_bytes(b"safe")
    monkeypatch.setattr(
        ingestion,
        "get_personal_path_service",
        lambda _owner: SimpleNamespace(get_knowledge_bases_root=lambda: root),
    )

    with pytest.raises(HTTPException) as failure:
        _seal_and_verify_source_storage(
            {
                "owner_user_id": "u_owner",
                "course_id": "crs_one",
                "source_id": "src_one",
                "base_dir": str(root),
                "kb_name": owned.name,
                "tree_bytes_before": 4,
                "reserved_growth_bytes": 64,
            }
        )

    assert failure.value.status_code == 413
    assert not owned.exists()
    assert (other / "retained.bin").read_bytes() == b"safe"


def test_cleanup_refuses_a_replaced_symbolic_link_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outside = tmp_path / "outside"
    shard = outside / "course_crs_one_src_one"
    shard.mkdir(parents=True)
    retained = shard / "must-remain.bin"
    retained.write_bytes(b"outside")
    linked_root = tmp_path / "knowledge"
    linked_root.symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(
        ingestion,
        "get_personal_path_service",
        lambda _owner: SimpleNamespace(get_knowledge_bases_root=lambda: linked_root),
    )

    _remove_owned_kb_shard(
        {
            "owner_user_id": "u_owner",
            "course_id": "crs_one",
            "source_id": "src_one",
            "base_dir": str(linked_root),
            "kb_name": shard.name,
        }
    )

    assert retained.read_bytes() == b"outside"


@pytest.mark.parametrize(
    ("kb_name", "source_id"),
    [
        (".", "src_one"),
        ("..", "src_one"),
        ("course_crs_one_src_other", "src_one"),
    ],
)
def test_cleanup_rejects_unowned_or_ambiguous_shard_names(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kb_name: str,
    source_id: str,
) -> None:
    root = tmp_path / "knowledge"
    unrelated = root / "course_crs_one_src_other"
    unrelated.mkdir(parents=True)
    retained = unrelated / "retained.bin"
    retained.write_bytes(b"safe")
    monkeypatch.setattr(
        ingestion,
        "get_personal_path_service",
        lambda _owner: SimpleNamespace(get_knowledge_bases_root=lambda: root),
    )

    _remove_owned_kb_shard(
        {
            "owner_user_id": "u_owner",
            "course_id": "crs_one",
            "source_id": source_id,
            "base_dir": str(root),
            "kb_name": kb_name,
        }
    )

    assert retained.read_bytes() == b"safe"


def test_cleanup_rejects_a_noncanonical_knowledge_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canonical = tmp_path / "canonical"
    outside = tmp_path / "outside"
    shard = outside / "course_crs_one_src_one"
    shard.mkdir(parents=True)
    retained = shard / "retained.bin"
    retained.write_bytes(b"safe")
    monkeypatch.setattr(
        ingestion,
        "get_personal_path_service",
        lambda _owner: SimpleNamespace(get_knowledge_bases_root=lambda: canonical),
    )

    _remove_owned_kb_shard(
        {
            "owner_user_id": "u_owner",
            "course_id": "crs_one",
            "source_id": "src_one",
            "base_dir": str(outside),
            "kb_name": shard.name,
        }
    )

    assert retained.read_bytes() == b"safe"
