import assert from "node:assert/strict";
import test from "node:test";

import {
  advancePracticeViewScope,
  formatPracticeScore,
  hasUnsavedPracticeAnswers,
  isCurrentPracticeResponse,
  learnerSafePracticeQuestions,
  listPracticeAttempts,
  type PracticeRequestScope,
} from "../lib/practice-api";

const scope = (identity: string | null, courseId: string | null, epoch: number): PracticeRequestScope => ({
  identity,
  courseId,
  epoch,
  viewEpoch: 0,
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
