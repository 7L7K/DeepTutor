"use client";

import { useRef, useState } from "react";
import { Archive, FilePlus2, Plus, RotateCcw } from "lucide-react";
import { useCourses } from "@/context/CourseContext";
import { attachCourseSource } from "@/lib/course-api";
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
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [newTitle, setNewTitle] = useState("");
  const [restoreId, setRestoreId] = useState("");
  const active = courses.filter((course) => course.state === "active");
  const archived = courses.filter((course) => course.state === "archived");

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
    setBusy(true);
    try {
      await attachCourseSource(activeCourse.id, file);
      setStatus(`${file.name} is processing`);
    } catch (cause) {
      setStatus(cause instanceof Error ? cause.message : "Could not attach source");
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
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
          <button disabled={busy} onClick={() => fileRef.current?.click()} className="rounded-lg p-1.5 hover:bg-[var(--muted)]" title={t("Attach course source")}>
            <FilePlus2 size={15} />
          </button>
          <button disabled={busy} onClick={() => void archiveSelected()} className="rounded-lg p-1.5 hover:bg-[var(--muted)]" title={t("Archive course")}>
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
      {status || error ? <span className="truncate text-[var(--muted-foreground)]">{status || error}</span> : null}
    </div>
  );
}
