"use client";

import Link from "next/link";
import { ArrowRight, BookOpen, Plus, RefreshCw, X } from "lucide-react";
import { useEffect, useState } from "react";
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
            Academic class
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
      </div>
      <div className="mt-6 flex items-end justify-between gap-4">
        <span className="text-xs text-[var(--muted-foreground)]">
          {course.state === "active" ? "Active" : "Archived"}
        </span>
        <span className="inline-flex items-center gap-1.5 text-sm font-medium text-[var(--foreground)]">
          Open class
          <ArrowRight
            size={15}
            className="transition-transform group-hover:translate-x-0.5"
          />
        </span>
      </div>
    </Link>
  );
}

function AddClassModal({
  title,
  onTitleChange,
  onClose,
  onSubmit,
  creating,
}: {
  title: string;
  onTitleChange: (title: string) => void;
  onClose: () => void;
  onSubmit: (event: React.FormEvent<HTMLFormElement>) => void;
  creating: boolean;
}) {
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !creating) onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [creating, onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/30 p-4 sm:items-center"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !creating) onClose();
      }}
    >
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="add-class-heading"
        className="w-full max-w-md rounded-2xl border border-[var(--border)] bg-[var(--card)] p-6 shadow-xl"
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-sm font-medium text-[var(--muted-foreground)]">
              Classes
            </p>
            <h2
              id="add-class-heading"
              className="mt-1 text-xl font-semibold text-[var(--foreground)]"
            >
              Add class
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={creating}
            aria-label="Close"
            className="rounded-lg p-1.5 text-[var(--muted-foreground)] hover:bg-[var(--muted)] disabled:opacity-50"
          >
            <X size={18} />
          </button>
        </div>
        <p className="mt-3 text-sm leading-6 text-[var(--muted-foreground)]">
          Add a class by title. You can organize its materials, Practice, Review,
          and Course Chat in one place.
        </p>
        <form onSubmit={onSubmit} className="mt-5 space-y-4">
          <label htmlFor="new-class-title" className="block text-sm font-medium text-[var(--foreground)]">
            Class title
          </label>
          <input
            id="new-class-title"
            value={title}
            onChange={(event) => onTitleChange(event.target.value)}
            placeholder="e.g. Biology"
            maxLength={160}
            disabled={creating}
            autoFocus
            className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2.5 text-sm text-[var(--foreground)] outline-none placeholder:text-[var(--muted-foreground)] focus:border-[var(--ring)]"
          />
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              disabled={creating}
              className="rounded-lg border border-[var(--border)] px-4 py-2 text-sm font-medium text-[var(--foreground)] hover:bg-[var(--muted)] disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={creating || !title.trim()}
              className="rounded-lg bg-[var(--foreground)] px-4 py-2 text-sm font-medium text-[var(--background)] transition hover:opacity-85 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {creating ? "Adding…" : "Add class"}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}

export default function ClassesHome() {
  const { courses, loading, error, refresh, createCourse, selectCourse } =
    useCourses();
  const [newTitle, setNewTitle] = useState("");
  const [creating, setCreating] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
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
      setCreateOpen(false);
      setStatus("Class added");
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
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => {
                setStatus(null);
                setCreateOpen(true);
              }}
              className="inline-flex items-center gap-2 rounded-lg bg-[var(--foreground)] px-3 py-2 text-sm font-medium text-[var(--background)] transition hover:opacity-85"
            >
              <Plus size={15} />
              Add class
            </button>
            <button
              type="button"
              onClick={() => void refresh()}
              disabled={loading}
              aria-label="Refresh classes"
              className="rounded-lg border border-[var(--border)] bg-[var(--card)] p-2 text-[var(--foreground)] transition hover:bg-[var(--muted)] disabled:cursor-not-allowed disabled:opacity-50"
            >
              <RefreshCw size={15} className={loading ? "animate-spin" : ""} />
            </button>
          </div>
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
            <div className="mb-4">
              <h2
                id="active-courses-heading"
                className="text-sm font-semibold text-[var(--foreground)]"
              >
                Your classes
              </h2>
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
        ) : archivedCourses.length ? null : (
          <section className="mt-10 rounded-2xl border border-dashed border-[var(--border)] bg-[var(--card)]/40 px-6 py-14 text-center">
            <span className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl border border-[var(--border)] bg-[var(--card)] text-[var(--muted-foreground)]">
              <BookOpen size={21} />
            </span>
            <h2 className="mt-4 text-lg font-semibold text-[var(--foreground)]">
              No classes yet
            </h2>
            <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-[var(--muted-foreground)]">
              Add your first class to organize materials, Practice, Review, and
              Course Chat in one place.
            </p>
            <button
              type="button"
              onClick={() => setCreateOpen(true)}
              className="mt-5 inline-flex items-center gap-2 rounded-lg bg-[var(--foreground)] px-4 py-2 text-sm font-medium text-[var(--background)] hover:opacity-85"
            >
              <Plus size={15} />
              Add class
            </button>
            <p className="mt-5 text-sm text-[var(--muted-foreground)]">
              Study without a class?{" "}
              <Link
                href="/space/learning"
                className="font-medium text-[var(--foreground)] underline underline-offset-4 hover:no-underline"
              >
                Open General Study
              </Link>
            </p>
          </section>
        )}

        {archivedCourses.length ? (
          <section aria-labelledby="archived-courses-heading" className="mt-10">
            <h2
              id="archived-courses-heading"
              className="mb-4 text-sm font-semibold text-[var(--foreground)]"
            >
              Archived classes
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
      {createOpen ? (
        <AddClassModal
          title={newTitle}
          onTitleChange={setNewTitle}
          onClose={() => {
            if (!creating) {
              setCreateOpen(false);
              setNewTitle("");
            }
          }}
          onSubmit={(event) => void submitCourse(event)}
          creating={creating}
        />
      ) : null}
    </main>
  );
}
