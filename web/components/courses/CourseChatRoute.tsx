"use client";

import Link from "next/link";
import { ArrowLeft, BookOpen, MessageSquare } from "lucide-react";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import UnifiedChatPage from "@/components/chat/home/UnifiedChatPage";
import { useCourses } from "@/context/CourseContext";
import {
  getCourse,
  getCourseChatReadiness,
  type Course,
  type CourseChatReadiness,
} from "@/lib/course-api";
import {
  academicTermLabel,
  courseChatPath,
  courseChatReadinessPresentation,
  courseChatRouteMatchesSession,
} from "@/lib/course-chat";
import { getSession } from "@/lib/session-api";

interface LoadedCourseChat {
  course: Course;
  readiness: CourseChatReadiness;
}

interface CourseChatLoadState {
  requestKey: string;
  loaded: LoadedCourseChat | null;
  error: string | null;
}

export default function CourseChatRoute() {
  const params = useParams<{ courseId: string; sessionId?: string }>();
  const courseId = params.courseId;
  const sessionId = params.sessionId || null;
  const {
    courses,
    activeCourse,
    loading: coursesLoading,
    selectCourse,
  } = useCourses();
  const requestKey = `${courseId}:${sessionId || "new"}`;
  const [loadState, setLoadState] = useState<CourseChatLoadState>({
    requestKey: "",
    loaded: null,
    error: null,
  });
  const { loaded, error } = loadState;

  useEffect(() => {
    let cancelled = false;
    void Promise.all([
      getCourse(courseId),
      getCourseChatReadiness(courseId),
      sessionId ? getSession(sessionId) : Promise.resolve(null),
    ])
      .then(([course, readiness, session]) => {
        if (cancelled) return;
        if (
          course.workspace_kind !== "academic_course" ||
          (session &&
            !courseChatRouteMatchesSession(course.id, session.course_id))
        ) {
          throw new Error("Course Chat is not available for this URL.");
        }
        setLoadState({
          requestKey,
          loaded: { course, readiness },
          error: null,
        });
      })
      .catch(() => {
        if (!cancelled) {
          setLoadState({
            requestKey,
            loaded: null,
            error: "Course Chat was not found or is not available to this account.",
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [courseId, requestKey, sessionId]);

  const contextCourse = useMemo(
    () => courses.find((course) => course.id === courseId) || null,
    [courseId, courses],
  );

  useEffect(() => {
    if (
      loaded?.course.state === "active" &&
      contextCourse?.state === "active" &&
      activeCourse?.id !== loaded.course.id
    ) {
      selectCourse(loaded.course.id);
    }
  }, [activeCourse?.id, contextCourse, loaded, selectCourse]);

  if (loadState.requestKey !== requestKey || coursesLoading) {
    return (
      <main className="px-6 py-10 sm:px-10" aria-busy="true">
        <div className="mx-auto max-w-5xl text-sm text-[var(--muted-foreground)]">
          Loading Course Chat…
        </div>
      </main>
    );
  }

  if (error || !loaded || !contextCourse) {
    return (
      <main className="px-6 py-10 sm:px-10">
        <div className="mx-auto max-w-5xl">
          <Link
            href="/classes"
            className="inline-flex items-center gap-2 text-sm text-[var(--muted-foreground)] hover:text-[var(--foreground)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
          >
            <ArrowLeft size={15} /> Back to Classes
          </Link>
          <div
            role="alert"
            className="mt-8 rounded-2xl border border-red-300/60 bg-red-50/60 px-5 py-4 text-sm text-red-900 dark:border-red-900/60 dark:bg-red-950/20 dark:text-red-200"
          >
            {error || "Course Chat is unavailable."}
          </div>
        </div>
      </main>
    );
  }

  const { course, readiness } = loaded;
  const materialsPath = `/classes/${encodeURIComponent(course.id)}/materials`;
  const overviewPath = `/classes/${encodeURIComponent(course.id)}`;
  const presentation = courseChatReadinessPresentation(readiness);

  if (course.state !== "active" || !presentation.allowChat) {
    return (
      <main className="px-6 py-10 sm:px-10">
        <div className="mx-auto max-w-3xl">
          <Link
            href={overviewPath}
            className="inline-flex items-center gap-2 text-sm text-[var(--muted-foreground)] hover:text-[var(--foreground)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
          >
            <ArrowLeft size={15} /> Back to Course
          </Link>
          <section className="mt-8 rounded-2xl border border-[var(--border)] bg-[var(--card)] p-6">
            <div className="flex items-start gap-3">
              <MessageSquare className="mt-0.5 h-5 w-5 text-[var(--muted-foreground)]" />
              <div>
                <p className="text-sm text-[var(--muted-foreground)]">
                  {course.title} · {academicTermLabel(course.term)}
                </p>
                <h1 className="mt-2 text-xl font-semibold text-[var(--foreground)]">
                  {course.state === "active"
                    ? presentation.title
                    : "This archived Course is read-only."}
                </h1>
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
    <main className="flex h-full min-h-0 flex-col" data-testid="course-chat-route">
      <header className="shrink-0 border-b border-[var(--border)] bg-[var(--background)] px-6 py-3">
        <div className="mx-auto flex w-full max-w-[960px] flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <Link
              href={overviewPath}
              className="inline-flex items-center gap-1.5 text-xs text-[var(--muted-foreground)] hover:text-[var(--foreground)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
            >
              <ArrowLeft size={14} /> Back to Course
            </Link>
            <div className="mt-1 flex min-w-0 flex-wrap items-baseline gap-x-2">
              <h1 className="truncate text-lg font-semibold text-[var(--foreground)]">
                {course.title}
              </h1>
              <span className="text-sm text-[var(--muted-foreground)]">
                {academicTermLabel(course.term)}
              </span>
            </div>
          </div>
          {readiness.state === "partial" ? (
            <Link
              href={materialsPath}
              className="rounded-full border border-[var(--border)] px-3 py-1.5 text-xs text-[var(--muted-foreground)] hover:text-[var(--foreground)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
            >
              {presentation.body}
            </Link>
          ) : null}
        </div>
      </header>
      <div className="min-h-0 flex-1">
        <UnifiedChatPage
          routeCourseId={course.id}
          routeSessionId={sessionId}
          courseRouteBase={courseChatPath(course.id)}
          courseReadiness={readiness}
          hideCourseBar
          disableCourseLearnerActions
        />
      </div>
    </main>
  );
}
