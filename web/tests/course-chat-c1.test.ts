import assert from "node:assert/strict";
import test from "node:test";

const READY_SOURCE = {
  source_id: "src_bio",
  title: "Lecture 6.pdf",
  revision: 4,
  content_sha256: "a".repeat(64),
};

test("Course Chat routes preserve exact Course and optional session identity", async () => {
  const { courseChatPath, courseChatRouteMatchesSession } = await import(
    "../lib/course-chat"
  );

  assert.equal(courseChatPath("crs/bio"), "/classes/crs%2Fbio/chat");
  assert.equal(
    courseChatPath("crs/bio", "session/one"),
    "/classes/crs%2Fbio/chat/session%2Fone",
  );
  assert.equal(courseChatRouteMatchesSession("crs_bio", "crs_bio"), true);
  assert.equal(courseChatRouteMatchesSession("crs_bio", "crs_psych"), false);
});

test("canonical academic term keeps identity while rendering a human label", async () => {
  const { academicTermLabel } = await import("../lib/course-chat");

  assert.equal(academicTermLabel("fall-2026"), "Fall 2026");
  assert.equal(academicTermLabel("spring-2027"), "Spring 2027");
  assert.equal(academicTermLabel(null), "Term not linked yet");
});

test("readiness presentation blocks zero, processing, and failed source states", async () => {
  const { courseChatReadinessPresentation } = await import("../lib/course-chat");

  assert.deepEqual(
    courseChatReadinessPresentation({
      state: "no_materials",
      counts: { ready: 0, processing: 0, failed: 0, unavailable: 0, total: 0 },
      ready_sources: [],
    }),
    {
      allowChat: false,
      title: "This Course does not have any materials yet.",
      body: "Add a Course material before asking grounded questions.",
      action: "Add materials",
    },
  );
  assert.equal(
    courseChatReadinessPresentation({
      state: "processing",
      counts: { ready: 0, processing: 1, failed: 0, unavailable: 1, total: 1 },
      ready_sources: [],
    }).allowChat,
    false,
  );
  assert.equal(
    courseChatReadinessPresentation({
      state: "failed",
      counts: { ready: 0, processing: 0, failed: 2, unavailable: 2, total: 2 },
      ready_sources: [],
    }).allowChat,
    false,
  );
});

test("mixed readiness allows Chat and discloses unavailable materials", async () => {
  const { courseChatReadinessPresentation } = await import("../lib/course-chat");

  const presentation = courseChatReadinessPresentation({
    state: "partial",
    counts: { ready: 2, processing: 1, failed: 1, unavailable: 2, total: 4 },
    ready_sources: [READY_SOURCE, { ...READY_SOURCE, source_id: "src_slides" }],
  });

  assert.equal(presentation.allowChat, true);
  assert.equal(
    presentation.body,
    "This answer uses 2 ready Course materials. Two other materials are not currently available.",
  );
});

test("persisted Course citations survive reload and become unavailable safely", async () => {
  const { extractCourseCitations, courseCitationIsAvailable } = await import(
    "../lib/course-chat"
  );
  const citation = {
    schema_version: 1,
    course_id: "crs_bio",
    source_id: "src_bio",
    source_revision: 4,
    source_content_hash: "a".repeat(64),
    source_title_snapshot: "Lecture 6.pdf",
    locator_type: "slide",
    locator_value: "18",
    retrieval_fragment_id: "fragment-18",
  };
  const events = [
    {
      type: "sources" as const,
      source: "course_grounding",
      stage: "",
      content: "",
      metadata: { course_citations: [citation] },
      timestamp: 1,
    },
  ];

  assert.deepEqual(extractCourseCitations(events), [citation]);
  assert.equal(
    courseCitationIsAvailable(citation, {
      state: "ready",
      counts: { ready: 1, processing: 0, failed: 0, unavailable: 0, total: 1 },
      ready_sources: [READY_SOURCE],
    }),
    true,
  );
  assert.equal(
    courseCitationIsAvailable(citation, {
      state: "failed",
      counts: { ready: 0, processing: 0, failed: 0, unavailable: 1, total: 1 },
      ready_sources: [],
    }),
    false,
  );
  assert.equal(citation.source_title_snapshot, "Lecture 6.pdf");
});

test("Course readiness API uses the exact owner-scoped Course route", async (t) => {
  const { getCourseChatReadiness } = await import("../lib/course-api");
  const originalFetch = globalThis.fetch;
  let requestedUrl = "";
  t.after(() => {
    globalThis.fetch = originalFetch;
  });
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    requestedUrl = String(input);
    return new Response(
      JSON.stringify({
        course_id: "crs/bio",
        state: "ready",
        counts: { ready: 1, processing: 0, failed: 0, unavailable: 0, total: 1 },
        ready_sources: [READY_SOURCE],
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
  }) as typeof fetch;

  const readiness = await getCourseChatReadiness("crs/bio");
  assert.equal(readiness.ready_sources[0].source_id, "src_bio");
  assert.equal(requestedUrl, "/api/v1/courses/crs%2Fbio/chat-readiness");
});
