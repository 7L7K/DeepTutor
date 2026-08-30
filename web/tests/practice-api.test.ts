import assert from "node:assert/strict";
import test from "node:test";

import {
  advancePracticeViewScope,
  autosavePracticeAnswer,
  canStartManualPracticeDraft,
  createPracticeAnswerSaveQueue,
  createPracticeRevision,
  createPracticeSet,
  formatPracticeScore,
  getPracticeAttempt,
  hasUnsavedPracticeAnswers,
  isCurrentPracticeResponse,
  learnerSafePracticeQuestions,
  listPracticeAttempts,
  orderedPracticeOptions,
  practiceLibrarySets,
  practiceResponseValue,
  practiceSetRevisionId,
  preparePracticeRemediationFlashcards,
  reportPracticeQuestion,
  updatePracticeGenerationPlan,
  type PracticeGenerationPlan,
  type PracticeGenerationOperation,
  type PracticeRequestScope,
  type PracticeSet,
  type QuizAttempt,
  type QuizAttemptAnswer,
  type QuizAttemptResponse,
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

test("Practice question reports use the Course-scoped quality endpoint", async (t) => {
  const originalFetch = globalThis.fetch;
  let requested = "";
  let requestedInit: RequestInit | undefined;
  t.after(() => {
    globalThis.fetch = originalFetch;
  });
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    requested = String(input);
    requestedInit = init;
    return new Response(JSON.stringify({ id: "qrep_1", state: "reported" }), { status: 201 });
  }) as typeof fetch;

  await reportPracticeQuestion("crs/bio", "pst/one", "prv/one", "qst/one", "Citation is wrong");
  assert.equal(
    requested,
    "/api/v1/courses/crs%2Fbio/practice/pst%2Fone/revisions/prv%2Fone/questions/qst%2Fone/quality-report",
  );
  assert.equal(requestedInit?.method, "POST");
  assert.deepEqual(JSON.parse(String(requestedInit?.body)), { reason: "Citation is wrong" });
});

test("manual Practice creation uses the existing Course set and revision APIs", async (t) => {
  const originalFetch = globalThis.fetch;
  const requests: Array<{ url: string; init?: RequestInit }> = [];
  t.after(() => {
    globalThis.fetch = originalFetch;
  });
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    requests.push({ url, init });
    const payload = url.endsWith("/revisions")
      ? { id: "prv_1", practice_set_id: "pst_1", state: "draft" }
      : { id: "pst_1", course_id: "crs/bio", state: "draft" };
    return new Response(JSON.stringify(payload), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  }) as typeof fetch;

  await createPracticeSet("crs/bio", "Manual review", 9);
  await createPracticeRevision("crs/bio", "pst/one", 9);

  assert.deepEqual(
    requests.map(({ url, init }) => ({
      url,
      method: init?.method,
      body: JSON.parse(String(init?.body)),
    })),
    [
      {
        url: "/api/v1/courses/crs%2Fbio/practice",
        method: "POST",
        body: { title: "Manual review", expected_course_write_epoch: 9 },
      },
      {
        url: "/api/v1/courses/crs%2Fbio/practice/pst%2Fone/revisions",
        method: "POST",
        body: { expected_course_write_epoch: 9 },
      },
    ],
  );
});

test("Practice sets recover a durable draft identity before publication", () => {
  const practiceSet: PracticeSet = {
    id: "pst_draft", owner_user_id: "usr_alice", course_id: "crs_biology",
    title: "Reload-safe draft", mode: "manual", state: "draft",
    current_revision_id: null, draft_revision_id: "prv_draft",
    revision: 1, write_epoch: 1, created_at: 1, updated_at: 1, archived_at: null,
  };
  assert.equal(practiceSetRevisionId(practiceSet), "prv_draft");
  assert.equal(
    practiceSetRevisionId({
      ...practiceSet,
      current_revision_id: "prv_ready",
      draft_revision_id: "prv_successor",
    }),
    "prv_ready",
  );
  assert.equal(
    practiceSetRevisionId({
      ...practiceSet,
      current_revision_id: null,
      draft_revision_id: null,
    }),
    null,
  );
});

