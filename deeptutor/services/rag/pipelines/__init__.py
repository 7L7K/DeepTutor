"""Pre-configured RAG pipelines.

TEEECHR currently ships with a single built-in provider (`llamaindex`).
Additional providers can still be registered dynamically via the factory layer.
"""

from typing import Any

__all__ = [
    "LlamaIndexPipeline",
]


def __getattr__(name: str) -> Any:
    if name == "LlamaIndexPipeline":
        from .llamaindex import LlamaIndexPipeline

        return LlamaIndexPipeline
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
