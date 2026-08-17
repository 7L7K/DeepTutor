"use client";

import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { useParams, usePathname } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useCourses } from "@/context/CourseContext";
import { getCourse, type Course } from "@/lib/course-api";
import {
  COURSE_NAVIGATION_DESTINATIONS,
  courseDestinationIsActive,
  courseDestinationPath,
  learnerCourseTermLabel,
} from "@/lib/course-chat";

interface CourseShellContextValue {
  course: Course;
  courseId: string;
}

const CourseShellContext = createContext<CourseShellContextValue | null>(null);

/** The resolved Course context shared by every Course learning surface. */
export function useCourseShell(): CourseShellContextValue | null {
  return useContext(CourseShellContext);
}

function CourseNavigation({ courseId }: { courseId: string }) {
  const pathname = usePathname();
  const activeLinkRef = useRef<HTMLAnchorElement | null>(null);
  const activeDestinationKey = COURSE_NAVIGATION_DESTINATIONS.find((destination) =>
    courseDestinationIsActive(pathname, courseId, destination.suffix),
  )?.key;

  const revealActiveDestination = () => {
    activeLinkRef.current?.scrollIntoView({
      block: "nearest",
      inline: "nearest",
    });
  };

  useEffect(() => {
    const frame = window.requestAnimationFrame(revealActiveDestination);
    return () => window.cancelAnimationFrame(frame);
  }, [activeDestinationKey, pathname]);

  return (
    <nav
      aria-label="Course navigation"
      data-testid="course-navigation"
      className="-mx-1 flex w-full min-w-0 max-w-full gap-1 overflow-x-auto overscroll-x-contain border-t border-[var(--border)]/70 pb-0 pt-2.5 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden sm:pt-3"
    >
      {COURSE_NAVIGATION_DESTINATIONS.map((destination) => {
        const active = courseDestinationIsActive(pathname, courseId, destination.suffix);
        return (
          <Link
            key={destination.key}
            href={courseDestinationPath(courseId, destination.suffix)}
            aria-current={active ? "page" : undefined}
            data-testid={`course-nav-${destination.key}`}
            ref={active ? activeLinkRef : undefined}
            onFocus={revealActiveDestination}
            className={`shrink-0 whitespace-nowrap rounded-md px-2.5 py-1.5 text-sm transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] sm:px-3 sm:py-1.5 ${
              active
                ? "bg-[var(--foreground)] font-medium text-[var(--background)]"
                : "text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
            }`}
          >
            {destination.label}
          </Link>
        );
      })}
    </nav>
  );
}

export default function CourseShell({
  children,
}: {
  children: React.ReactNode;
}) {
  const params = useParams<{ courseId: string }>();
  const courseId = params.courseId;
  const { courses, selectCourse } = useCourses();
  const [course, setCourse] = useState<Course | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadCourse = useCallback(() => {
    let cancelled = false;
    // The route parameter can change without remounting the workspace layout.
    // Clear the previous Course immediately so a direct-link transition never
    // briefly presents the wrong Course context.
    setLoading(true);
    setError(null);
    setCourse(null);
    void getCourse(courseId)
      .then((loaded) => {
        if (!cancelled) setCourse(loaded);
      })
      .catch((cause: unknown) => {
        if (!cancelled) {
          setCourse(null);
          setError(cause instanceof Error ? cause.message : "Course not found");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [courseId]);

  useEffect(() => {
    // The initial owner-scoped read intentionally seeds local route state.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadCourse();
  }, [loadCourse]);

  useEffect(() => {
    // A browser Back may restore the Course route from bfcache before the
    // client component's original fetch has completed. Re-run the same
    // owner-scoped read when the route is restored instead of leaving the
    // shell on its initial loading state.
    const onPopState = () => loadCourse();
    const onPageShow = (event: PageTransitionEvent) => {
      if (event.persisted) loadCourse();
    };
    window.addEventListener("popstate", onPopState);
    window.addEventListener("pageshow", onPageShow);
    return () => {
      window.removeEventListener("popstate", onPopState);
      window.removeEventListener("pageshow", onPageShow);
    };
  }, [loadCourse]);

  const listedCourse = course
    ? courses.find((item) => item.id === course.id) ?? null
    : null;

  useEffect(() => {
    if (listedCourse) selectCourse(listedCourse.id);
  }, [listedCourse, selectCourse]);

  const contextValue = useMemo(
    () => (course ? { course, courseId: course.id } : null),
    [course],
  );
  const termLabel = learnerCourseTermLabel(course?.term);

  // The direct Course read is the authorization boundary for a deep link.
  // The owner-scoped Course list is shared navigation state and may briefly
  // rehydrate after browser Back; it must not hold an already-authorized
  // Course route on an infinite loading screen.
  if (loading) {
    return (
      <main className="px-6 py-10 sm:px-10">
        <div role="status" className="mx-auto max-w-5xl text-sm text-[var(--muted-foreground)]">
          Loading Course…
        </div>
      </main>
    );
  }

  if (error || !course || !contextValue) {
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
            {error || "Course not found or not available to this account."}
          </div>
        </div>
      </main>
    );
  }

  return (
    <CourseShellContext.Provider value={contextValue}>
      <div className="flex h-full min-h-0 min-w-0 flex-col overflow-x-hidden">
        <header className="shrink-0 overflow-x-hidden border-b border-[var(--border)] bg-[var(--background)] px-5 py-4 sm:px-8 sm:py-5">
          <div className="mx-auto w-full max-w-6xl">
            <div className="flex min-w-0 items-center justify-between gap-4">
              <Link
                href="/classes"
                className="inline-flex shrink-0 items-center gap-2 text-sm text-[var(--muted-foreground)] hover:text-[var(--foreground)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
              >
                <ArrowLeft size={15} /> Back to Classes
              </Link>
              {course.state === "archived" ? (
                <span className="shrink-0 rounded-full border border-[var(--border)] px-2.5 py-1 text-xs text-[var(--muted-foreground)]">
                  Read-only archived Course
                </span>
              ) : (
                <span className="inline-flex shrink-0 items-center gap-2 text-xs text-[var(--muted-foreground)]">
                  <span className="h-2 w-2 rounded-full bg-emerald-500" aria-hidden="true" />
                  Active course
                </span>
              )}
            </div>
            <div className="mt-4 flex min-w-0 items-end gap-3">
              <div className="min-w-0">
                <p className="text-[11px] font-medium uppercase tracking-[0.14em] text-[var(--muted-foreground)]">
                  Course
                </p>
                <h1 className="mt-1 truncate text-2xl font-semibold tracking-tight text-[var(--foreground)] sm:text-3xl">
                  {course.title}
                </h1>
              </div>
              {termLabel ? (
                <span className="shrink-0 pb-1 text-sm text-[var(--muted-foreground)]">
                  {termLabel}
                </span>
              ) : null}
            </div>
            <CourseNavigation courseId={course.id} />
          </div>
        </header>
        <div className="min-h-0 min-w-0 flex-1">{children}</div>
      </div>
    </CourseShellContext.Provider>
  );
}
