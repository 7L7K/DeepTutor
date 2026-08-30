import assert from "node:assert/strict";
import test from "node:test";

import {
  archiveCourseSource,
  attachCourseSource,
  getCourse,
  getCourseCapabilities,
  type CourseSource,
} from "../lib/course-api";

test("Course detail reads the owner-scoped Course route with its nullable term", async (t) => {
  const originalFetch = globalThis.fetch;
  let requestedUrl = "";
  t.after(() => {
    globalThis.fetch = originalFetch;
  });
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    requestedUrl = String(input);
    return new Response(
      JSON.stringify({
        id: "crs/bio",
        owner_user_id: "u_alice",
        title: "Biology",
        term: null,
        workspace_kind: "academic_course",
        state: "active",
        revision: 1,
        write_epoch: 1,
        managed_kb_ref: null,
        created_at: 1,
        updated_at: 1,
        archived_at: null,
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
  }) as typeof fetch;

  const course = await getCourse("crs/bio");
  assert.equal(course.title, "Biology");
  assert.equal(course.term, null);
  assert.equal(requestedUrl, "/api/v1/courses/crs%2Fbio");
});

test("Course detail forwards navigation cancellation to its owner-scoped read", async (t) => {
  const originalFetch = globalThis.fetch;
  let receivedSignal: AbortSignal | null | undefined;
  t.after(() => {
    globalThis.fetch = originalFetch;
  });
  globalThis.fetch = (async (_input: RequestInfo | URL, init?: RequestInit) => {
    receivedSignal = init?.signal;
    return new Response(JSON.stringify({}), { status: 404 });
  }) as typeof fetch;

  const controller = new AbortController();
  await assert.rejects(() => getCourse("crs_stale", controller.signal));
  assert.equal(receivedSignal, controller.signal);
});

test("Course capability status comes from the authenticated server", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => {
    globalThis.fetch = originalFetch;
  });
  globalThis.fetch = (async () =>
    new Response(
      JSON.stringify({
        courses: [],
        capabilities: {
          grounded_generation: false,
          practice_generation: false,
          flashcard_generation: false,
          flashcard_generation_reason:
            "Flashcard generation is not enabled on this server",
          grounded_generation_reason:
            "Grounded generation is not enabled on this server",
        },
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    )) as typeof fetch;

  assert.deepEqual(await getCourseCapabilities(), {
    grounded_generation: false,
    practice_generation: false,
    flashcard_generation: false,
    flashcard_generation_reason:
      "Flashcard generation is not enabled on this server",
    grounded_generation_reason:
      "Grounded generation is not enabled on this server",
  });
});

test("Course source replacement preserves supersession lineage", async (t) => {
  const originalFetch = globalThis.fetch;
  const requestedEntries = new Map<string, FormDataEntryValue>();
  t.after(() => {
    globalThis.fetch = originalFetch;
  });
  globalThis.fetch = (async (
    _input: RequestInfo | URL,
    init?: RequestInit,
  ) => {
    const body = init?.body;
    assert.ok(body instanceof FormData);
    body.forEach((value, key) => requestedEntries.set(key, value));
    return new Response(
      JSON.stringify({
        id: "src_new",
        course_id: "crs_bio",
        kind: "document",
        display_name: "notes-v2.pdf",
        state: "processing",
        manifest: [],
        content_sha256: "",
        revision: 1,
        operation_id: "op_2",
      }),
      { status: 202, headers: { "Content-Type": "application/json" } },
    );
  }) as typeof fetch;

  await attachCourseSource(
    "crs_bio",
    new File(["replacement"], "notes-v2.pdf"),
    "src_old",
  );
  assert.equal(requestedEntries.get("supersedes_source_id"), "src_old");
  assert.equal(requestedEntries.get("display_name"), "notes-v2.pdf");
});

test("Course source archive carries the current source revision", async (t) => {
  const originalFetch = globalThis.fetch;
  let requestedUrl = "";
  let requestedInit: RequestInit | undefined;
  t.after(() => {
    globalThis.fetch = originalFetch;
  });
  const source: CourseSource = {
    id: "src/notes",
    course_id: "crs/bio",
    kind: "document",
    display_name: "notes.pdf",
    state: "ready",
    manifest: [],
    content_sha256: "a".repeat(64),
    revision: 4,
    operation_id: "op_1",
  };
  globalThis.fetch = (async (
    input: RequestInfo | URL,
    init?: RequestInit,
  ) => {
    requestedUrl = String(input);
    requestedInit = init;
    return new Response(
      JSON.stringify({ ...source, state: "archived", revision: 5 }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
  }) as typeof fetch;

  const archived = await archiveCourseSource("crs/bio", source);
  assert.equal(archived.state, "archived");
  assert.equal(
    requestedUrl,
    "/api/v1/courses/crs%2Fbio/sources/src%2Fnotes/archive",
  );
  assert.equal(requestedInit?.method, "POST");
  assert.deepEqual(JSON.parse(String(requestedInit?.body)), {
    expected_revision: 4,
  });
});
