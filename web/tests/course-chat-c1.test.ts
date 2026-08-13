import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import path from "node:path";

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
  const { academicTermLabel, learnerCourseTermLabel } = await import(
    "../lib/course-chat"
  );

  assert.equal(academicTermLabel("fall-2026"), "Fall 2026");
  assert.equal(academicTermLabel("spring-2027"), "Spring 2027");
  assert.equal(academicTermLabel(null), "No term set");
  assert.equal(learnerCourseTermLabel(null), null);
  assert.equal(learnerCourseTermLabel("  fall-2026 "), "Fall 2026");
});

test("Course navigation preserves the Course ID and marks the active destination", async () => {
  const {
    COURSE_NAVIGATION_DESTINATIONS,
    courseDestinationIsActive,
    courseDestinationPath,
  } = await import("../lib/course-chat");

  assert.deepEqual(
    COURSE_NAVIGATION_DESTINATIONS.map((destination) => destination.label),
    ["Chat", "Materials", "Practice", "Review"],
  );
  assert.equal(
    courseDestinationPath("crs/bio", "/materials"),
    "/classes/crs%2Fbio/materials",
  );
  assert.equal(
    courseDestinationIsActive(
      "/classes/crs%2Fbio/chat/session-1",
      "crs/bio",
      "",
    ),
    true,
  );
  assert.equal(
    courseDestinationIsActive(
      "/classes/crs%2Fbio/materials",
      "crs/bio",
      "/materials",
    ),
    true,
  );
  assert.equal(
    courseDestinationIsActive(
      "/classes/crs%2Fbio/materials",
      "crs/other",
      "/materials",
    ),
    false,
  );
});

test("CourseShell contains the mobile navigation and focus-visibility contract", () => {
  const source = readFileSync(
    path.join(process.cwd(), "components/courses/CourseShell.tsx"),
    "utf8",
  );

  assert.match(source, /overflow-x-auto/);
  assert.match(source, /min-h-11 shrink-0 items-center whitespace-nowrap/);
  assert.match(source, /aria-current=\{active \? "page" : undefined\}/);
  assert.match(source, /scrollIntoView/);
  assert.match(source, /onFocus=\{revealActiveDestination\}/);
  assert.match(source, /overflow-x-hidden/);
});

test("the mobile app shell renders the learner-facing TEEECHR wordmark", () => {
  const source = readFileSync(
    path.join(process.cwd(), "components/layout/AppShell.tsx"),
    "utf8",
  );

  assert.match(source, /const PRODUCT_NAME = "TEEECHR"/);
  assert.match(source, /\{PRODUCT_NAME\}/);
  assert.doesNotMatch(source, /banner\.png/);
});

test("General Study keeps its label without the Course-only selector bar", () => {
  const source = readFileSync(
    path.join(
      process.cwd(),
      "components/chat/home/GeneralStudyWorkspace.tsx",
    ),
    "utf8",
  );

  assert.match(source, /hideCourseBar/);
  assert.match(source, /hideCourseScope/);
  assert.match(source, /surfaceLabel="General Study"/);
});

test("learner shells do not expose unqualified Progress or Course scope copy", () => {
  const overview = readFileSync(
    path.join(process.cwd(), "components/courses/CourseOverview.tsx"),
    "utf8",
  );
  const composer = readFileSync(
    path.join(process.cwd(), "components/chat/home/ChatComposer.tsx"),
    "utf8",
  );
  const courseChat = readFileSync(
    path.join(process.cwd(), "components/courses/CourseChatRoute.tsx"),
    "utf8",
  );

  assert.doesNotMatch(overview, /Progress and recommendations/);
  assert.doesNotMatch(overview, /Not available in this slice/);
  assert.match(composer, /Course sources only/);
  assert.match(courseChat, /hideCourseBar/);
  assert.doesNotMatch(courseChat, /hideCourseScope/);
});

