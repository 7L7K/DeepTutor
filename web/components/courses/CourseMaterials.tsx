"use client";

import { ChevronDown, ChevronUp, FilePlus2, RefreshCw } from "lucide-react";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { useCourseShell } from "@/components/courses/CourseShell";
import {
  archiveCourseSource,
  attachCourseSource,
  listCourseSources,
  type CourseSource,
} from "@/lib/course-api";

type MaterialState = CourseSource["state"];

export interface MaterialErrorState {
  load: string | null;
  action: string | null;
}

export type MaterialErrorEvent =
  | { type: "load-started" | "load-succeeded" }
  | { type: "load-failed"; message: string }
  | { type: "action-started" }
  | { type: "action-failed"; message: string };

export function reduceMaterialErrors(
  current: MaterialErrorState,
  event: MaterialErrorEvent,
): MaterialErrorState {
  switch (event.type) {
    case "load-started":
    case "load-succeeded":
      return { ...current, load: null };
    case "load-failed":
      return { ...current, load: event.message };
    case "action-started":
      return { ...current, action: null };
    case "action-failed":
      return { ...current, action: event.message };
  }
}

export function isCurrentMaterialRefresh(
  requestEpoch: number,
  latestEpoch: number,
): boolean {
  return requestEpoch === latestEpoch;
}

export async function runSerializedMaterialPollCycle(
  refresh: () => Promise<void>,
  rearm: () => void,
  isActive: () => boolean,
): Promise<void> {
  await refresh();
  if (isActive()) rearm();
}

function materialStateLabel(state: MaterialState): string {
  switch (state) {
    case "processing":
      return "Preparing";
    case "ready":
      return "Ready";
    case "failed":
      return "Could not process";
    case "archived":
      return "Archived";
  }
}

function materialKindLabel(source: CourseSource): string {
  const extension = source.display_name.split(".").pop()?.toLowerCase();
  if (extension === "pdf") return "PDF";
  if (["txt", "md", "markdown", "csv"].includes(extension ?? "")) return "Text";
  if (["doc", "docx"].includes(extension ?? "")) return "Document";
  return source.kind === "document" ? "Document" : "Material";
}

