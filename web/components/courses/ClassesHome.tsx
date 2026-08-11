"use client";

import Link from "next/link";
import { ArrowRight, BookOpen, Plus, RefreshCw } from "lucide-react";
import { useState } from "react";
import { useCourses } from "@/context/CourseContext";
import type { Course } from "@/lib/course-api";
import { learnerCourseTermLabel } from "@/lib/course-chat";

function CourseCard({
  course,
  onOpen,
}: {
  course: Course;
  onOpen: () => void;
}) {
  return (
    <Link
      href={`/classes/${encodeURIComponent(course.id)}`}
      onClick={onOpen}
      className="group flex min-h-[168px] flex-col justify-between rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5 shadow-sm transition hover:-translate-y-0.5 hover:border-[var(--foreground)]/25 hover:shadow-md focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
      data-testid={`course-card-${course.id}`}
    >
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-[11px] font-medium uppercase tracking-[0.14em] text-[var(--muted-foreground)]">
            Course
          </p>
          <h2 className="mt-2 text-lg font-semibold text-[var(--foreground)]">
            {course.title}
          </h2>
          {learnerCourseTermLabel(course.term) ? (
            <p className="mt-1 text-sm text-[var(--muted-foreground)]">
              {learnerCourseTermLabel(course.term)}
            </p>
          ) : null}
        </div>
        {course.state === "archived" ? (
          <span className="rounded-full border border-[var(--border)] px-2 py-1 text-[11px] text-[var(--muted-foreground)]">
            Archived
          </span>
        ) : null}
      </div>
      <span className="mt-6 inline-flex items-center gap-1.5 text-sm font-medium text-[var(--foreground)]">
        {course.state === "active" ? "Continue" : "Open course"}
        <ArrowRight
          size={15}
          className="transition-transform group-hover:translate-x-0.5"
        />
      </span>
    </Link>
  );
}

