import assert from "node:assert/strict";
import test from "node:test";
import {
  advanceFlashcardViewScope,
  createGeneratedFlashcardDeck,
  createGeneratedFlashcardSuccessor,
  isCurrentFlashcardResponse,
  isFlashcardCourseWritable,
  listFlashcardGenerationOperations,
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

test("grounded Flashcard requests use the Course authority routes and idempotency header", async (t) => {
  const calls: Array<{ input: RequestInfo | URL; init?: RequestInit }> = [];
  const originalFetch = globalThis.fetch;
  t.after(() => {
    globalThis.fetch = originalFetch;
  });
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ input, init });
    return new Response(
      JSON.stringify({
        deck_id: "fcd_generated",
        operation: {
          id: "fgo_1",
          owner_user_id: "usr_alice",
          course_id: "crs_biology",
          deck_id: "fcd_generated",
          supersedes_deck_id: null,
          idempotency_key: "idem-1",
          request_fingerprint: "a".repeat(64),
          source_snapshot: [],
          objective_ids: [],
          course_write_epoch: 4,
          deck_write_epoch: 1,
          item_limit: 8,
          context_char_limit: 12000,
          state: "queued",
          error_code: null,
          created_at: 1,
          started_at: null,
          completed_at: null,
          updated_at: 1,
        },
      }),
      { status: 202, headers: { "Content-Type": "application/json" } },
    );
  }) as typeof fetch;

  await createGeneratedFlashcardDeck(
    "crs/bio",
    "Core terms",
    ["src_notes"],
    ["obj_energy"],
    4,
    "idem-1",
  );
  await createGeneratedFlashcardSuccessor(
    "crs/bio",
    "fcd/generated",
    "Core terms v2",
    ["src_notes"],
    [],
    4,
    "idem-2",
  );

  assert.equal(
    String(calls[0].input),
    "/api/v1/courses/crs%2Fbio/flashcard-generation",
  );
  assert.equal(
    String(calls[1].input),
    "/api/v1/courses/crs%2Fbio/flashcards/fcd%2Fgenerated/flashcard-generation",
  );
  assert.equal(
    new Headers(calls[0].init?.headers).get("Idempotency-Key"),
    "idem-1",
  );
  assert.deepEqual(JSON.parse(String(calls[0].init?.body)), {
    title: "Core terms",
    source_ids: ["src_notes"],
    objective_ids: ["obj_energy"],
    expected_course_write_epoch: 4,
    item_limit: 8,
    context_char_limit: 12000,
  });
});

test("grounded Flashcard operation listing is Course scoped", async (t) => {
  const originalFetch = globalThis.fetch;
  let requested = "";
  t.after(() => {
    globalThis.fetch = originalFetch;
  });
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    requested = String(input);
    return new Response(JSON.stringify({ operations: [] }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  }) as typeof fetch;

  assert.deepEqual(await listFlashcardGenerationOperations("crs/bio"), []);
  assert.equal(requested, "/api/v1/courses/crs%2Fbio/flashcard-generation");
});
