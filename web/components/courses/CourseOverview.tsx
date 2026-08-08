"use client";

import Link from "next/link";
import { ArrowLeft, BookOpen, ClipboardCheck, MessageSquare, RotateCcw } from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useCourses } from "@/context/CourseContext";
import { getCourse, type Course } from "@/lib/course-api";
import { academicTermLabel, courseChatPath } from "@/lib/course-chat";

export default function CourseOverview() {
  const params = useParams<{ courseId: string }>();
  const courseId = params.courseId;
  const router = useRouter();
  const { courses, loading: coursesLoading, selectCourse } = useCourses();
  const [course, setCourse] = useState<Course | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void getCourse(courseId)
      .then((loaded) => {
        if (!cancelled) setCourse(loaded);
      })
      .catch((cause: unknown) => {
        if (!cancelled) {
          setCourse(null);
          setError(cause instanceof Error ? cause.message : "Could not load Course");
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
    if (course) selectCourse(course.id);
  }, [course, selectCourse]);

  function openDestination(path: string) {
    if (!course || course.state !== "active") return;
    selectCourse(course.id);
    router.push(path);
  }

  if (loading || coursesLoading) {
    return (
      <main className="px-6 py-10 sm:px-10">
        <div className="mx-auto max-w-5xl text-sm text-[var(--muted-foreground)]">
          Loading Course Hub…
        </div>
      </main>
    );
  }

  if (error || !course) {
    return (
      <main className="px-6 py-10 sm:px-10">
        <div className="mx-auto max-w-5xl">
          <Link
            href="/classes"
            className="inline-flex items-center gap-2 text-sm text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
          >
            <ArrowLeft size={15} /> Back to Classes
          </Link>
          <div role="alert" className="mt-8 rounded-2xl border border-red-300/60 bg-red-50/60 px-5 py-4 text-sm text-red-900 dark:border-red-900/60 dark:bg-red-950/20 dark:text-red-200">
            {error || "Course not found or not available to this account."}
          </div>
        </div>
      </main>
    );
  }

  if (course.id !== courseId) {
    return (
      <main className="px-6 py-10 sm:px-10">
        <div className="mx-auto max-w-5xl text-sm text-[var(--muted-foreground)]">
          Loading Course Hub…
        </div>
      </main>
    );
  }

  const disabled = course.state !== "active";

  return (
    <main className="min-h-full px-6 py-10 sm:px-10">
      <div className="mx-auto w-full max-w-5xl">
        <Link
          href="/classes"
          className="inline-flex items-center gap-2 text-sm text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
        >
          <ArrowLeft size={15} /> Back to Classes
        </Link>

        <header className="mt-8 flex flex-wrap items-start justify-between gap-5">
          <div>
            <p className="text-sm font-medium text-[var(--muted-foreground)]">Course Hub</p>
            <h1 className="mt-2 text-3xl font-semibold tracking-tight text-[var(--foreground)]">
              {course.title}
            </h1>
            <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 text-sm text-[var(--muted-foreground)]">
              <span>Term: {academicTermLabel(course.term)}</span>
              <span>State: {course.state}</span>
            </div>
          </div>
          {disabled ? (
            <span className="rounded-full border border-[var(--border)] px-3 py-1.5 text-xs text-[var(--muted-foreground)]">
              Read-only archived Course
            </span>
          ) : null}
        </header>

        {disabled ? (
          <div className="mt-8 flex items-start gap-3 rounded-xl border border-[var(--border)] bg-[var(--card)] px-4 py-3 text-sm text-[var(--muted-foreground)]">
            <RotateCcw size={16} className="mt-0.5 shrink-0" />
            Restore this Course from Classes before opening its learning tools.
          </div>
        ) : null}

        <section aria-labelledby="course-destinations-heading" className="mt-10">
          <div className="mb-4">
            <h2 id="course-destinations-heading" className="text-sm font-semibold text-[var(--foreground)]">
              Course destinations
            </h2>
            <p className="mt-1 text-sm text-[var(--muted-foreground)]">
              Open a working surface for this Course. Selection stays private to your account.
            </p>
          </div>
          <div className="grid gap-4 md:grid-cols-3">
            <DestinationCard
              icon={<BookOpen size={19} />}
              title="Materials"
              description="Attach and review Course sources."
              href={`/classes/${encodeURIComponent(course.id)}/materials`}
              disabled={disabled}
              onOpen={() => openDestination(`/classes/${encodeURIComponent(course.id)}/materials`)}
            />
            <DestinationCard
              icon={<ClipboardCheck size={19} />}
              title="Practice"
              description="Take persistent Practice grounded in this Course."
              href={`/classes/${encodeURIComponent(course.id)}/practice`}
              disabled={disabled}
              onOpen={() => openDestination(`/classes/${encodeURIComponent(course.id)}/practice`)}
            />
            <DestinationCard
              icon={<RotateCcw size={19} />}
              title="Review"
              description="Review approved cards from this Course."
              href={`/classes/${encodeURIComponent(course.id)}/review`}
              disabled={disabled}
              onOpen={() => openDestination(`/classes/${encodeURIComponent(course.id)}/review`)}
            />
          </div>
        </section>

        <section className="mt-8 grid gap-4 md:grid-cols-2">
          <Link
            href={courseChatPath(course.id)}
            data-testid="course-chat-link"
            onClick={() => selectCourse(course.id)}
            aria-disabled={disabled}
            className={`rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5 transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] ${
              disabled
                ? "pointer-events-none opacity-50"
                : "hover:-translate-y-0.5 hover:border-[var(--foreground)]/25 hover:shadow-md"
            }`}
          >
            <div className="flex items-start gap-3">
              <MessageSquare size={18} className="mt-0.5 text-[var(--muted-foreground)]" />
              <div>
                <h2 className="font-semibold text-[var(--foreground)]">Course Chat</h2>
                <p className="mt-1 text-sm leading-6 text-[var(--muted-foreground)]">
                  Ask questions grounded in this Course&apos;s ready materials.
                </p>
              </div>
            </div>
          </Link>
          <div className="rounded-2xl border border-dashed border-[var(--border)] px-5 py-5">
            <h2 className="font-semibold text-[var(--foreground)]">Progress and recommendations</h2>
            <p className="mt-1 text-sm leading-6 text-[var(--muted-foreground)]">
              Not available in this slice. No progress or recommendation state is inferred here.
            </p>
          </div>
        </section>
      </div>
    </main>
  );
}

function DestinationCard({
  icon,
  title,
  description,
  href,
  disabled,
  onOpen,
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
  href?: string;
  disabled: boolean;
  onOpen: () => void;
}) {
  const className = `group flex min-h-[150px] flex-col justify-between rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5 text-left shadow-sm transition ${
    disabled
      ? "cursor-not-allowed opacity-50"
      : "hover:-translate-y-0.5 hover:border-[var(--foreground)]/25 hover:shadow-md"
  }`;
  const body = (
    <>
      <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-[var(--accent)] text-[var(--foreground)]">
        {icon}
      </span>
      <span>
        <span className="block font-semibold text-[var(--foreground)]">{title}</span>
        <span className="mt-1 block text-sm leading-5 text-[var(--muted-foreground)]">{description}</span>
      </span>
    </>
  );
  if (disabled || !href) {
    return (
      <button type="button" disabled={disabled} onClick={onOpen} className={className}>
        {body}
      </button>
    );
  }
  return (
    <Link href={href} onClick={onOpen} className={className}>
      {body}
    </Link>
  );
}