export default function ClassesHome() {
  const { courses, loading, error, refresh, createCourse, selectCourse } =
    useCourses();
  const [newTitle, setNewTitle] = useState("");
  const [creating, setCreating] = useState(false);
  const [status, setStatus] = useState<string | null>(null);

  const academicCourses = courses.filter(
    (course) => course.workspace_kind === "academic_course",
  );
  const activeCourses = academicCourses.filter(
    (course) => course.state === "active",
  );
  const archivedCourses = academicCourses.filter(
    (course) => course.state === "archived",
  );

  async function submitCourse(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const title = newTitle.trim();
    if (!title) return;
    setCreating(true);
    setStatus(null);
    try {
      await createCourse(title);
      setNewTitle("");
      setStatus("Course created");
    } catch (cause) {
      setStatus(cause instanceof Error ? cause.message : "Could not create Course");
    } finally {
      setCreating(false);
    }
  }

  return (
    <main className="min-h-full px-6 py-10 sm:px-10">
      <div className="mx-auto w-full max-w-5xl">
        <header className="flex flex-wrap items-end justify-between gap-5">
          <div>
            <p className="text-sm font-medium text-[var(--muted-foreground)]">
              TEEECHR
            </p>
            <h1 className="mt-2 text-3xl font-semibold tracking-tight text-[var(--foreground)]">
              Classes
            </h1>
            <p className="mt-2 max-w-xl text-sm leading-6 text-[var(--muted-foreground)]">
              Your private academic Courses, with one stable place to open each
              Course.
            </p>
          </div>
          <button
            type="button"
            onClick={() => void refresh()}
            disabled={loading}
            className="inline-flex items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--card)] px-3 py-2 text-sm font-medium text-[var(--foreground)] transition hover:bg-[var(--muted)] disabled:cursor-not-allowed disabled:opacity-50"
          >
            <RefreshCw size={15} className={loading ? "animate-spin" : ""} />
            Refresh
          </button>
        </header>

        {error ? (
          <div
            role="alert"
            className="mt-6 rounded-xl border border-red-300/60 bg-red-50/60 px-4 py-3 text-sm text-red-900 dark:border-red-900/60 dark:bg-red-950/20 dark:text-red-200"
          >
            {error}
          </div>
        ) : null}
        {status ? (
          <p role="status" className="mt-4 text-sm text-[var(--muted-foreground)]">
            {status}
          </p>
        ) : null}

        {loading && !courses.length ? (
          <div className="mt-10 rounded-2xl border border-dashed border-[var(--border)] px-6 py-14 text-center text-sm text-[var(--muted-foreground)]">
            Loading your Courses…
          </div>
        ) : activeCourses.length ? (
          <section aria-labelledby="active-courses-heading" className="mt-10">
            <div className="mb-4 flex items-center justify-between gap-4">
              <h2
                id="active-courses-heading"
                className="text-sm font-semibold text-[var(--foreground)]"
              >
                Active Courses
              </h2>
              <span className="text-xs text-[var(--muted-foreground)]">
                {activeCourses.length} {activeCourses.length === 1 ? "Course" : "Courses"}
              </span>
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              {activeCourses.map((course) => (
                <CourseCard
                  key={course.id}
                  course={course}
                  onOpen={() => selectCourse(course.id)}
                />
              ))}
            </div>
          </section>
        ) : (
          <section className="mt-10 rounded-2xl border border-dashed border-[var(--border)] bg-[var(--card)]/40 px-6 py-14 text-center">
            <span className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--card)] text-[var(--muted-foreground)]">
              <BookOpen size={21} />
            </span>
            <h2 className="mt-4 text-lg font-semibold text-[var(--foreground)]">
              No Classes yet
            </h2>
            <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-[var(--muted-foreground)]">
              Create a Course to keep its materials, practice, and review work
              private to you.
            </p>
          </section>
        )}

        <section className="mt-8 rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5">
          <div className="flex items-start gap-4">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[var(--accent)] text-[var(--foreground)]">
              <Plus size={17} />
            </span>
            <div className="min-w-0 flex-1">
              <h2 className="font-semibold text-[var(--foreground)]">
                Add a Course
              </h2>
              <p className="mt-1 text-sm text-[var(--muted-foreground)]">
                Add a title now. You can set the academic term when it is known.
              </p>
              <form onSubmit={(event) => void submitCourse(event)} className="mt-4 flex flex-wrap gap-2">
                <label htmlFor="new-course-title" className="sr-only">
                  Course title
                </label>
                <input
                  id="new-course-title"
                  value={newTitle}
                  onChange={(event) => setNewTitle(event.target.value)}
                  placeholder="e.g. Biology"
                  maxLength={160}
                  disabled={creating}
                  className="min-w-[220px] flex-1 rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm text-[var(--foreground)] outline-none placeholder:text-[var(--muted-foreground)] focus:border-[var(--ring)]"
                />
                <button
                  type="submit"
                  disabled={creating || !newTitle.trim()}
                  className="rounded-lg bg-[var(--foreground)] px-4 py-2 text-sm font-medium text-[var(--background)] transition hover:opacity-85 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {creating ? "Creating…" : "Create Course"}
                </button>
              </form>
            </div>
          </div>
        </section>

        {archivedCourses.length ? (
          <section aria-labelledby="archived-courses-heading" className="mt-10">
            <h2
              id="archived-courses-heading"
              className="mb-4 text-sm font-semibold text-[var(--foreground)]"
            >
              Archived Courses
            </h2>
            <div className="grid gap-4 md:grid-cols-2">
              {archivedCourses.map((course) => (
                <CourseCard
                  key={course.id}
                  course={course}
                  onOpen={() => selectCourse(course.id)}
                />
              ))}
            </div>
          </section>
        ) : null}

        <p className="mt-10 text-sm text-[var(--muted-foreground)]">
          Need general learning instead?{" "}
          <Link
            href="/space/learning"
            className="font-medium text-[var(--foreground)] underline underline-offset-4 hover:no-underline"
          >
            Open General Study
          </Link>
          .
        </p>
      </div>
    </main>
  );
}
