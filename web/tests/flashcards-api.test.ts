import assert from "node:assert/strict";
import test from "node:test";
import {
  advanceFlashcardViewScope,
  cancelFlashcardGeneration,
  consumeFlashcardProposal,
  createGeneratedFlashcardDeck,
  createGeneratedFlashcardSuccessor,
  flashcardProposalStorageKey,
  isCurrentFlashcardResponse,
  isFlashcardCourseWritable,
  listFlashcardDecks,
  listFlashcardGenerationOperations,
  prepareFlashcardGenerationBrief,
  publishFlashcardCandidates,
  requeueAgainCard,
  storeFlashcardProposal,
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
    focus: "Core terms",
    item_limit: 8,
    card_type_mix: ["recall"],
    difficulty: "mixed",
    answer_length: "short",
    include_hints: true,
    context_char_limit: 12000,
  });
});

test("brief, publish, and cancel use separate Course authority routes", async (t) => {
  const calls: Array<{ input: RequestInfo | URL; init?: RequestInit }> = [];
  const originalFetch = globalThis.fetch;
  t.after(() => {
    globalThis.fetch = originalFetch;
  });
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ input, init });
    return new Response(JSON.stringify({}), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  }) as typeof fetch;

  await prepareFlashcardGenerationBrief(
    "crs/bio",
    "Terms",
    ["src_1"],
    [],
    3,
  );
  await publishFlashcardCandidates("crs/bio", "ofg/1", ["cand_1"], 2);
  await cancelFlashcardGeneration("crs/bio", "ofg/1");

  assert.deepEqual(
    calls.map((call) => String(call.input)),
    [
      "/api/v1/courses/crs%2Fbio/flashcard-generation/brief",
      "/api/v1/courses/crs%2Fbio/flashcard-generation/ofg%2F1/publish",
      "/api/v1/courses/crs%2Fbio/flashcard-generation/ofg%2F1/cancel",
    ],
  );
  assert.deepEqual(JSON.parse(String(calls[1].init?.body)), {
    candidate_ids: ["cand_1"],
    expected_candidate_revision: 2,
  });
});

test("flashcard proposals are isolated by identity and Course and consumed once", () => {
  const values = new Map<string, string>();
  const prior = globalThis.sessionStorage;
  Object.defineProperty(globalThis, "sessionStorage", {
    configurable: true,
    value: {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value),
      removeItem: (key: string) => values.delete(key),
    },
  });
  try {
    const proposal = {
      course_id: "crs_bio",
      course_write_epoch: 2,
      brief: {
        focus: "Review cells",
        desired_count: 8,
        card_type_mix: ["recall" as const],
        difficulty: "mixed" as const,
        answer_length: "short" as const,
        include_hints: true,
      },
      source_snapshot: [],
      objective_ids: [],
      origin: {
        kind: "chat" as const,
        session_id: "ses_1",
        message_id: 4,
        practice_attempt_id: null,
      },
      provider_available: true,
      warnings: [],
    };
    storeFlashcardProposal("usr_alice", "crs_bio", proposal);
    assert.equal(
      values.has(flashcardProposalStorageKey("usr_bob", "crs_bio")),
      false,
    );
    assert.deepEqual(
      consumeFlashcardProposal("usr_alice", "crs_bio"),
      proposal,
    );
    assert.equal(consumeFlashcardProposal("usr_alice", "crs_bio"), null);
  } finally {
    Object.defineProperty(globalThis, "sessionStorage", {
      configurable: true,
      value: prior,
    });
  }
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

test("Flashcard deck history requests bounded pages", async (t) => {
  const originalFetch = globalThis.fetch;
  let requested = "";
  t.after(() => {
    globalThis.fetch = originalFetch;
  });
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    requested = String(input);
    return new Response(JSON.stringify({ flashcard_decks: [] }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  }) as typeof fetch;

  assert.deepEqual(await listFlashcardDecks("crs/bio", 50), []);
  assert.equal(
    requested,
    "/api/v1/courses/crs%2Fbio/flashcards?include_archived=true&limit=50&offset=50",
  );
});
