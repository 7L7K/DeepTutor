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
    ["Overview", "Chat", "Practice", "Flashcards", "Materials"],
  );
  assert.equal(
    courseDestinationPath("crs/bio", "/materials"),
    "/classes/crs%2Fbio/materials",
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
  assert.match(source, /shrink-0 whitespace-nowrap/);
  assert.match(source, /aria-current=\{active \? "page" : undefined\}/);
  assert.match(source, /scrollIntoView/);
  assert.match(source, /onFocus=\{revealActiveDestination\}/);
  assert.match(source, /overflow-x-hidden/);
  assert.match(source, /Active course/);
  assert.match(source, /Read-only archived Course/);
  assert.match(source, /text-\[11px\].*uppercase/);
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
  assert.doesNotMatch(overview, /\{course\.title\}/);
  assert.doesNotMatch(overview, /Term: \{course\.term\}/);
  assert.doesNotMatch(overview, /course-chat-link|DestinationCard/);
  assert.match(overview, /Practice performance/);
  assert.match(overview, /Mastery progress/);
  assert.match(composer, /Course sources only/);
  assert.match(courseChat, /hideCourseBar/);
  assert.doesNotMatch(courseChat, /hideCourseScope/);
  assert.match(courseChat, /readiness\.state !== "ready"/);
  assert.match(courseChat, /course-chat-readiness-banner/);
  assert.match(courseChat, /Retry Course Chat/);
  assert.match(courseChat, /setLoadAttempt\(\(attempt\) => attempt \+ 1\)/);
});

test("Course Chat load failures stay inside the current Course", () => {
  const chat = readFileSync(
    path.join(process.cwd(), "components/chat/home/UnifiedChatPage.tsx"),
    "utf8",
  );

  assert.match(chat, /router\.replace\(courseRouteBase \?\? '\/home'/);
});

test("Chat cost details are reserved for administrators", () => {
  const messages = readFileSync(
    path.join(process.cwd(), "components/chat/home/ChatMessages.tsx"),
    "utf8",
  );

  assert.match(messages, /useAuthStatus/);
  assert.match(messages, /const showCostSummary = !authLoading && isAdmin/);
  assert.match(messages, /showCostSummary && costSummary/);
  assert.match(messages, /courseReadiness \? \(/);
});

test("learner chat reads only the learner-safe subagent consult projection", () => {
  const chat = readFileSync(
    path.join(process.cwd(), "components/chat/home/UnifiedChatPage.tsx"),
    "utf8",
  );
  const api = readFileSync(
    path.join(process.cwd(), "lib/subagents-api.ts"),
    "utf8",
  );

  assert.match(chat, /getSubagentConsultSettings/);
  assert.doesNotMatch(chat, /getSubagentSettings/);
  assert.match(
    api,
    /apiUrl\("\/api\/v1\/subagents\/consult-settings"\)/,
  );
});

test("opening a Course enters Overview and the expanded sidebar uses TEEECHR branding", () => {
  const coursePage = readFileSync(
    path.join(process.cwd(), "app/(workspace)/classes/[courseId]/page.tsx"),
    "utf8",
  );
  const sidebar = readFileSync(
    path.join(process.cwd(), "components/sidebar/SidebarShell.tsx"),
    "utf8",
  );

  assert.match(coursePage, /CourseOverview/);
  assert.doesNotMatch(coursePage, /CourseChatRoute/);
  assert.match(sidebar, />\s*TEEECHR\s*</);
  assert.doesNotMatch(sidebar, /src="\/banner\.png"/);
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

test("readiness presentation keeps Chat usable without ready materials", async () => {
  const { courseChatReadinessPresentation } = await import("../lib/course-chat");

  assert.deepEqual(
    courseChatReadinessPresentation({
      state: "no_materials",
      counts: { ready: 0, processing: 0, failed: 0, unavailable: 0, total: 0 },
      ready_sources: [],
    }),
    {
      allowChat: true,
      title: "Course Chat is ready for general questions.",
      body: "This Course has no materials yet. Answers will be general knowledge, not based on Course materials.",
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
      title: "Course materials are still processing.",
      body: "You can chat now with general knowledge. Course-material grounding will be available when a material is ready.",
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
      title: "Course materials could not be prepared for Chat.",
      body: "You can chat now with general knowledge. Open the failed material to restore Course-material grounding.",
      action: "Open materials",
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

  assert.deepEqual(presentation, {
    allowChat: true,
    title: "Course Chat is using the ready materials.",
    body: "This answer uses 2 ready Course materials. Two other materials are not currently available.",
    action: "View materials",
  });
});

test("ready Course Chat stays quiet while archived Courses remain blocked", async () => {
  const { courseChatReadinessPresentation } = await import("../lib/course-chat");
  const courseChat = readFileSync(
    path.join(process.cwd(), "components/courses/CourseChatRoute.tsx"),
    "utf8",
  );

  assert.deepEqual(
    courseChatReadinessPresentation({
      state: "ready",
      counts: { ready: 1, processing: 0, failed: 0, unavailable: 0, total: 1 },
      ready_sources: [READY_SOURCE],
    }),
    {
      allowChat: true,
      title: "Course materials are ready.",
      body: "1 Course material is available for grounded answers.",
      action: null,
    },
  );
  assert.match(courseChat, /readiness\.state !== "ready"/);
  assert.match(courseChat, /course\.state !== "active"/);
  assert.match(courseChat, /This archived Course is read-only\./);
  assert.match(
    courseChat,
    /Restore the Course from Classes before starting a grounded Chat\./,
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
