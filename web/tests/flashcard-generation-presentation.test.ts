import assert from "node:assert/strict";
import test from "node:test";

import {
  FLASHCARDS_VIEW_PRESENTATION,
  flashcardCourseSourceLabel,
  flashcardGenerationFailureCategory,
  flashcardGenerationFailurePresentation,
  flashcardGenerationStatePresentation,
  flashcardGenerationUnavailableCopy,
  flashcardsViewFromQuery,
} from "../lib/flashcard-generation-presentation";

test("Course source labels hide internal BlueWay bundle terminology", () => {
  assert.equal(
    flashcardCourseSourceLabel(
      "BlueWay verified course bundle",
      "blueway_course_bundle",
    ),
    "Imported BlueWay Course material",
  );
  assert.equal(
    flashcardCourseSourceLabel("Lecture 4 notes.pdf", "document"),
    "Lecture 4 notes.pdf",
  );
  assert.equal(flashcardCourseSourceLabel("  ", "notes"), "Course material");
});

test("Flashcard views are typed learner navigation with Study as the safe default", () => {
  assert.equal(flashcardsViewFromQuery(null), "study");
  assert.equal(flashcardsViewFromQuery("create"), "create");
  assert.equal(flashcardsViewFromQuery("activity"), "activity");
  assert.equal(flashcardsViewFromQuery("operation-123"), "study");
  assert.deepEqual(
    Object.values(FLASHCARDS_VIEW_PRESENTATION).map((view) => view.label),
    ["Study", "Create", "Activity"],
  );
});

test("Flashcard generation operation states use learner-facing copy", () => {
  assert.deepEqual(flashcardGenerationStatePresentation("queued"), {
    label: "Waiting to start",
    description: "Your card request is waiting to start.",
    kind: "active",
  });
  assert.deepEqual(flashcardGenerationStatePresentation("running"), {
    label: "Creating cards",
    description: "TEEECHR is creating your cards. You can leave this page.",
    kind: "active",
  });
  assert.equal(
    flashcardGenerationStatePresentation("awaiting_review").label,
    "Finishing your cards",
  );
  assert.equal(
    flashcardGenerationStatePresentation("failed").kind,
    "recovery",
  );
  assert.equal(
    flashcardGenerationStatePresentation("cancelled").label,
    "Creation cancelled",
  );
});

test("Flashcard failure codes map to safe learner categories", () => {
  assert.equal(
    flashcardGenerationFailureCategory("provider_failed"),
    "interrupted",
  );
  assert.equal(
    flashcardGenerationFailureCategory("source_changed"),
    "request-needs-update",
  );
  assert.equal(
    flashcardGenerationFailureCategory("invalid_output"), "card-quality");
  assert.equal(flashcardGenerationFailureCategory("quota_exceeded"), "limit-reached");
  assert.equal(flashcardGenerationFailureCategory("diagnostic-only-code"), "unknown");
});

test("Flashcard failure presentation hides raw codes and only retries with server permission", () => {
  const uncertainProvider = flashcardGenerationFailurePresentation(
    "provider_failed",
    false,
  );
  assert.deepEqual(uncertainProvider, {
    title: "We could not create these cards.",
    detail: "Your request is still here.",
    category: "interrupted",
    primaryAction: "change-request",
  });
  assert.doesNotMatch(
    `${uncertainProvider.title} ${uncertainProvider.detail}`,
    /provider_failed/,
  );

  assert.equal(
    flashcardGenerationFailurePresentation("provider_failed", true).primaryAction,
    "try-again",
  );
  assert.equal(
    flashcardGenerationFailurePresentation("source_changed", false).primaryAction,
    "change-request",
  );
  assert.equal(
    flashcardGenerationFailurePresentation("quota_exceeded", true).primaryAction,
    "create-manually",
  );
  assert.equal(
    flashcardGenerationFailurePresentation("cancelled", true).primaryAction,
    "none",
  );
});

test("Flashcard provider-unavailable copy keeps manual fallback visible", () => {
  assert.equal(
    flashcardGenerationUnavailableCopy(
      "Grounded generation is not enabled on this server",
    ),
    "Grounded generation is not enabled on this server. Manual Flashcards remain available.",
  );
  assert.equal(
    flashcardGenerationUnavailableCopy(null),
    "Grounded generation is not enabled on this server. Manual Flashcards remain available.",
  );
});

test("Flashcard provider-unavailable copy does not duplicate fallback", () => {
  assert.equal(
    flashcardGenerationUnavailableCopy(
      "Provider disabled. Manual Flashcards remain available.",
    ),
    "Provider disabled. Manual Flashcards remain available.",
  );
});
