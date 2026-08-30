import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

import {
  canApplySessionLoad,
  isCurrentAbortableRequest,
} from "../lib/request-cancellation";

test("a delayed Course A read cannot apply after Course B owns the route", () => {
  const courseA = new AbortController();
  const courseB = new AbortController();
  const courseAEpoch = 1;
  const courseBEpoch = 2;

  assert.equal(isCurrentAbortableRequest(courseAEpoch, courseBEpoch), false);
  assert.equal(isCurrentAbortableRequest(courseBEpoch, courseBEpoch), true);

  courseA.abort();
  assert.equal(isCurrentAbortableRequest(courseAEpoch, courseAEpoch, courseA.signal), false);
});

test("a cancelled or superseded Course A chat snapshot cannot select shared chat state after Course B", () => {
  const courseASession = new AbortController();
  const courseBSession = new AbortController();
  let selectedSession: string | null = null;

  courseASession.abort();
  if (canApplySessionLoad(courseASession.signal)) selectedSession = "course-a-session";
  if (canApplySessionLoad(courseBSession.signal, () => false)) selectedSession = "stale-course-b-session";
  if (canApplySessionLoad(courseBSession.signal, () => true)) selectedSession = "course-b-session";

  assert.equal(selectedSession, "course-b-session");
});

test("learner surfaces use the cancellation guards rather than applying late responses", () => {
  const courseShell = readFileSync(
    path.join(process.cwd(), "components/courses/CourseShell.tsx"),
    "utf8",
  );
  const chatProvider = readFileSync(
    path.join(process.cwd(), "context/UnifiedChatContext.tsx"),
    "utf8",
  );
  const chatPage = readFileSync(
    path.join(process.cwd(), "components/chat/home/UnifiedChatPage.tsx"),
    "utf8",
  );

  assert.match(courseShell, /isCurrentAbortableRequest/);
  assert.match(courseShell, /getCourse\(courseId\)/);
  assert.match(chatProvider, /if \(!canApplySessionLoad\(options\?\.signal, options\?\.isCurrent\)\) return/);
  assert.match(chatPage, /sessionLoadEpochRef/);
  assert.match(chatPage, /isCurrent: current/);
  assert.match(chatPage, /loadAbortRef\.current\?\.abort\(\)/);
});
