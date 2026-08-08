"use client";

import Link from "next/link";
import { ArrowLeft, FilePlus2, RefreshCw } from "lucide-react";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { useCourses } from "@/context/CourseContext";
import {
  archiveCourseSource,
  attachCourseSource,
  getCourse,
  listCourseSources,
  type Course,
  type CourseSource,
} from "@/lib/course-api";

export default function CourseMaterials() {
  const params = useParams<{ courseId: string }>();
  const courseId = params.courseId;
  const { selectCourse } = useCourses();
  const fileRef = useRef<HTMLInputElement | null>(null);
  const [course, setCourse] = useState<Course | null>(null);
  const [sources, setSources] = useState<CourseSource[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [loadedCourse, loadedSources] = await Promise.all([
        getCourse(courseId),
        listCourseSources(courseId),
      ]);
      setCourse(loadedCourse);
      setSources(loadedSources);
      selectCourse(loadedCourse.id);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not load Course materials");
    } finally {
      setLoading(false);
    }
  }, [courseId, selectCourse]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!sources.some((source) => source.state === "processing")) return;
    const timer = window.setInterval(() => void refresh(), 2_000);
    return () => window.clearInterval(timer);
  }, [refresh, sources]);

  async function attach(file: File | undefined) {
    if (!file || !course || course.state !== "active") return;
    setBusy(true);
    setStatus(null);
    try {
      const source = await attachCourseSource(course.id, file);
      setSources((current) => [source, ...current.filter((item) => item.id !== source.id)]);
      setStatus(`${file.name} is processing`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not attach source");
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function archiveSource(source: CourseSource) {
    if (!course || source.state === "archived") return;
    setBusy(true);
    setStatus(null);
    try {
      const updated = await archiveCourseSource(course.id, source);
      setSources((current) => current.map((item) => (item.id === updated.id ? updated : item)));
      setStatus(`${source.display_name} archived`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not archive source");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="min-h-full px-6 py-10 sm:px-10">
      <div className="mx-auto w-full max-w-5xl">
        <Link
          href={`/classes/${encodeURIComponent(courseId)}`}
          className="inline-flex items-center gap-2 text-sm text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
        >
          <ArrowLeft size={15} /> Back to Course Hub
        </Link>

        <header className="mt-8 flex flex-wrap items-end justify-between gap-5">
          <div>
            <p className="text-sm font-medium text-[var(--muted-foreground)]">Course materials</p>
            <h1 className="mt-2 text-3xl font-semibold tracking-tight text-[var(--foreground)]">
              {course?.title || "Materials"}
            </h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-[var(--muted-foreground)]">
              Sources attached here belong only to this Course and this account.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => void refresh()}
              disabled={loading || busy}
              className="inline-flex items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--card)] px-3 py-2 text-sm font-medium text-[var(--foreground)] transition hover:bg-[var(--muted)] disabled:cursor-not-allowed disabled:opacity-50"
            >
              <RefreshCw size={15} className={loading ? "animate-spin" : ""} />
              Refresh
            </button>
            <input
              ref={fileRef}
              type="file"
              className="hidden"
              onChange={(event) => void attach(event.target.files?.[0])}
            />
            <button
              type="button"
              onClick={() => fileRef.current?.click()}
              disabled={busy || !course || course.state !== "active"}
              className="inline-flex items-center gap-2 rounded-lg bg-[var(--foreground)] px-3 py-2 text-sm font-medium text-[var(--background)] transition hover:opacity-85 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <FilePlus2 size={15} /> Attach source
            </button>
          </div>
        </header>

        {error ? (
          <div role="alert" className="mt-6 rounded-xl border border-red-300/60 bg-red-50/60 px-4 py-3 text-sm text-red-900 dark:border-red-900/60 dark:bg-red-950/20 dark:text-red-200">
            {error}
          </div>
        ) : null}
        {status ? (
          <p role="status" className="mt-4 text-sm text-[var(--muted-foreground)]">
            {status}
          </p>
        ) : null}

        {loading ? (
          <div className="mt-10 text-sm text-[var(--muted-foreground)]">Loading Course materials…</div>
        ) : sources.length ? (
          <ul className="mt-10 space-y-3">
            {sources.map((source) => (
              <li key={source.id} className="flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-[var(--border)] bg-[var(--card)] px-5 py-4">
                <div className="min-w-0">
                  <p className="truncate font-medium text-[var(--foreground)]">{source.display_name}</p>
                  <p className="mt-1 text-sm text-[var(--muted-foreground)]">
                    {source.state === "processing"
                      ? "Processing"
                      : source.state === "ready"
                        ? "Ready"
                        : source.state === "failed"
                          ? "Failed — attach the file again to retry"
                          : "Archived"}
                  </p>
                </div>
                {source.state !== "archived" ? (
                  <button
                    type="button"
                    onClick={() => void archiveSource(source)}
                    disabled={busy || source.state === "processing" || course?.state !== "active"}
                    className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-sm text-[var(--foreground)] transition hover:bg-[var(--muted)] disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    Archive
                  </button>
                ) : null}
              </li>
            ))}
          </ul>
        ) : (
          <div className="mt-10 rounded-2xl border border-dashed border-[var(--border)] px-6 py-14 text-center">
            <h2 className="text-lg font-semibold text-[var(--foreground)]">No materials attached</h2>
            <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-[var(--muted-foreground)]">
              Attach a Course source when you are ready. No readiness or generated learning state is inferred before that happens.
            </p>
          </div>
        )}
      </div>
    </main>
  );
}
