import assert from "node:assert/strict";
import test from "node:test";

import {
  canShowCourseLearnerActions,
  isCurrentCourseLearnerAction,
  requestCourseLearnerAction,
  type CourseLearnerActionScope,
} from "../lib/course-actions-api";

const scope = (
  userId: string | null,
  courseId: string | null,
  sessionId: string | null,
  messageId: number | null,
  epoch: number,
): CourseLearnerActionScope => ({ userId, courseId, sessionId, messageId, epoch });

test("learner-action responses require exact Course, session, message, and epoch", () => {
  const current = scope("usr_alice", "crs_bio", "ses_1", 41, 5);
  assert.equal(isCurrentCourseLearnerAction(current, current), true);
  assert.equal(
    isCurrentCourseLearnerAction(
      scope("usr_bob", "crs_bio", "ses_1", 41, 5),
      current,
    ),
    false,
  );
  assert.equal(
    isCurrentCourseLearnerAction(
      scope("usr_alice", "crs_math", "ses_1", 41, 5),
      current,
    ),
    false,
  );
  assert.equal(
    isCurrentCourseLearnerAction(
      scope("usr_alice", "crs_bio", "ses_2", 41, 5),
      current,
    ),
    false,
  );
  assert.equal(
    isCurrentCourseLearnerAction(
      scope("usr_alice", "crs_bio", "ses_1", 42, 5),
      current,
    ),
    false,
  );
  assert.equal(
    isCurrentCourseLearnerAction(
      scope("usr_alice", "crs_bio", "ses_1", 41, 6),
      current,
    ),
    false,
  );
});

test("learner-action chips appear only on the last persisted completed Course assistant turn", () => {
  const eligible = {
    courseActionsEnabled: true,
    isStreaming: false,
    isLastAssistant: true,
    role: "assistant" as const,
    messageId: 41,
    hasVisibleContent: true,
  };
  assert.equal(canShowCourseLearnerActions(eligible), true);
  assert.equal(
    canShowCourseLearnerActions({ ...eligible, courseActionsEnabled: false }),
    false,
  );
  assert.equal(
    canShowCourseLearnerActions({ ...eligible, isStreaming: true }),
    false,
  );
  assert.equal(
    canShowCourseLearnerActions({ ...eligible, isLastAssistant: false }),
    false,
  );
  assert.equal(
    canShowCourseLearnerActions({ ...eligible, messageId: undefined }),
    false,
  );
});

test("learner-action request carries identity bindings but no prompt or source authority", async (t) => {
  const originalFetch = globalThis.fetch;
  let requestedUrl = "";
  let requestedInit: RequestInit | undefined;
  t.after(() => {
    globalThis.fetch = originalFetch;
  });
  globalThis.fetch = (async (
    input: RequestInfo | URL,
    init?: RequestInit,
  ) => {
    requestedUrl = String(input);
    requestedInit = init;
    return new Response(
      JSON.stringify({
        action: "quiz_me",
        course_id: "crs/bio",
        course_revision: 3,
        course_write_epoch: 2,
        destination: "practice",
        session_id: "ses_1",
        parent_message_id: 41,
        objective_ids: ["obj_1"],
        source_ids: ["src_1"],
        reason_code: "course_sources",
        operation_id: "opg_1",
        practice_set_id: "pst_1",
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
  }) as typeof fetch;

  await requestCourseLearnerAction("crs/bio", {
    action: "quiz_me",
    sessionId: "ses_1",
    assistantMessageId: 41,
    idempotencyKey: "action-once",
    expectedCourseRevision: 3,
    expectedCourseWriteEpoch: 2,
  });

  assert.equal(requestedUrl, "/api/v1/courses/crs%2Fbio/learner-actions");
  const body = JSON.parse(String(requestedInit?.body));
  assert.deepEqual(body, {
    action: "quiz_me",
    session_id: "ses_1",
    assistant_message_id: 41,
    idempotency_key: "action-once",
    expected_course_revision: 3,
    expected_course_write_epoch: 2,
  });
  for (const forbidden of [
    "prompt",
    "source_ids",
    "objective_ids",
    "knowledge_base",
    "provider",
    "tools",
    "owner_user_id",
  ]) {
    assert.equal(forbidden in body, false);
  }
});
