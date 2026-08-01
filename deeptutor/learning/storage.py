from __future__ import annotations

import json
from pathlib import Path
import threading
import time
from uuid import uuid4

from deeptutor.learning.models import LearningProgress
from deeptutor.services.file_io import atomic_write_text as _atomic_write_text
from deeptutor.services.path_service import get_path_service

# Module-level lock so CAS semantics hold across all store instances.
_cas_lock = threading.Lock()


class LearningConflictError(RuntimeError):
    """The caller attempted to overwrite newer persisted learning state."""


class LearningDataError(RuntimeError):
    """Persisted learning JSON exists but cannot be safely interpreted."""


class LearningStore:
    def __init__(self, root: Path | None = None) -> None:
        self._root = root or (get_path_service().get_workspace_dir() / "learning")
        self._root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._root.chmod(0o700)

    def _path(self, book_id: str) -> Path:
        if "/" in book_id or "\\" in book_id or ".." in book_id or ":" in book_id:
            raise ValueError(f"Invalid book_id: {book_id!r}")
        return self._root / f"{book_id}.json"

    def save(self, progress: LearningProgress) -> None:
        with _cas_lock:
            path = self._path(progress.book_id)
            if path.exists():
                try:
                    current = json.loads(path.read_text(encoding="utf-8"))
                    persisted_version = int(current.get("version", 0))
                except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                    raise LearningConflictError(
                        "Persisted learning state is unreadable; refusing to overwrite it"
                    ) from exc
                if persisted_version != progress.version:
                    raise LearningConflictError("Learning state revision is stale")
            elif progress.version != 0:
                raise LearningConflictError("Persisted learning state is missing")

            updated_at = time.time()
            next_version = progress.version + 1
            data = progress.model_dump(mode="json")
            data["updated_at"] = updated_at
            data["version"] = next_version
            text = json.dumps(data, ensure_ascii=False, indent=2)
            _atomic_write_text(path, text)
            progress.updated_at = updated_at
            progress.version = next_version

    def load(self, book_id: str) -> LearningProgress | None:
        path = self._path(book_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return LearningProgress.model_validate(data)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise LearningDataError("Persisted learning state is unreadable") from exc

    def quarantine_corrupt(self, book_id: str) -> Path | None:
        """Preserve an unreadable state file before explicit reinitialization."""
        with _cas_lock:
            path = self._path(book_id)
            if not path.exists():
                return None
            target = path.with_name(
                f".{path.stem}.corrupt-{int(time.time())}-{uuid4().hex[:8]}.json"
            )
            path.replace(target)
            return target

    def delete(self, book_id: str) -> None:
        with _cas_lock:
            path = self._path(book_id)
            if path.exists():
                path.unlink()

    def exists(self, book_id: str) -> bool:
        return self._path(book_id).exists()

    def list_all(self) -> list[str]:
        """Return all book_ids that have stored progress."""
        return sorted(p.stem for p in self._root.glob("*.json") if not p.name.startswith("."))


__all__ = ["LearningConflictError", "LearningDataError", "LearningStore"]
