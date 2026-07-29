import assert from "node:assert/strict";
import test from "node:test";
import {
  advanceFlashcardViewScope,
  isCurrentFlashcardResponse,
  isFlashcardCourseWritable,
  requeueAgainCard,
  type FlashcardRequestScope,
} from "../lib/flashcards-api";

const scope = (
  identity: string | null,
  courseId: string | null,
  epoch: number,
): FlashcardRequestScope => ({ identity, courseId, epoch, viewEpoch: 0 });

test("Flashcard results require the exact identity, Course, and request epoch", () => {
  const current = scope("usr_alice", "crs_biology", 5);
  assert.equal(isCurrentFlashcardResponse(current, current), true);
  assert.equal(
    isCurrentFlashcardResponse(scope("usr_bob", "crs_biology", 5), current),
    false,
  );
  assert.equal(
    isCurrentFlashcardResponse(scope("usr_alice", "crs_calculus", 5), current),
    false,
  );
  assert.equal(
    isCurrentFlashcardResponse(scope("usr_alice", "crs_biology", 4), current),
    false,
  );
});

test("logout and deck selection invalidate delayed Flashcard results", () => {
  const request = scope("usr_alice", "crs_biology", 8);
  assert.equal(
    isCurrentFlashcardResponse(request, scope(null, null, 9)),
    false,
  );
  const nextDeck = advanceFlashcardViewScope(request);
  assert.equal(isCurrentFlashcardResponse(request, nextDeck), false);
  assert.equal(isCurrentFlashcardResponse(nextDeck, nextDeck), true);
});

test("Again requeues a missed card while other ratings complete the pass", () => {
  assert.deepEqual(requeueAgainCard(["a", "b"], "a", "again"), ["a", "b", "a"]);
  assert.deepEqual(requeueAgainCard(["a", "b"], "a", "hard"), ["a", "b"]);
  assert.deepEqual(requeueAgainCard(["a", "b"], "a", "good"), ["a", "b"]);
  assert.deepEqual(requeueAgainCard(["a", "b"], "a", "easy"), ["a", "b"]);
});

test("archived or missing Courses cannot start or mutate Flashcard work", () => {
  assert.equal(isFlashcardCourseWritable("active"), true);
  assert.equal(isFlashcardCourseWritable("archived"), false);
  assert.equal(isFlashcardCourseWritable(null), false);
  assert.equal(isFlashcardCourseWritable(undefined), false);
});
