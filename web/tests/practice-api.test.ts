import assert from "node:assert/strict";
import test from "node:test";

import {
  advancePracticeViewScope,
  formatPracticeScore,
  hasUnsavedPracticeAnswers,
  isCurrentPracticeResponse,
  learnerSafePracticeQuestions,
  listPracticeAttempts,
  practiceLibrarySets,
  preparePracticeRemediationFlashcards,
  updatePracticeGenerationPlan,
  type PracticeGenerationPlan,
  type PracticeGenerationOperation,
  type PracticeRequestScope,
  type PracticeSet,
} from "../lib/practice-api";

const scope = (identity: string | null, courseId: string | null, epoch: number): PracticeRequestScope => ({
  identity,
  courseId,
  epoch,
  viewEpoch: 0,
});

test("Practice remediation asks the server for an owned flashcard brief", async (t) => {
  const originalFetch = globalThis.fetch;
  let requested = "";
  let requestedInit: RequestInit | undefined;
  t.after(() => {
    globalThis.fetch = originalFetch;
  });
  globalThis.fetch = (async (
    input: RequestInfo | URL,
    init?: RequestInit,
  ) => {
    requested = String(input);
    requestedInit = init;
    return new Response(JSON.stringify({}), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  }) as typeof fetch;

  await preparePracticeRemediationFlashcards(
    "crs/bio",
    "pst/one",
    "att/one",
  );
  assert.equal(
    requested,
    "/api/v1/courses/crs%2Fbio/practice/pst%2Fone/attempts/att%2Fone/flashcard-brief",
  );
  assert.equal(requestedInit?.method, "POST");
  assert.deepEqual(JSON.parse(String(requestedInit?.body)), {});
});

test("Practice responses require the same immutable identity, Course, and request epoch", () => {
  const current = scope("usr_alice", "crs_biology", 7);
  assert.equal(isCurrentPracticeResponse(scope("usr_alice", "crs_biology", 7), current), true);
  assert.equal(isCurrentPracticeResponse(scope("usr_bob", "crs_biology", 7), current), false);
  assert.equal(isCurrentPracticeResponse(scope("usr_alice", "crs_calculus", 7), current), false);
  assert.equal(isCurrentPracticeResponse(scope("usr_alice", "crs_biology", 6), current), false);
});

test("Practice stale-response guard fails closed when sign-out clears identity and Course", () => {
  const beforeLogout = scope("usr_alice", "crs_biology", 11);
  const afterLogout = scope(null, null, 12);
  assert.equal(isCurrentPracticeResponse(beforeLogout, afterLogout), false);
  assert.equal(isCurrentPracticeResponse(afterLogout, afterLogout), true);
});

test("delayed Practice set A detail cannot overwrite a newer set B selection", () => {
  const setARequest = scope("usr_alice", "crs_biology", 21);
  const setBSelection = advancePracticeViewScope(setARequest);
  assert.equal(isCurrentPracticeResponse(setARequest, setBSelection), false);
  assert.equal(isCurrentPracticeResponse(setBSelection, setBSelection), true);
});

test("delayed attempt A detail cannot overwrite a newer attempt B selection", () => {
  const attemptARequest = scope("usr_alice", "crs_biology", 22);
  const attemptBSelection = advancePracticeViewScope(attemptARequest);
  assert.equal(isCurrentPracticeResponse(attemptARequest, attemptBSelection), false);
  assert.equal(isCurrentPracticeResponse(attemptBSelection, attemptBSelection), true);
});

test("a new view scope stays current for its own operation completion", () => {
  const creationScope = advancePracticeViewScope(scope("usr_alice", "crs_biology", 23));
  assert.equal(isCurrentPracticeResponse(creationScope, creationScope), true);
});

test("Practice scores render as percentage and exact ratio", () => {
  assert.equal(
    formatPracticeScore({ correct: 1, total: 1, fraction: 1 }),
    "100% (1/1)",
  );
  assert.equal(
    formatPracticeScore({ correct: 2, total: 3, fraction: 2 / 3 }),
    "67% (2/3)",
  );
  assert.equal(formatPracticeScore({ correct: 2, total: 1 }), null);
  assert.equal(formatPracticeScore({ correct: 0, total: 0 }), null);
  assert.equal(formatPracticeScore(null), null);
});

test("Practice submission is blocked until local answer text matches the durable answer revision", () => {
  const answers = [{ attempt_item_id: "ati_1", response: { answer: "saved" }, revision: 2, answered_at: 1 }];
  assert.equal(hasUnsavedPracticeAnswers({ ati_1: "saved" }, answers), false);
  assert.equal(hasUnsavedPracticeAnswers({ ati_1: "changed" }, answers), true);
  assert.equal(hasUnsavedPracticeAnswers({}, answers), true);
});

test("publishing clears draft answer contracts from the learner-side question state", () => {
  const published = learnerSafePracticeQuestions([{
    id: "qst_1", practice_set_revision_id: "prv_1", question_type: "exact",
    prompt: "Question", answer_contract: { kind: "exact", answer: "secret" },
    explanation: "", objective_ids: [], citations: [], ordinal: 1, created_at: 1,
  }]);
  assert.equal(published[0].answer_contract, undefined);
  assert.equal(published[0].prompt, "Question");
});

test("failed unpublished generation shells stay in Activity instead of the Practice library", () => {
  const baseSet: PracticeSet = {
    id: "pst_failed", owner_user_id: "usr_alice", course_id: "crs_biology",
    title: "Unfinished generated quiz", mode: "generated", state: "draft",
    current_revision_id: null, revision: 1, write_epoch: 1,
    created_at: 1, updated_at: 1, archived_at: null,
  };
  const operation: PracticeGenerationOperation = {
    id: "opg_failed", owner_user_id: "usr_alice", course_id: "crs_biology",
    practice_set_id: baseSet.id, practice_set_revision_id: "prv_failed",
    source_snapshot: [], objective_ids: [], item_limit: 3,
    context_char_limit: 1_000, focus: "Review", difficulty: "mixed",
    timing_mode: "untimed", state: "failed", error_code: "provider_failed",
    cancel_requested_at: null, cancelled_at: null, created_at: 1, updated_at: 2,
  };
  const readySet: PracticeSet = {
    ...baseSet, id: "pst_ready", title: "Ready quiz",
    current_revision_id: "prv_ready",
  };
  const recoveredSet: PracticeSet = {
    ...baseSet, id: "pst_recovered", title: "Recovered quiz",
    current_revision_id: "prv_recovered",
  };
  const recoveredFailure = {
    ...operation, id: "opg_recovered", practice_set_id: recoveredSet.id,
  };
  assert.deepEqual(
    practiceLibrarySets(
      [baseSet, readySet, recoveredSet],
      [operation, recoveredFailure],
    ).map((item) => item.id),
    ["pst_ready", "pst_recovered"],
  );
});

test("Practice attempt history requests bounded pages", async (t) => {
  const originalFetch = globalThis.fetch;
  let requested = "";
  t.after(() => {
    globalThis.fetch = originalFetch;
  });
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    requested = String(input);
    return new Response(JSON.stringify({ attempts: [] }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  }) as typeof fetch;

  assert.deepEqual(await listPracticeAttempts("crs/bio", "pst/one", 50), []);
  assert.equal(
    requested,
    "/api/v1/courses/crs%2Fbio/practice/pst%2Fone/attempts?limit=50&offset=50",
  );
});

test("Practice plan updates serialize only the strict update contract", async (t) => {
  const originalFetch = globalThis.fetch;
  let requestedBody: Record<string, unknown> = {};
  t.after(() => {
    globalThis.fetch = originalFetch;
  });
  globalThis.fetch = (async (
    _input: RequestInfo | URL,
    init?: RequestInit,
  ) => {
    requestedBody = JSON.parse(String(init?.body));
    return new Response(JSON.stringify({}), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  }) as typeof fetch;

  const body = {
    title: "Cellular energy",
    focus: "Review ATP",
    source_ids: ["src_notes"],
    objective_ids: [],
    item_limit: 4,
    difficulty: "mixed" as const,
    timing_mode: "practice_timer" as const,
    expected_course_write_epoch: 99,
  };
  await updatePracticeGenerationPlan(
    "crs_biology",
    { id: "pln_owned", revision: 3 } as PracticeGenerationPlan,
    body,
  );

  assert.deepEqual(requestedBody, {
    title: "Cellular energy",
    focus: "Review ATP",
    source_ids: ["src_notes"],
    objective_ids: [],
    item_limit: 4,
    difficulty: "mixed",
    timing_mode: "practice_timer",
    expected_revision: 3,
  });
  assert.equal("expected_course_write_epoch" in requestedBody, false);
});
