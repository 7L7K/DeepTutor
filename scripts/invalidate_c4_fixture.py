#!/usr/bin/env python3
"""Invalidate one disposable C4 question after the learner has graded."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deeptutor.courses.content_quality_repository import CourseContentQualityRepository
from deeptutor.courses.content_quality_service import CourseContentQualityService
from deeptutor.courses.practice_repository import CoursePracticeRepository
from deeptutor.courses.practice_service import CoursePracticeService
from deeptutor.courses.repository import CourseRepository
from deeptutor.multi_user.paths import get_personal_path_service


def main() -> None:
    owner_id, fixture_path = sys.argv[1], Path(sys.argv[2])
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    paths = get_personal_path_service(owner_id)
    courses = CourseRepository(paths.get_courses_db(), owner_id)
    practice = CoursePracticeService(CoursePracticeRepository(courses))
    quality = CourseContentQualityService(CourseContentQualityRepository(courses))
    questions = practice.list_questions(
        fixture["course_id"],
        fixture["practice"]["practice_set_id"],
        fixture["practice"]["revision_id"],
    )
    assert len(questions) == 3
    question = questions[1]
    report = quality.report_question(
        fixture["course_id"],
        fixture["practice"]["practice_set_id"],
        fixture["practice"]["revision_id"],
        question.id,
        reason="C4 disposable invalidation proof",
    )
    resolved, evidence_ids = quality.resolve_report(
        fixture["course_id"],
        report["id"],
        decision="invalidate",
        reviewer_user_id="c4_fixture_reviewer",
        note="C4 disposable invalidation proof",
    )
    assert resolved["state"] == "invalidated"
    fixture["invalidation"] = {
        "question_id": question.id,
        "report_id": report["id"],
        "state": resolved["state"],
        "evidence_ids": evidence_ids,
        "reviewer_user_id": "c4_fixture_reviewer",
    }
    fixture_path.write_text(json.dumps(fixture, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    fixture_path.chmod(0o600)
    print(json.dumps(fixture["invalidation"], sort_keys=True))


if __name__ == "__main__":
    main()
