import test from "node:test";
import assert from "node:assert/strict";

import {
  courseIdForChatSession,
  courseSelectionStorageKey,
  getRuntimeActiveCourseId,
  isCurrentCourseRequest,
  resolveSessionCourseView,
  setRuntimeActiveCourseId,
  shouldClearArchivedCourseSelection,
  validatedActiveCourseId,
} from "../lib/course-selection";

test("course selection persistence is namespaced by immutable user identity", () => {
  assert.equal(
    courseSelectionStorageKey("u_alice"),
    "dt:courses:active:u_alice",
  );
  assert.notEqual(
    courseSelectionStorageKey("u_alice"),
    courseSelectionStorageKey("u_bob"),
  );
});

test("stale course responses cannot apply after identity or request epoch changes", () => {
  assert.equal(isCurrentCourseRequest(4, 4, "u_bob", "u_bob"), true);
  assert.equal(isCurrentCourseRequest(3, 4, "u_alice", "u_bob"), false);
  assert.equal(isCurrentCourseRequest(4, 4, "u_alice", "u_bob"), false);
});

test("archived and unknown course ids cannot become the active browser course", () => {
  const courses = [
    { id: "crs_active", state: "active" as const },
    { id: "crs_archived", state: "archived" as const },
  ];
  assert.equal(validatedActiveCourseId(courses, "crs_active"), "crs_active");
  assert.equal(validatedActiveCourseId(courses, "crs_archived"), null);
  assert.equal(validatedActiveCourseId(courses, "crs_unknown"), null);
});

test("a delayed archive response cannot clear a newer same-user Course selection", () => {
  setRuntimeActiveCourseId("crs_a");
  const archivedCourseId = "crs_a";

  // The user selects B while the request to archive A is still in flight.
  setRuntimeActiveCourseId("crs_b");

  assert.equal(getRuntimeActiveCourseId(), "crs_b");
  assert.equal(
    shouldClearArchivedCourseSelection(
      getRuntimeActiveCourseId(),
      archivedCourseId,
    ),
    false,
  );
  assert.equal(
    shouldClearArchivedCourseSelection("crs_a", archivedCourseId),
    true,
  );
  setRuntimeActiveCourseId(null);
});

test("loaded course sessions are validated as views without changing the selector", () => {
  const courses = [
    { id: "crs_active", state: "active" as const },
    { id: "crs_archived", state: "archived" as const },
  ];
  assert.deepEqual(resolveSessionCourseView(courses, "crs_active", false), {
    courseId: "crs_active",
    readOnly: false,
  });
  assert.deepEqual(resolveSessionCourseView(courses, "crs_archived", false), {
    courseId: "crs_archived",
    readOnly: true,
  });
  assert.equal(
    resolveSessionCourseView(courses, "crs_active", true).readOnly,
    true,
  );
  assert.equal(
    resolveSessionCourseView(courses, "crs_missing", false).readOnly,
    true,
  );
});

test("only an unbound draft inherits the selected course", () => {
  assert.equal(courseIdForChatSession(null, null, "crs_selected"), "crs_selected");
  assert.equal(
    courseIdForChatSession("session_generic", null, "crs_selected"),
    null,
  );
  assert.equal(
    courseIdForChatSession("session_course", "crs_bound", "crs_selected"),
    "crs_bound",
  );
});
