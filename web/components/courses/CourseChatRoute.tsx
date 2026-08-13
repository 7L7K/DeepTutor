"use client";

import Link from "next/link";
import { BookOpen } from "lucide-react";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import UnifiedChatPage from "@/components/chat/home/UnifiedChatPage";
import { useCourses } from "@/context/CourseContext";
import { useCourseShell } from "@/components/courses/CourseShell";
import {
  getCourseChatReadiness,
  type CourseChatReadiness,
} from "@/lib/course-api";
import {
  courseChatPath,
  courseChatReadinessPresentation,
  courseChatRouteMatchesSession,
} from "@/lib/course-chat";
import { getSession } from "@/lib/session-api";

interface CourseChatLoadState {
  requestKey: string;
  readiness: CourseChatReadiness | null;
  error: string | null;
}

export default function CourseChatRoute() {
  const params = useParams<{ courseId: string; sessionId?: string }>();
  const courseId = params.courseId;
  const sessionId = params.sessionId || null;
  const courseShell = useCourseShell();
  const { activeCourse } = useCourses();
  const requestKey = `${courseId}:${sessionId || "new"}`;
  const [loadState, setLoadState] = useState<CourseChatLoadState>({
    requestKey: "",
    readiness: null,
    error: null,
  });
  const { readiness, error } = loadState;

  useEffect(() => {
    if (!courseShell) return;
    let cancelled = false;
    void Promise.all([
      getCourseChatReadiness(courseId),
      sessionId ? getSession(sessionId) : Promise.resolve(null),
    ])
      .then(([loadedReadiness, session]) => {
        if (cancelled) return;
        if (
          courseShell.course.workspace_kind !== "academic_course" ||
          (session &&
            !courseChatRouteMatchesSession(courseShell.course.id, session.course_id))
        ) {
          throw new Error("Course Chat is not available for this URL.");
        }
        setLoadState({
          requestKey,
          readiness: loadedReadiness,
          error: null,
        });
      })
      .catch(() => {
        if (!cancelled) {
          setLoadState({
            requestKey,
            readiness: null,
            error: "Course Chat was not found or is not available to this account.",
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [courseId, courseShell, requestKey, sessionId]);

  if (!courseShell) return null;
  const { course } = courseShell;
  const materialsPath = `/classes/${encodeURIComponent(course.id)}/materials`;
  const presentation = readiness
    ? courseChatReadinessPresentation(readiness)
    : null;

  if (loadState.requestKey !== requestKey) {
    return (
      <main className="px-6 py-10 sm:px-10" aria-busy="true">
        <div className="mx-auto max-w-5xl text-sm text-[var(--muted-foreground)]">
          Loading Course Chat…
        </div>
      </main>
    );
  }

  if (error || !readiness || !presentation) {
    return (
      <main className="px-6 py-10 sm:px-10">
        <div className="mx-auto max-w-5xl">
          <div
            role="alert"
            className="rounded-2xl border border-red-300/60 bg-red-50/60 px-5 py-4 text-sm text-red-900 dark:border-red-900/60 dark:bg-red-950/20 dark:text-red-200"
          >
            {error || "Course Chat is unavailable."}
          </div>
        </div>
      </main>
    );
  }

  if (course.state !== "active") {
    return (
      <main className="px-5 py-4 sm:px-8">
        <div
          role="status"
          aria-live="polite"
          aria-atomic="true"
          className="mx-auto flex max-w-6xl items-start gap-3 border-b border-[var(--border)] px-1 py-3 text-sm"
        >
          <BookOpen aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0 text-[var(--muted-foreground)]" />
          <div>
            <p className="font-medium text-[var(--foreground)]">This archived Class is read-only.</p>
            <p className="mt-0.5 text-[var(--muted-foreground)]">
              Restore the Class from Classes before starting a chat.
            </p>
          </div>
        </div>
      </main>
    );
  }

  if (activeCourse?.id !== course.id) {
    return (
      <main className="px-6 py-10 sm:px-10" aria-busy="true">
        <div className="mx-auto max-w-5xl text-sm text-[var(--muted-foreground)]">
          Binding Chat to {course.title}…
        </div>
      </main>
    );
  }

  return (
    <main className="flex min-h-[520px] min-h-0 flex-1 flex-col" data-testid="course-chat-route">
      <div
        role="status"
        aria-live="polite"
        aria-atomic="true"
        data-testid="course-chat-status"
        className="shrink-0 border-b border-[var(--border)] bg-[var(--card)] px-5 py-2.5 sm:px-8"
      >
        <div className="mx-auto flex w-full max-w-[960px] items-center gap-2.5 text-sm">
          <BookOpen aria-hidden="true" className="h-4 w-4 shrink-0 text-[var(--muted-foreground)]" />
          <p className="min-w-0 flex-1 text-[var(--muted-foreground)]">
            <span className="font-medium text-[var(--foreground)]">{presentation.title}</span>{" "}
            {presentation.body}
          </p>
          {presentation.action ? (
          <Link
            href={materialsPath}
            className="inline-flex min-h-11 shrink-0 items-center rounded-md px-2.5 text-sm font-medium text-[var(--foreground)] hover:bg-[var(--muted)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
          >
            {presentation.action}
          </Link>
          ) : null}
        </div>
      </div>
      <div className="min-h-0 flex-1">
        <UnifiedChatPage
          routeCourseId={course.id}
          routeSessionId={sessionId}
          courseRouteBase={courseChatPath(course.id)}
          courseReadiness={readiness}
          courseTitle={course.title}
          hideCourseBar
        />
      </div>
    </main>
  );
}
