"use client";

import Link from "next/link";
import { BookOpen, MessageSquare } from "lucide-react";
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

  if (course.state !== "active" || !presentation.allowChat) {
    return (
      <main className="px-5 py-7 sm:px-8">
        <div className="mx-auto max-w-3xl">
          <section className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-6">
            <div className="flex items-start gap-3">
              <MessageSquare className="mt-0.5 h-5 w-5 text-[var(--muted-foreground)]" />
              <div>
                <h2 className="text-xl font-semibold text-[var(--foreground)]">
                  {course.state === "active"
                    ? presentation.title
                    : "This archived Course is read-only."}
                </h2>
                <p className="mt-2 text-sm leading-6 text-[var(--muted-foreground)]">
                  {course.state === "active"
                    ? presentation.body
                    : "Restore the Course from Classes before starting a grounded Chat."}
                </p>
                {course.state === "active" && presentation.action ? (
                  <Link
                    href={materialsPath}
                    className="mt-5 inline-flex items-center gap-2 rounded-xl bg-[var(--primary)] px-4 py-2 text-sm font-medium text-[var(--primary-foreground)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
                  >
                    <BookOpen size={16} /> {presentation.action}
                  </Link>
                ) : null}
              </div>
            </div>
          </section>
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
      {readiness.state === "partial" ? (
        <div className="shrink-0 border-b border-[var(--border)] bg-[var(--card)] px-5 py-2 text-center text-xs text-[var(--muted-foreground)] sm:px-8">
          <Link
            href={materialsPath}
            className="rounded-md px-2 py-1 hover:text-[var(--foreground)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
          >
            {presentation.body}
          </Link>
        </div>
      ) : null}
      <div className="min-h-0 flex-1">
        <UnifiedChatPage
          routeCourseId={course.id}
          routeSessionId={sessionId}
          courseRouteBase={courseChatPath(course.id)}
          courseReadiness={readiness}
          hideCourseBar
        />
      </div>
    </main>
  );
}
