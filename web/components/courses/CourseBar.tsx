"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Archive, FilePlus2, Plus, RefreshCw, RotateCcw } from "lucide-react";
import { useCourses } from "@/context/CourseContext";
import {
  archiveCourseSource,
  attachCourseSource,
  listCourseSources,
  type CourseSource,
} from "@/lib/course-api";
import { useTranslation } from "react-i18next";

export function CourseBar({ onCourseChange }: { onCourseChange?: () => void }) {
  const { t } = useTranslation();
  const {
    courses,
    activeCourse,
    loading,
    error,
    createCourse,
    selectCourse,
    archiveCourse,
    restoreCourse,
  } = useCourses();
  const fileRef = useRef<HTMLInputElement | null>(null);
  const replacementSourceRef = useRef<CourseSource | null>(null);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [newTitle, setNewTitle] = useState("");
  const [restoreId, setRestoreId] = useState("");
  const [sources, setSources] = useState<CourseSource[]>([]);
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const active = courses.filter((course) => course.state === "active");
  const archived = courses.filter((course) => course.state === "archived");

  const refreshSources = useCallback(async () => {
    if (!activeCourse) {
      setSources([]);
      return;
    }
    try {
      setSources(await listCourseSources(activeCourse.id));
    } catch (cause) {
      setStatus(
        cause instanceof Error ? cause.message : "Could not load course sources",
      );
    }
  }, [activeCourse]);

  useEffect(() => {
    setSources([]);
    setSourcesOpen(false);
    void refreshSources();
  }, [refreshSources]);

  useEffect(() => {
    if (!activeCourse || !sources.some((source) => source.state === "processing")) {
      return;
    }
    const timer = window.setInterval(() => void refreshSources(), 2_000);
    return () => window.clearInterval(timer);
  }, [activeCourse, refreshSources, sources]);

  async function addCourse() {
    const title = newTitle.trim();
    if (!title) return;
    setBusy(true);
    try {
      await createCourse(title);
      setNewTitle("");
      setCreating(false);
      onCourseChange?.();
    } catch (cause) {
      setStatus(cause instanceof Error ? cause.message : "Could not create course");
    } finally {
      setBusy(false);
    }
  }

  async function attach(file: File | undefined) {
    if (!file || !activeCourse) return;
    const replacement = replacementSourceRef.current;
    setBusy(true);
    try {
      const source = await attachCourseSource(
        activeCourse.id,
        file,
        replacement?.id,
      );
      setSources((current) => [
        source,
        ...current.filter((item) => item.id !== source.id),
      ]);
      setSourcesOpen(true);
      setStatus(
        replacement
          ? `${file.name} is processing as a replacement for ${replacement.display_name}`
          : `${file.name} is processing`,
      );
    } catch (cause) {
      setStatus(cause instanceof Error ? cause.message : "Could not attach source");
    } finally {
      setBusy(false);
      replacementSourceRef.current = null;
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function archiveSource(source: CourseSource) {
    if (!activeCourse || source.state === "archived") return;
    setBusy(true);
    try {
      const archivedSource = await archiveCourseSource(activeCourse.id, source);
      setSources((current) =>
        current.map((item) =>
          item.id === archivedSource.id ? archivedSource : item,
        ),
      );
      setStatus(`${source.display_name} archived`);
    } catch (cause) {
      setStatus(cause instanceof Error ? cause.message : "Could not archive source");
    } finally {
      setBusy(false);
    }
  }

  async function archiveSelected() {
    if (!activeCourse) return;
    setBusy(true);
    try {
      await archiveCourse(activeCourse);
      onCourseChange?.();
    } catch (cause) {
      setStatus(cause instanceof Error ? cause.message : "Could not archive course");
    } finally {
      setBusy(false);
    }
  }

  async function restoreOne() {
    const selected = archived.find((course) => course.id === restoreId);
    if (!selected) return;
    setBusy(true);
    try {
      await restoreCourse(selected);
      setStatus(`${selected.title} restored`);
      setRestoreId("");
    } catch (cause) {
      setStatus(cause instanceof Error ? cause.message : "Could not restore course");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto flex w-full max-w-[960px] flex-wrap items-center gap-2 px-6 pt-2 text-xs">
      <span className="font-medium text-[var(--muted-foreground)]">{t("Course")}</span>
      <select
        value={activeCourse?.id || ""}
        disabled={loading || busy}
        onChange={(event) => {
          selectCourse(event.target.value || null);
          onCourseChange?.();
        }}
        className="max-w-[260px] rounded-lg border border-[var(--border)] bg-[var(--card)] px-2 py-1.5 text-[var(--foreground)]"
        aria-label={t("Active course")}
      >
        <option value="">{t("General chat (no course)")}</option>
        {active.map((course) => (
          <option key={course.id} value={course.id}>{course.title}</option>
        ))}
      </select>
      <button
        disabled={busy}
        onClick={() => setCreating((value) => !value)}
        className="rounded-lg p-1.5 hover:bg-[var(--muted)]"
        title={t("Create course")}
        aria-label={t("Create course")}
      >
        <Plus size={15} />
      </button>
      {creating ? (
        <form
          className="flex items-center gap-1"
          onSubmit={(event) => {
            event.preventDefault();
            void addCourse();
          }}
        >
          <input
            value={newTitle}
            onChange={(event) => setNewTitle(event.target.value)}
            disabled={busy}
            autoFocus
            aria-label={t("Course name")}
            placeholder={t("Course name")}
            className="w-44 rounded-lg border border-[var(--border)] bg-[var(--card)] px-2 py-1.5 text-[var(--foreground)]"
          />
          <button
            type="submit"
            disabled={busy || !newTitle.trim()}
            className="rounded-lg px-2 py-1.5 hover:bg-[var(--muted)] disabled:opacity-50"
          >
            {t("Create")}
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => {
              setCreating(false);
              setNewTitle("");
            }}
            className="rounded-lg px-2 py-1.5 hover:bg-[var(--muted)]"
          >
            {t("Cancel")}
          </button>
        </form>
      ) : null}
      {activeCourse ? (
        <>
          <input ref={fileRef} type="file" className="hidden" onChange={(event) => void attach(event.target.files?.[0])} />
          <button
            disabled={busy}
            onClick={() => {
              replacementSourceRef.current = null;
              fileRef.current?.click();
            }}
            className="rounded-lg p-1.5 hover:bg-[var(--muted)]"
            title={t("Attach course source")}
            aria-label={t("Attach course source")}
          >
            <FilePlus2 size={15} />
          </button>
          <button
            disabled={busy}
            onClick={() => setSourcesOpen((value) => !value)}
            className="rounded-lg px-2 py-1.5 hover:bg-[var(--muted)]"
            aria-expanded={sourcesOpen}
          >
            {t("Sources")} ({sources.length})
          </button>
          <button disabled={busy} onClick={() => void archiveSelected()} className="rounded-lg p-1.5 hover:bg-[var(--muted)]" title={t("Archive course")} aria-label={t("Archive course")}>
            <Archive size={15} />
          </button>
        </>
      ) : null}
      {archived.length ? (
        <>
          <select
            value={restoreId}
            disabled={busy}
            onChange={(event) => setRestoreId(event.target.value)}
            aria-label={t("Archived course")}
            className="max-w-[220px] rounded-lg border border-[var(--border)] bg-[var(--card)] px-2 py-1.5 text-[var(--foreground)]"
          >
            <option value="">{t("Select archived course")}</option>
            {archived.map((course) => (
              <option key={course.id} value={course.id}>{course.title}</option>
            ))}
          </select>
          <button
            disabled={busy || !restoreId}
            onClick={() => void restoreOne()}
            className="inline-flex items-center gap-1 rounded-lg px-2 py-1.5 hover:bg-[var(--muted)] disabled:opacity-50"
            title={t("Restore archived course")}
          >
            <RotateCcw size={14} /> {t("Restore")}
          </button>
        </>
      ) : null}
      {status || error ? <span role={error ? "alert" : "status"} className="truncate text-[var(--muted-foreground)]">{status || error}</span> : null}
      {activeCourse && sourcesOpen ? (
        <section className="basis-full rounded-lg border border-[var(--border)] bg-[var(--card)] p-3" aria-label={t("Course sources")}>
          <div className="mb-2 flex items-center justify-between gap-2">
            <div>
              <p className="font-medium text-[var(--foreground)]">{t("Course sources")}</p>
              <p className="text-[var(--muted-foreground)]">
                {t("Ready sources can be used by Course Chat and study tools.")}
              </p>
            </div>
            <button
              type="button"
              disabled={busy}
              onClick={() => void refreshSources()}
              className="inline-flex items-center gap-1 rounded-lg border border-[var(--border)] px-2 py-1.5 disabled:opacity-50"
            >
              <RefreshCw size={13} /> {t("Refresh")}
            </button>
          </div>
          {sources.length ? (
            <ul className="space-y-2">
              {sources.map((source) => (
                <li key={source.id} className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-[var(--border)] px-2 py-2">
                  <div className="min-w-0">
                    <p className="truncate font-medium text-[var(--foreground)]">{source.display_name}</p>
                    <p className="text-[var(--muted-foreground)]">
                      {source.state === "processing"
                        ? t("Processing")
                        : source.state === "ready"
                          ? t("Ready")
                          : source.state === "failed"
                            ? t("Failed — attach the file again to retry")
                            : t("Archived")}
                    </p>
                  </div>
                  {source.state !== "archived" ? (
                    <div className="flex gap-1">
                      {source.state === "failed" ? (
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => {
                            replacementSourceRef.current = source;
                            fileRef.current?.click();
                          }}
                          className="rounded-md border border-[var(--border)] px-2 py-1 disabled:opacity-50"
                        >
                          {t("Attach replacement")}
                        </button>
                      ) : null}
                      <button
                        type="button"
                        disabled={busy || source.state === "processing"}
                        onClick={() => void archiveSource(source)}
                        className="rounded-md border border-[var(--border)] px-2 py-1 disabled:opacity-50"
                      >
                        {t("Archive")}
                      </button>
                    </div>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-[var(--muted-foreground)]">
              {t("No Course sources yet. Attach a file to begin.")}
            </p>
          )}
        </section>
      ) : null}
    </div>
  );
}
