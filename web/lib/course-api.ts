import { apiFetch, apiUrl } from "@/lib/api";
import type { MasteryMap, NextStep } from "@/lib/learning-api";

export interface Course {
  id: string;
  owner_user_id: string;
  title: string;
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

export async function createCourse(title: string): Promise<Course> {
  return json<Course>(
    await apiFetch(apiUrl("/api/v1/courses"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
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

export async function attachCourseSource(courseId: string, file: File) {
  const body = new FormData();
  body.append("files", file);
  body.append("kind", "document");
  body.append("display_name", file.name);
  return json<CourseSource>(
    await apiFetch(apiUrl(`/api/v1/courses/${courseId}/sources`), {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
      body,
    }),
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
