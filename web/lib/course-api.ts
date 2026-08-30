import { apiFetch, apiUrl } from "./api";
import type { MasteryMap, NextStep } from "./learning-api";

export interface Course {
  id: string;
  owner_user_id: string;
  title: string;
  term?: string | null;
  workspace_kind: "academic_course" | "general_study";
  state: "active" | "archived";
  revision: number;
  write_epoch: number;
  managed_kb_ref?: string | null;
  created_at: number;
  updated_at: number;
  archived_at?: number | null;
}

export interface CourseSource {
  id: string;
  course_id: string;
  kind: string;
  display_name: string;
  state: "processing" | "ready" | "failed" | "archived";
  manifest: Array<Record<string, unknown>>;
  content_sha256: string;
  revision: number;
  operation_id?: string | null;
}

export interface CourseCapabilities {
  grounded_generation: boolean;
  practice_generation: boolean;
  flashcard_generation: boolean;
  flashcard_generation_reason: string | null;
  grounded_generation_reason: string | null;
}

export interface CourseChatReadySource {
  source_id: string;
  title: string;
  revision: number;
  content_sha256: string;
}

export interface CourseChatReadiness {
  course_id?: string;
  state: "no_materials" | "processing" | "failed" | "partial" | "ready";
  counts: {
    ready: number;
    processing: number;
    failed: number;
    unavailable: number;
    total: number;
  };
  ready_sources: CourseChatReadySource[];
}

async function json<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(String(body.detail || `Request failed: ${response.status}`));
  }
  return response.json() as Promise<T>;
}

export async function listCourses(): Promise<Course[]> {
  const response = await apiFetch(apiUrl("/api/v1/courses"), { cache: "no-store" });
  return (await json<{ courses: Course[] }>(response)).courses;
}

export async function getCourse(
  courseId: string,
  signal?: AbortSignal,
): Promise<Course> {
  return json<Course>(
    await apiFetch(
      apiUrl(`/api/v1/courses/${encodeURIComponent(courseId)}`),
      { cache: "no-store", signal },
    ),
  );
}

export async function getCourseChatReadiness(
  courseId: string,
): Promise<CourseChatReadiness> {
  return json<CourseChatReadiness>(
    await apiFetch(
      apiUrl(
        `/api/v1/courses/${encodeURIComponent(courseId)}/chat-readiness`,
      ),
      { cache: "no-store" },
    ),
  );
}

export async function getCourseCapabilities(): Promise<CourseCapabilities> {
  const response = await apiFetch(apiUrl("/api/v1/courses"), { cache: "no-store" });
  return (
    await json<{ courses: Course[]; capabilities: CourseCapabilities }>(response)
  ).capabilities;
}

export async function createCourse(title: string): Promise<Course> {
  return json<Course>(
    await apiFetch(apiUrl("/api/v1/courses"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    }),
  );
}

export async function getOrCreateGeneralStudy(): Promise<Course> {
  return json<Course>(
    await apiFetch(apiUrl("/api/v1/courses/general-study"), {
      method: "POST",
    }),
  );
}

async function lifecycle(course: Course, action: "archive" | "restore") {
  return json<Course>(
    await apiFetch(apiUrl(`/api/v1/courses/${course.id}/${action}`), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ expected_revision: course.revision }),
    }),
  );
}

export const archiveCourse = (course: Course) => lifecycle(course, "archive");
export const restoreCourse = (course: Course) => lifecycle(course, "restore");

export async function attachCourseSource(
  courseId: string,
  file: File,
  supersedesSourceId?: string | null,
) {
  const body = new FormData();
  body.append("files", file);
  body.append("kind", "document");
  body.append("display_name", file.name);
  if (supersedesSourceId) {
    body.append("supersedes_source_id", supersedesSourceId);
  }
  return json<CourseSource>(
    await apiFetch(apiUrl(`/api/v1/courses/${courseId}/sources`), {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
      body,
    }),
  );
}

export async function listCourseSources(courseId: string): Promise<CourseSource[]> {
  return (
    await json<{ sources: CourseSource[] }>(
      await apiFetch(apiUrl(`/api/v1/courses/${encodeURIComponent(courseId)}/sources`), {
        cache: "no-store",
      }),
    )
  ).sources;
}

export async function archiveCourseSource(
  courseId: string,
  source: CourseSource,
): Promise<CourseSource> {
  return json<CourseSource>(
    await apiFetch(
      apiUrl(
        `/api/v1/courses/${encodeURIComponent(courseId)}/sources/${encodeURIComponent(source.id)}/archive`,
      ),
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ expected_revision: source.revision }),
      },
    ),
  );
}

export async function getCourseLearning(courseId: string) {
  return json<{
    course_id: string;
    learning_path_id: string;
    initialized: boolean;
    progress: Record<string, unknown> | null;
    next?: NextStep;
    map?: MasteryMap;
  }>(await apiFetch(apiUrl(`/api/v1/courses/${courseId}/learning`), { cache: "no-store" }));
}

export async function initCourseLearning(
  courseId: string,
  modules: Array<Record<string, unknown>>,
) {
  return json<Record<string, unknown>>(
    await apiFetch(apiUrl(`/api/v1/courses/${courseId}/learning/init`), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ modules }),
    }),
  );
}

export async function resetCourseLearning(courseId: string, sessionId?: string | null) {
  return json<Record<string, unknown>>(
    await apiFetch(apiUrl(`/api/v1/courses/${courseId}/learning/reset`), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId || null }),
    }),
  );
}