export default function CourseMaterials() {
  const params = useParams<{ courseId: string }>();
  const courseId = params.courseId;
  const courseShell = useCourseShell();
  const fileRef = useRef<HTMLInputElement | null>(null);
  const refreshEpochRef = useRef(0);
  const [sources, setSources] = useState<CourseSource[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [errors, setErrors] = useState<MaterialErrorState>({ load: null, action: null });
  const [status, setStatus] = useState<string | null>(null);
  const [replacementSourceId, setReplacementSourceId] = useState<string | null>(null);
  const [showArchived, setShowArchived] = useState(false);
  const hasProcessingSources = sources.some((source) => source.state === "processing");

  const refresh = useCallback(async ({ silent = false }: { silent?: boolean } = {}) => {
    if (!courseShell) return;
    const requestEpoch = ++refreshEpochRef.current;
    if (!silent) {
      setLoading(true);
      setErrors((current) => reduceMaterialErrors(current, { type: "load-started" }));
    }
    try {
      const loadedSources = await listCourseSources(courseId);
      if (!isCurrentMaterialRefresh(requestEpoch, refreshEpochRef.current)) return;
      setSources(loadedSources);
      setErrors((current) => reduceMaterialErrors(current, { type: "load-succeeded" }));
    } catch (cause) {
      if (!isCurrentMaterialRefresh(requestEpoch, refreshEpochRef.current)) return;
      setErrors((current) => reduceMaterialErrors(current, {
        type: "load-failed",
        message: cause instanceof Error ? cause.message : "Could not load Course materials",
      }));
    } finally {
      if (!silent && isCurrentMaterialRefresh(requestEpoch, refreshEpochRef.current)) {
        setLoading(false);
      }
    }
  }, [courseId, courseShell]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (busy || loading || !hasProcessingSources) return;
    let cancelled = false;
    let timer: number | null = null;

    const rearm = () => {
      if (cancelled) return;
      timer = window.setTimeout(() => {
        void runSerializedMaterialPollCycle(
          () => refresh({ silent: true }),
          rearm,
          () => !cancelled,
        );
      }, 2_000);
    };

    rearm();
    return () => {
      cancelled = true;
      if (timer !== null) window.clearTimeout(timer);
    };
  }, [busy, hasProcessingSources, loading, refresh]);

  async function attach(file: File | undefined) {
    const course = courseShell?.course;
    if (!file || !course || course.state !== "active") return;
    const supersedesSourceId = replacementSourceId;
    refreshEpochRef.current += 1;
    setLoading(false);
    setBusy(true);
    setStatus(null);
    setErrors((current) => reduceMaterialErrors(current, { type: "action-started" }));
    try {
      const source = await attachCourseSource(course.id, file, supersedesSourceId);
      refreshEpochRef.current += 1;
      setSources((current) => [source, ...current.filter((item) => item.id !== source.id)]);
      setReplacementSourceId(null);
      setStatus(`${file.name} is preparing`);
    } catch (cause) {
      setErrors((current) => reduceMaterialErrors(current, {
        type: "action-failed",
        message: cause instanceof Error ? cause.message : "Could not attach source",
      }));
    } finally {
      setBusy(false);
      setReplacementSourceId(null);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function archiveSource(source: CourseSource) {
    const course = courseShell?.course;
    if (!course || source.state === "archived") return;
    refreshEpochRef.current += 1;
    setLoading(false);
    setBusy(true);
    setStatus(null);
    setErrors((current) => reduceMaterialErrors(current, { type: "action-started" }));
    try {
      const updated = await archiveCourseSource(course.id, source);
      refreshEpochRef.current += 1;
      setSources((current) => current.map((item) => (item.id === updated.id ? updated : item)));
      setStatus(`${source.display_name} archived`);
    } catch (cause) {
      setErrors((current) => reduceMaterialErrors(current, {
        type: "action-failed",
        message: cause instanceof Error ? cause.message : "Could not archive source",
      }));
    } finally {
      setBusy(false);
    }
  }

  if (!courseShell) return null;
  const { course } = courseShell;
  const activeSources = sources.filter((source) => source.state !== "archived");
  const archivedSources = sources.filter((source) => source.state === "archived");
  const readySources = activeSources.filter((source) => source.state === "ready");
  const processingSources = activeSources.filter((source) => source.state === "processing");
  const failedSources = activeSources.filter((source) => source.state === "failed");
  const openFilePicker = (sourceId: string | null = null) => {
    setReplacementSourceId(sourceId);
    fileRef.current?.click();
  };
  const renderSource = (source: CourseSource) => (
    <li key={source.id} className="flex flex-wrap items-start justify-between gap-4 rounded-2xl border border-[var(--border)] bg-[var(--card)] px-5 py-4">
      <div className="min-w-0">
        <p className="truncate font-medium text-[var(--foreground)]">{source.display_name}</p>
        <p className="mt-1 text-sm text-[var(--muted-foreground)]">
          {materialKindLabel(source)} · {materialStateLabel(source.state)}
        </p>
        {source.state === "ready" ? (
          <p className="mt-2 text-xs font-medium text-[var(--muted-foreground)]">Available to Course Chat and Practice</p>
        ) : source.state === "processing" ? (
          <p className="mt-2 text-xs text-[var(--muted-foreground)]">Preparing material…</p>
        ) : source.state === "failed" ? (
          <p className="mt-2 text-xs text-[var(--muted-foreground)]">This material could not be processed.</p>
        ) : null}
      </div>
      <div className="flex shrink-0 flex-wrap gap-2">
        {source.state === "failed" ? (
          <button type="button" onClick={() => openFilePicker(source.id)} disabled={busy || course.state !== "active"} className="rounded-lg bg-[var(--foreground)] px-3 py-1.5 text-sm font-medium text-[var(--background)] transition hover:opacity-85 disabled:cursor-not-allowed disabled:opacity-50">Replace material</button>
        ) : null}
        {source.state !== "archived" ? (
          <button type="button" onClick={() => void archiveSource(source)} disabled={busy || source.state === "processing" || course.state !== "active"} className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-sm text-[var(--muted-foreground)] transition hover:bg-[var(--muted)] disabled:cursor-not-allowed disabled:opacity-50">Archive</button>
        ) : null}
      </div>
    </li>
  );

  return (
    <main className="min-h-full px-6 py-10 sm:px-10">
      <div className="mx-auto w-full max-w-5xl">
        <header className="flex flex-wrap items-end justify-between gap-5">
          <div>
            <h2 className="text-2xl font-semibold tracking-tight text-[var(--foreground)]">Materials</h2>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-[var(--muted-foreground)]">
              Sources attached here belong to {course.title}.
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
              onClick={() => openFilePicker()}
              disabled={busy || course.state !== "active"}
              className="inline-flex items-center gap-2 rounded-lg bg-[var(--foreground)] px-3 py-2 text-sm font-medium text-[var(--background)] transition hover:opacity-85 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <FilePlus2 size={15} /> Add material
            </button>
          </div>
        </header>

        {errors.action ? (
          <div role="alert" className="mt-6 rounded-xl border border-red-300/60 bg-red-50/60 px-4 py-3 text-sm text-red-900 dark:border-red-900/60 dark:bg-red-950/20 dark:text-red-200">
            {errors.action}
          </div>
        ) : null}
        {errors.load ? (
          <div role="alert" className="mt-6 rounded-xl border border-red-300/60 bg-red-50/60 px-4 py-3 text-sm text-red-900 dark:border-red-900/60 dark:bg-red-950/20 dark:text-red-200">
            <p>{errors.load}</p>
            <button type="button" onClick={() => void refresh()} disabled={loading || busy} className="mt-3 rounded-lg border border-current px-3 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-50">Retry loading materials</button>
          </div>
        ) : null}
        {status ? (
          <p role="status" className="mt-4 text-sm text-[var(--muted-foreground)]">
            {status}
          </p>
        ) : null}

        {loading ? (
          <div className="mt-10 text-sm text-[var(--muted-foreground)]">Loading Course materials…</div>
        ) : errors.load ? null : sources.length ? (
          <div className="mt-10 space-y-8">
            <div className="grid gap-3 sm:grid-cols-3">
              {[
                ["Ready", readySources.length],
                ["Preparing", processingSources.length],
                ["Needs attention", failedSources.length],
              ].map(([label, count]) => (
                <div key={label} className="rounded-xl border border-[var(--border)] bg-[var(--card)] px-4 py-3">
                  <p className="text-2xl font-semibold text-[var(--foreground)]">{count}</p>
                  <p className="text-sm text-[var(--muted-foreground)]">{label}</p>
                </div>
              ))}
            </div>
            {readySources.length ? <section><h2 className="mb-3 text-lg font-semibold">Ready</h2><ul className="space-y-3">{readySources.map(renderSource)}</ul></section> : null}
            {processingSources.length ? <section><h2 className="mb-3 text-lg font-semibold">Preparing</h2><ul className="space-y-3">{processingSources.map(renderSource)}</ul></section> : null}
            {failedSources.length ? <section><h2 className="mb-3 text-lg font-semibold">Needs attention</h2><ul className="space-y-3">{failedSources.map(renderSource)}</ul></section> : null}
            {archivedSources.length ? <section>
              <button type="button" aria-expanded={showArchived} onClick={() => setShowArchived((shown) => !shown)} className="flex w-full items-center justify-between border-t border-[var(--border)] pt-5 text-left text-lg font-semibold">
                <span>Archived ({archivedSources.length})</span>{showArchived ? <ChevronUp size={18} /> : <ChevronDown size={18} />}
              </button>
              {showArchived ? <ul className="mt-3 space-y-3">{archivedSources.map(renderSource)}</ul> : null}
            </section> : null}
          </div>
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
