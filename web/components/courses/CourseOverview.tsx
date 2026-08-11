"use client";

import Link from "next/link";
import { BookOpen, ClipboardCheck, MessageSquare, RotateCcw } from "lucide-react";
import { useCourses } from "@/context/CourseContext";
import { courseChatPath } from "@/lib/course-chat";
import { useCourseShell } from "@/components/courses/CourseShell";

export default function CourseOverview() {
  const courseShell = useCourseShell();
  const { selectCourse } = useCourses();

  if (!courseShell) return null;
  const { course } = courseShell;
  const disabled = course.state !== "active";
  const coursePath = `/classes/${encodeURIComponent(course.id)}`;

  return (
    <main className="min-h-full px-5 py-7 sm:px-8 sm:py-9">
      <div className="mx-auto w-full max-w-6xl">
        <header>
          <p className="text-sm font-medium text-[var(--muted-foreground)]">
            Your Course workspace
          </p>
          <h2 className="mt-2 text-2xl font-semibold tracking-tight text-[var(--foreground)] sm:text-3xl">
            Course Overview
          </h2>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-[var(--muted-foreground)]">
            Materials, Chat, Practice, and Review for {course.title}.
          </p>
        </header>

        {disabled ? (
          <div className="mt-7 flex items-start gap-3 rounded-xl border border-[var(--border)] bg-[var(--card)] px-4 py-3 text-sm text-[var(--muted-foreground)]">
            <RotateCcw size={16} className="mt-0.5 shrink-0" />
            Restore this Course from Classes before opening its learning tools.
          </div>
        ) : null}

        <section aria-labelledby="continue-learning-heading" className="mt-8">
          <div className="mb-4">
            <h3
              id="continue-learning-heading"
              className="text-sm font-semibold text-[var(--foreground)]"
            >
              Continue learning
            </h3>
            <p className="mt-1 text-sm text-[var(--muted-foreground)]">
              Choose a Course surface without leaving this Course context.
            </p>
          </div>
          <div className="grid gap-4 md:grid-cols-3">
            <DestinationCard
              icon={<BookOpen size={19} />}
              title="Materials"
              description="Attach and review Course sources."
              href={`${coursePath}/materials`}
              disabled={disabled}
            />
            <DestinationCard
              icon={<ClipboardCheck size={19} />}
              title="Practice"
              description="Take persistent Practice grounded in this Course."
              href={`${coursePath}/practice`}
              disabled={disabled}
            />
            <DestinationCard
              icon={<RotateCcw size={19} />}
              title="Review"
              description="Review approved cards from this Course."
              href={`${coursePath}/review`}
              disabled={disabled}
            />
          </div>
        </section>

        <section className="mt-6 grid gap-4 md:grid-cols-2">
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
                <h3 className="font-semibold text-[var(--foreground)]">Course Chat</h3>
                <p className="mt-1 text-sm leading-6 text-[var(--muted-foreground)]">
                  Ask questions grounded in this Course&apos;s ready materials.
                </p>
              </div>
            </div>
          </Link>
          <div className="rounded-2xl border border-dashed border-[var(--border)] px-5 py-5">
            <h3 className="font-semibold text-[var(--foreground)]">Progress and recommendations</h3>
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
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
  href: string;
  disabled: boolean;
}) {
  const className = `group flex min-h-[150px] flex-col justify-between rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5 text-left shadow-sm transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] ${
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
  if (disabled) {
    return (
      <div aria-disabled="true" className={className}>
        {body}
      </div>
    );
  }
  return (
    <Link href={href} className={className}>
      {body}
    </Link>
  );
}
