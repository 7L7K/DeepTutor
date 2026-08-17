import type { CourseChatReadiness } from "@/lib/course-api";
import type { StreamEvent } from "@/lib/unified-ws";

export interface CourseCitation {
  schema_version: 1;
  course_id: string;
  source_id: string;
  source_revision: number;
  source_content_hash: string;
  source_title_snapshot: string;
  locator_type: "page" | "slide" | "timestamp" | "section" | null;
  locator_value: string | null;
  retrieval_fragment_id: string | null;
}

export function courseChatPath(courseId: string, sessionId?: string): string {
  const base = `/classes/${encodeURIComponent(courseId)}/chat`;
  return sessionId ? `${base}/${encodeURIComponent(sessionId)}` : base;
}

export const COURSE_NAVIGATION_DESTINATIONS = [
  { key: "overview", label: "Overview", suffix: "" },
  { key: "chat", label: "Chat", suffix: "/chat" },
  { key: "practice", label: "Practice", suffix: "/practice" },
  { key: "review", label: "Flashcards", suffix: "/review" },
  { key: "materials", label: "Materials", suffix: "/materials" },
] as const;

export type CourseNavigationSuffix =
  (typeof COURSE_NAVIGATION_DESTINATIONS)[number]["suffix"];

export function courseDestinationPath(
  courseId: string,
  suffix: CourseNavigationSuffix,
): string {
  return `/classes/${encodeURIComponent(courseId)}${suffix}`;
}

export function courseDestinationIsActive(
  pathname: string,
  courseId: string,
  suffix: CourseNavigationSuffix,
): boolean {
  const destinationPath = courseDestinationPath(courseId, suffix);
  if (!suffix) return pathname === destinationPath;
  return pathname === destinationPath || pathname.startsWith(`${destinationPath}/`);
}

export function courseChatRouteMatchesSession(
  routeCourseId: string,
  persistedCourseId: string | null | undefined,
): boolean {
  return Boolean(routeCourseId) && routeCourseId === persistedCourseId;
}

export function academicTermLabel(term: string | null | undefined): string {
  const normalized = String(term || "").trim();
  if (!normalized) return "No term set";
  return normalized
    .split("-")
    .filter(Boolean)
    .map((part) =>
      /^\d+$/.test(part)
        ? part
        : `${part.charAt(0).toUpperCase()}${part.slice(1).toLowerCase()}`,
    )
    .join(" ");
}

/** Everyday learner surfaces omit a missing term instead of showing setup copy. */
export function learnerCourseTermLabel(
  term: string | null | undefined,
): string | null {
  const normalized = String(term || "").trim();
  return normalized ? academicTermLabel(normalized) : null;
}

export function visibleChatKnowledgeReferences(
  references: string[],
  courseMode: boolean,
): string[] {
  if (!courseMode) return references;
  return references.filter(
    (reference) => !reference.startsWith("personal:kb:course_"),
  );
}

export function courseChatReadinessPresentation(readiness: CourseChatReadiness): {
  allowChat: boolean;
  title: string;
  body: string;
  action: string | null;
} {
  const ready = readiness.counts.ready;
  const unavailable = readiness.counts.unavailable;
  if (readiness.state === "no_materials") {
    return {
      allowChat: true,
      title: "Course Chat is ready for general questions.",
      body: "This Course has no materials yet. Answers will be general knowledge, not based on Course materials.",
      action: "Add materials",
    };
  }
  if (readiness.state === "processing") {
    return {
      allowChat: true,
      title: "Course materials are still processing.",
      body: "You can chat now with general knowledge. Course-material grounding will be available when a material is ready.",
      action: "View materials",
    };
  }
  if (readiness.state === "failed") {
    return {
      allowChat: true,
      title: "Course materials could not be prepared for Chat.",
      body: "You can chat now with general knowledge. Open the failed material to restore Course-material grounding.",
      action: "Open materials",
    };
  }
  if (readiness.state === "partial") {
    const unavailableSentence =
      unavailable === 1
        ? "One other material is not currently available."
        : `${unavailable === 2 ? "Two" : unavailable} other materials are not currently available.`;
    return {
      allowChat: true,
      title: "Course Chat is using the ready materials.",
      body: `This answer uses ${ready} ready Course ${ready === 1 ? "material" : "materials"}. ${unavailableSentence}`,
      action: "View materials",
    };
  }
  return {
    allowChat: true,
    title: "Course materials are ready.",
    body: `${ready} Course ${ready === 1 ? "material is" : "materials are"} available for grounded answers.`,
    action: null,
  };
}

function isCourseCitation(value: unknown): value is CourseCitation {
  if (!value || typeof value !== "object") return false;
  const citation = value as Partial<CourseCitation>;
  return (
    citation.schema_version === 1 &&
    typeof citation.course_id === "string" &&
    typeof citation.source_id === "string" &&
    typeof citation.source_revision === "number" &&
    typeof citation.source_content_hash === "string" &&
    typeof citation.source_title_snapshot === "string"
  );
}

export function extractCourseCitations(
  events: StreamEvent[] | undefined,
): CourseCitation[] {
  const citations: CourseCitation[] = [];
  const seen = new Set<string>();
  for (const event of events || []) {
    if (event.type !== "sources") continue;
    const values = (event.metadata as { course_citations?: unknown[] } | undefined)
      ?.course_citations;
    for (const value of values || []) {
      if (!isCourseCitation(value)) continue;
      const key = [
        value.course_id,
        value.source_id,
        value.source_revision,
        value.locator_type,
        value.locator_value,
        value.retrieval_fragment_id,
      ].join(":");
      if (seen.has(key)) continue;
      seen.add(key);
      citations.push(value);
    }
  }
  return citations;
}

export function courseCitationIsAvailable(
  citation: Pick<
    CourseCitation,
    "source_id" | "source_revision" | "source_content_hash"
  >,
  readiness: CourseChatReadiness,
): boolean {
  return readiness.ready_sources.some(
    (source) =>
      source.source_id === citation.source_id &&
      source.revision === citation.source_revision &&
      source.content_sha256 === citation.source_content_hash,
  );
}
