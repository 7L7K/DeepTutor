"use client";

import { useEffect, useState } from "react";
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
    <p className="text-sm text-[var(--muted-foreground)]">Read the imported content used by Course Chat and Practice. Syllabus entries are extracted details and may not include the whole syllabus.</p>
    {error && <p role="alert" className="mt-3 text-sm text-red-500">{error}</p>}
    {loading ? <p role="status" className="mt-3 text-sm">Loading materials…</p> : groups.map(group => {
      const entries = items.filter(item => item.group === group);
      if (!entries.length) return null;
      return <section key={group} className="mt-5">
        <h3 className="font-medium">{group} <span className="text-[var(--muted-foreground)]">({entries.length})</span></h3>
        <ul className="mt-2 space-y-2">{entries.map(item => <li key={item.id} id={`material-${item.id}`} className="rounded-xl border border-[var(--border)] p-3">
          <button type="button" aria-expanded={selected === item.id} aria-controls={`content-${item.id}`} onClick={() => setSelected(selected === item.id ? null : item.id)} className="w-full text-left text-sm font-medium underline underline-offset-4">
            {item.title}{item.kind === "transcripts" || item.date ? ` · ${savedDate(item.date)}` : ""}
          </button>
          {selected === item.id && <div id={`content-${item.id}`} className="mt-4 space-y-3 text-sm">
            {detail?.id !== item.id ? !error && <p role="status">Opening material…</p> : <>
              {detail.notice && <p className="text-[var(--muted-foreground)]">{detail.notice}</p>}
              {detail.fields?.map((field, index) => <div key={index}><p className="font-medium">{field.label}</p><p className="whitespace-pre-wrap break-words">{field.text}</p></div>)}
              {detail.segments?.map((segment, index) => <div key={index} id={`segment-${item.id}-${index}`} className="flex items-start gap-3"><span className="shrink-0 font-mono text-xs text-[var(--muted-foreground)]">{timestamp(segment.start_ms)}</span><p className="whitespace-pre-wrap break-words">{segment.text}</p></div>)}
              <a href={`/classes/${encodeURIComponent(courseId)}/chat`} className="inline-block underline underline-offset-4">Ask a question in this class</a>
            </>}
          </div>}
        </li>)}</ul>
      </section>;
    })}
    {!loading && !error && !items.length && <p className="mt-3 text-sm">No readable entries in this import.</p>}
  </div>;
}