test("Course Chat hides internal managed knowledge references", async () => {
  const { visibleChatKnowledgeReferences } = await import("../lib/course-chat");
  const references = [
    "personal:kb:course_crs_bio_src_notes",
    "personal:kb:general-study",
  ];

  assert.deepEqual(visibleChatKnowledgeReferences(references, true), [
    "personal:kb:general-study",
  ]);
  assert.deepEqual(visibleChatKnowledgeReferences(references, false), references);
});

test("Course answers expose their immutable general or grounded authority", async () => {
  const { courseAnswerMode } = await import("../lib/course-chat");
  const event = (course_grounding: string) => ({
    type: "content" as const,
    source: "course_grounding",
    stage: "",
    content: "Answer",
    metadata: { course_grounding },
    timestamp: 1,
  });

  assert.equal(courseAnswerMode([event("general_knowledge")]), "general_knowledge");
  assert.equal(courseAnswerMode([event("supported")]), "class_materials");
  assert.equal(courseAnswerMode([event("unsupported")]), null);

  const messages = readFileSync(
    path.join(process.cwd(), "components/chat/home/ChatMessages.tsx"),
    "utf8",
  );
  assert.match(messages, /General knowledge/);
  assert.match(messages, /Not based on Class materials/);
  assert.match(messages, /Based on Class materials/);
});

test("readiness presentation keeps active Class Chat available with truthful material mode", async () => {
  const { courseChatReadinessPresentation } = await import("../lib/course-chat");

  assert.deepEqual(
    courseChatReadinessPresentation({
      state: "no_materials",
      counts: { ready: 0, processing: 0, failed: 0, unavailable: 0, total: 0 },
      ready_sources: [],
    }),
    {
      allowChat: true,
      title: "No Class materials yet.",
      body: "Answers use general knowledge and are not based on Class materials.",
      action: "Add materials",
    },
  );
  assert.deepEqual(
    courseChatReadinessPresentation({
      state: "processing",
      counts: { ready: 0, processing: 1, failed: 0, unavailable: 1, total: 1 },
      ready_sources: [],
    }),
    {
      allowChat: true,
      title: "Class materials are processing.",
      body: "Answers use general knowledge and are not based on Class materials.",
      action: "View materials",
    },
  );
  assert.deepEqual(
    courseChatReadinessPresentation({
      state: "failed",
      counts: { ready: 0, processing: 0, failed: 2, unavailable: 2, total: 2 },
      ready_sources: [],
    }),
    {
      allowChat: true,
      title: "Class materials need review.",
      body: "Answers use general knowledge and are not based on Class materials.",
      action: "Review materials",
    },
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
    "Answers use 2 ready Class materials. Two other materials are not currently available.",
  );
});

test("Class Chat source keeps active composers available and gives them Class context", () => {
  const courseChat = readFileSync(
    path.join(process.cwd(), "components/courses/CourseChatRoute.tsx"),
    "utf8",
  );
  const chatPage = readFileSync(
    path.join(
      process.cwd(),
      "app/(workspace)/classes/[courseId]/page.tsx",
    ),
    "utf8",
  );
  const compatibilityPage = readFileSync(
    path.join(
      process.cwd(),
      "app/(workspace)/classes/[courseId]/chat/page.tsx",
    ),
    "utf8",
  );
  const unifiedChat = readFileSync(
    path.join(process.cwd(), "components/chat/home/UnifiedChatPage.tsx"),
    "utf8",
  );

  assert.match(courseChat, /role="status"/);
  assert.match(courseChat, /aria-live="polite"/);
  assert.match(courseChat, /courseTitle=\{course.title\}/);
  assert.doesNotMatch(courseChat, /!presentation\.allowChat/);
  assert.match(chatPage, /<CourseChatRoute/);
  assert.match(compatibilityPage, /redirect\(/);
  assert.match(unifiedChat, /Ask a question about \$\{courseTitle\}/);
  assert.match(unifiedChat, /inputPlaceholder=\{courseInputPlaceholder\}/);
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
