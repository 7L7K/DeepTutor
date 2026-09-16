"use client";

import { useEffect, useRef, useState } from "react";
import { getCourseMaterials, type CourseSource, type CourseMaterialItem } from "@/lib/course-api";

const groups = ["Lectures", "Syllabus", "Assignments", "Documents", "Notes", "Course information", "Schedule"];
function timestamp(ms: number) {
  const seconds = Math.floor(ms / 1000);
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}
function savedDate(value: string | null) {
  if (!value) return "Date unavailable";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : date.toLocaleDateString(undefined, {year: "numeric", month: "short", day: "numeric", timeZone: "UTC"});
}
export default function BlueWayMaterials({courseId, source}: {courseId: string; source: CourseSource}) {
  const [items, setItems] = useState<CourseMaterialItem[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<CourseMaterialItem | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const selectedItem = items.find(item => item.id === selected);
  const transcriptOpen = selectedItem?.kind === "transcripts";
  const chatHref = `/classes/${encodeURIComponent(courseId)}/chat`;
  const questionButton = "inline-flex items-center justify-center rounded-lg bg-[var(--foreground)] px-4 py-2.5 text-sm font-semibold text-[var(--background)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4";
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!transcriptOpen || !dialog) return;
    const trigger = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const previousOverflow = document.body.style.overflow;
    dialog.showModal();
    document.body.style.overflow = "hidden";
    return () => { dialog.close(); document.body.style.overflow = previousOverflow; trigger?.focus({preventScroll: true}); };
  }, [transcriptOpen, selected]);
  useEffect(() => {
    let active = true;
    setItems([]); setError(null); setLoading(true); setSelected(null); setDetail(null);
    void getCourseMaterials(courseId, source).then(result => {
      if (!active) return;
      setItems(result.items);
      const query = new URLSearchParams(window.location.search);
      if (query.get("source") === source.id && query.get("revision") === String(source.revision) && query.get("hash") === source.content_sha256) {
        const item = query.get("item");
        if (result.items.some(value => value.id === item)) setSelected(item);
      }
    }).catch(cause => {if (active) setError(cause instanceof Error ? cause.message : "Could not load materials");})
      .finally(() => {if (active) setLoading(false);});
    return () => {active = false;};
  }, [courseId, source.id, source.revision, source.content_sha256]);
  useEffect(() => {
    let active = true;
    setDetail(null);
    if (selected) {
      setError(null);
      void getCourseMaterials(courseId, source, selected).then(result => {if (active) setDetail(result.items[0]);})
        .catch(cause => {if (active) setError(cause instanceof Error ? cause.message : "Could not open material");});
    }
    return () => {active = false;};
  }, [courseId, source.id, source.revision, source.content_sha256, selected]);
  useEffect(() => {
    if (!detail) return;
    const query = new URLSearchParams(window.location.search);
    if (query.get("item") !== detail.id || query.get("source") !== source.id) return;
    const segment = query.get("segment") || "0";
    const target = document.getElementById(`segment-${detail.id}-${segment}`) || document.getElementById(`material-${detail.id}`);
    target?.scrollIntoView({block: "center"});
  }, [detail, source.id]);
  return <div className="mt-4 w-full border-t border-[var(--border)] pt-4">
    <a href={chatHref} className={`${questionButton} mb-4`}>Ask a question in this class</a>
    <p className="text-sm text-[var(--muted-foreground)]">Read the imported content used by Course Chat and Practice. Syllabus entries are extracted details and may not include the whole syllabus.</p>
    {error && <p role="alert" className="mt-3 text-sm text-red-500">{error}</p>}
    {loading ? <p role="status" className="mt-3 text-sm">Loading materials…</p> : groups.map(group => {
      const entries = items.filter(item => item.group === group);
      if (!entries.length) return null;
      return <section key={group} className="mt-5">
        <h3 className="font-medium">{group} <span className="text-[var(--muted-foreground)]">({entries.length})</span></h3>
        <ul className="mt-2 space-y-2">{entries.map(item => <li key={item.id} id={`material-${item.id}`} className="rounded-xl border border-[var(--border)] p-3">
          <button type="button" aria-expanded={item.kind === "transcripts" ? undefined : selected === item.id} aria-haspopup={item.kind === "transcripts" ? "dialog" : undefined} aria-controls={item.kind === "transcripts" ? `transcript-dialog-${source.id}` : `content-${item.id}`} onClick={() => setSelected(selected === item.id ? null : item.id)} className="w-full text-left text-sm font-medium underline underline-offset-4">
            {item.title}{item.kind === "transcripts" || item.date ? ` · ${savedDate(item.date)}` : ""}
          </button>
          {selected === item.id && item.kind !== "transcripts" && <div id={`content-${item.id}`} className="mt-4 space-y-3 text-sm">
            {detail?.id !== item.id ? !error && <p role="status">Opening material…</p> : <>
              {detail.notice && <p className="text-[var(--muted-foreground)]">{detail.notice}</p>}
              {detail.fields?.map((field, index) => <div key={index}><p className="font-medium">{field.label}</p><p className="whitespace-pre-wrap break-words">{field.text}</p></div>)}
              <a href={chatHref} className={questionButton}>Ask a question in this class</a>
            </>}
          </div>}
        </li>)}</ul>
      </section>;
    })}
    {transcriptOpen && <dialog ref={dialogRef} id={`transcript-dialog-${source.id}`} aria-labelledby={`transcript-title-${source.id}`}
      onCancel={() => setSelected(null)}
      onClick={event => { if (event.target === event.currentTarget) setSelected(null); }}
      className="m-auto w-[calc(100%-2rem)] max-w-3xl max-h-[85dvh] overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--background)] p-0 text-[var(--foreground)] shadow-2xl backdrop:bg-black/60">
      <div className="flex max-h-[85dvh] flex-col">
        <header className="flex shrink-0 items-start justify-between gap-4 border-b border-[var(--border)] p-5">
          <div><h2 id={`transcript-title-${source.id}`} className="text-lg font-semibold">{selectedItem.title}</h2><p className="mt-1 text-sm text-[var(--muted-foreground)]">Transcript · {savedDate(selectedItem.date)}</p></div>
          <button type="button" autoFocus onClick={() => setSelected(null)} className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm font-medium">Close</button>
        </header>
        <div className="min-h-0 overflow-y-auto overscroll-contain p-5 text-sm" tabIndex={0} aria-label="Transcript text">
          {error ? <p role="alert">{error}</p> : detail?.id !== selected ? <p role="status">Opening transcript…</p> : <div className="space-y-4">
            {detail.segments?.map((segment, index) => <div key={index} id={`segment-${detail.id}-${index}`} className="flex items-start gap-4"><span className="shrink-0 font-mono text-xs text-[var(--muted-foreground)]">{timestamp(segment.start_ms)}</span><p className="whitespace-pre-wrap break-words leading-relaxed">{segment.text}</p></div>)}
          </div>}
        </div>
        <footer className="shrink-0 border-t border-[var(--border)] p-4"><a href={chatHref} className={questionButton}>Ask a question in this class</a></footer>
      </div>
    </dialog>}
    {!loading && !error && !items.length && <p className="mt-3 text-sm">No readable entries in this import.</p>}
  </div>;
}
