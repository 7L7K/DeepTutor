import assert from "node:assert/strict";
import test from "node:test";

import {
  archiveCourseSource,
  attachCourseSource,
  getCourseCapabilities,
  type CourseSource,
} from "../lib/course-api";

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