test("manual draft start waits for a settled revision-free detail read", () => {
  const emptySet: PracticeSet = {
    id: "pst_empty", owner_user_id: "usr_alice", course_id: "crs_biology",
    title: "Empty draft", mode: "manual", state: "draft",
    current_revision_id: null, draft_revision_id: null,
    revision: 1, write_epoch: 1, created_at: 1, updated_at: 1, archived_at: null,
  };
  assert.equal(canStartManualPracticeDraft(emptySet, "loaded"), true);
  assert.equal(canStartManualPracticeDraft(emptySet, "loading"), false);
  assert.equal(canStartManualPracticeDraft(emptySet, "error"), false);
  assert.equal(canStartManualPracticeDraft({
    ...emptySet,
    current_revision_id: "prv_ready",
  }, "loading"), false);
  assert.equal(canStartManualPracticeDraft({
    ...emptySet,
    draft_revision_id: "prv_draft",
  }, "error"), false);
  assert.equal(canStartManualPracticeDraft({
    ...emptySet,
    state: "archived",
  }, "loaded"), false);
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
  const answers = [
    { attempt_item_id: "ati_1", response: { answer: "saved" } as const, revision: 2, answered_at: 1 },
    { attempt_item_id: "ati_2", response: { option_id: "opt_blue" } as const, revision: 3, answered_at: 1 },
  ];
  assert.equal(hasUnsavedPracticeAnswers({ ati_1: "saved", ati_2: "opt_blue" }, answers), false);
  assert.equal(hasUnsavedPracticeAnswers({ ati_1: "changed", ati_2: "opt_blue" }, answers), true);
  assert.equal(hasUnsavedPracticeAnswers({ ati_1: "saved", ati_2: "opt_red" }, answers), true);
  assert.equal(hasUnsavedPracticeAnswers({}, answers), true);
  assert.equal(practiceResponseValue(answers[0].response), "saved");
  assert.equal(practiceResponseValue(answers[1].response), "opt_blue");
});

test("Practice answer saves serialize revisions per item and rotate keys only after success", async () => {
  const initialAnswer: QuizAttemptAnswer = {
    attempt_item_id: "ati_1", response: null, revision: 1, answered_at: null,
  };
  const calls: Array<{ revision: number; answer: string; key: string }> = [];
  let keyNumber = 0;
  let activeWrites = 0;
  let maximumActiveWrites = 0;
  const save = async (
    answer: QuizAttemptAnswer,
    response: QuizAttemptResponse,
    key: string,
  ) => {
    activeWrites += 1;
    maximumActiveWrites = Math.max(maximumActiveWrites, activeWrites);
    await Promise.resolve();
    calls.push({
      revision: answer.revision,
      answer: "answer" in response ? response.answer : response.option_id,
      key,
    });
    activeWrites -= 1;
    return { ...answer, response, revision: answer.revision + 1, answered_at: 2 };
  };
  const queue = createPracticeAnswerSaveQueue({
    initialAnswers: [initialAnswer],
    createIdempotencyKey: () => `idem-${++keyNumber}`,
  });

  queue.enqueue("ati_1", { answer: "first" });
  const firstFlush = queue.flush("ati_1", save);
  queue.enqueue("ati_1", { answer: "second" });
  const secondFlush = queue.flush("ati_1", save);
  assert.deepEqual(await Promise.all([firstFlush, secondFlush]), [true, true]);
  assert.equal(maximumActiveWrites, 1);
  assert.deepEqual(calls, [
    { revision: 1, answer: "first", key: "idem-1" },
    { revision: 2, answer: "second", key: "idem-2" },
  ]);
  assert.deepEqual(queue.getAnswer("ati_1")?.response, { answer: "second" });
});

test("Practice answer save retries retain the failed idempotency key", async () => {
  let durable: QuizAttemptAnswer = {
    attempt_item_id: "ati_1", response: null, revision: 1, answered_at: null,
  };
  const keys: string[] = [];
  let keyNumber = 0;
  let fail = true;
  const save = async (
    answer: QuizAttemptAnswer,
    response: QuizAttemptResponse,
    key: string,
  ) => {
    keys.push(key);
    if (fail) throw new Error("offline");
    return { ...answer, response, revision: answer.revision + 1, answered_at: 2 };
  };
  const queue = createPracticeAnswerSaveQueue({
    initialAnswers: [durable],
    createIdempotencyKey: () => `idem-${++keyNumber}`,
  });

  queue.enqueue("ati_1", { answer: "retry me" });
  assert.equal(await queue.flush("ati_1", save), false);
  assert.equal(queue.hasPending("ati_1"), true);
  fail = false;
  assert.equal(await queue.flush("ati_1", save), true);
  assert.deepEqual(keys, ["idem-1", "idem-1"]);
  durable = queue.getAnswer("ati_1")!;
  assert.deepEqual(durable.response, { answer: "retry me" });
});

