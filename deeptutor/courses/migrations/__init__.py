"""Versioned schema authority for private Course databases."""

from .runner import (
    CourseMigrationError,
    CourseSchemaMismatchError,
    ensure_course_schema,
)

__all__ = [
    "CourseMigrationError",
    "CourseSchemaMismatchError",
    "ensure_course_schema",
]