test("publishing clears every answer-adjacent field while retaining learner-safe options", () => {
  const published = learnerSafePracticeQuestions([{
    id: "qst_1", practice_set_revision_id: "prv_1", question_type: "single_choice",
    prompt: "Question", options: [
      { option_id: "opt_public_a", text: "Visible choice A" },
      { option_id: "opt_public_b", text: "Visible choice B" },
    ],
    answer_contract: { kind: "single_choice_v1", correct_option_id: "opt_public_b" },
    explanation: "Secret explanation", objective_ids: [], citations: [{ evidence_quote: "Secret evidence" }], ordinal: 1, created_at: 1,
  }]);
  assert.equal(published[0].answer_contract, undefined);
  assert.equal(published[0].explanation, undefined);
  assert.equal(published[0].citations, undefined);
  assert.equal(published[0].prompt, "Question");
  assert.deepEqual(published[0].options, [
    { option_id: "opt_public_a", text: "Visible choice A" },
    { option_id: "opt_public_b", text: "Visible choice B" },
  ]);
  assert.equal(JSON.stringify(published).includes("correct_option_id"), false);
  assert.equal(JSON.stringify(published).includes("Secret explanation"), false);
});

test("single-choice rendering follows the exact server-owned option order and fails closed", () => {
  const question = {
    id: "qst_1", practice_set_revision_id: "prv_1", question_type: "single_choice" as const,
    prompt: "Question", options: [
      { option_id: "opt_alpha", text: "Alpha" },
      { option_id: "opt_beta", text: "Beta" },
      { option_id: "opt_gamma", text: "Gamma" },
    ],
    objective_ids: [], ordinal: 1, created_at: 1,
  };
  const item = {
    id: "ati_1", attempt_id: "att_1", question_id: question.id, display_ordinal: 1,
    option_order: ["opt_gamma", "opt_alpha", "opt_beta"], randomized_values: null,
    grading: null, error_type: null, graded_at: null,
  };
  assert.deepEqual(
    orderedPracticeOptions(question, item).map((option) => option.option_id),
    ["opt_gamma", "opt_alpha", "opt_beta"],
  );
  assert.deepEqual(orderedPracticeOptions(question, {
    ...item,
    option_order: ["opt_gamma", "opt_gamma", "opt_beta"],
  }), []);
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

test("an attempt deep link requests the exact attempt instead of scanning history", async (t) => {
  const originalFetch = globalThis.fetch;
  let requested = "";
  let requestedInit: RequestInit | undefined;
  t.after(() => {
    globalThis.fetch = originalFetch;
  });
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    requested = String(input);
    requestedInit = init;
    return new Response(JSON.stringify({
      attempt: { id: "att/deep" },
      items: [],
      answers: [],
    }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  }) as typeof fetch;

  await getPracticeAttempt("crs/bio", "pst/one", "att/deep");
  assert.equal(
    requested,
    "/api/v1/courses/crs%2Fbio/practice/pst%2Fone/attempts/att%2Fdeep",
  );
  assert.equal(requested.includes("limit=50"), false);
  assert.equal(requestedInit?.cache, "no-store");
});

test("Practice autosave serializes the strict single-choice response union", async (t) => {
  const originalFetch = globalThis.fetch;
  let requestedBody: Record<string, unknown> = {};
  let requestedInit: RequestInit | undefined;
  t.after(() => {
    globalThis.fetch = originalFetch;
  });
  globalThis.fetch = (async (_input: RequestInfo | URL, init?: RequestInit) => {
    requestedInit = init;
    requestedBody = JSON.parse(String(init?.body));
    return new Response(JSON.stringify({
      attempt_item_id: "ati_1",
      response: { option_id: "opt_blue" },
      revision: 2,
      answered_at: 2,
    }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  }) as typeof fetch;

  const practiceSet: PracticeSet = {
    id: "pst_1", owner_user_id: "usr_1", course_id: "crs_1", title: "Quiz",
    mode: "generated", state: "draft", current_revision_id: "prv_1",
    revision: 1, write_epoch: 4, created_at: 1, updated_at: 1, archived_at: null,
  };
  const attempt: QuizAttempt = {
    id: "att_1", owner_user_id: "usr_1", course_id: "crs_1",
    practice_set_id: practiceSet.id, practice_set_revision_id: "prv_1",
    timing_mode: "untimed", state: "in_progress", score: null, revision: 1,
    course_write_epoch: 7, practice_set_write_epoch: 4, started_at: 1,
    submitted_at: null, graded_at: null, archived_at: null, updated_at: 1,
  };
  await autosavePracticeAnswer(
    "crs_1",
    practiceSet,
    attempt,
    { attempt_item_id: "ati_1", response: null, revision: 1, answered_at: null },
    { option_id: "opt_blue" },
    "idem-choice-1",
  );
  assert.deepEqual(requestedBody, {
    attempt_item_id: "ati_1",
    response: { option_id: "opt_blue" },
    expected_answer_revision: 1,
    expected_course_write_epoch: 7,
    expected_practice_set_write_epoch: 4,
  });
  assert.equal(requestedInit?.keepalive, true);
  assert.equal(
    "answer" in (requestedBody.response as Record<string, unknown>),
    false,
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
