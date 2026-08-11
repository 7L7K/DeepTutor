"use client";

import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Archive,
  CheckCircle2,
  DatabaseBackup,
  FileSearch,
  LockKeyhole,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";

import { listCourses, type Course } from "@/lib/course-api";
import {
  createHistoricalDryRun,
  listHistoricalSources,
  type HistoricalMigrationDryRun,
  type HistoricalSourceSummary,
  type LegacyOwnerSummary,
} from "@/lib/historical-migration-api";

const TABLE_LABELS: Record<string, string> = {
  sessions: "Conversations",
  messages: "Conversation messages",
  practice_attempts: "Practice attempts",
  practice_attempt_items: "Practice answers",
  flashcard_decks: "Flashcard decks",
  flashcard_cards: "Flashcards",
  flashcard_reviews: "Flashcard reviews",
  flashcard_session_reviews: "Study sessions",
};

function shortFingerprint(value: string) {
  return value ? `${value.slice(0, 8)}…${value.slice(-6)}` : "Unavailable";
}

function formatBytes(value: number) {
  if (value < 1024 * 1024) return `${Math.max(1, Math.round(value / 1024))} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function profileActivity(owner: LegacyOwnerSummary) {
  return owner.session_count + owner.practice_attempt_count + owner.flashcard_deck_count;
}

export default function HistoricalDataPage() {
  const [sources, setSources] = useState<HistoricalSourceSummary[]>([]);
  const [courses, setCourses] = useState<Course[]>([]);
  const [sourceId, setSourceId] = useState("");
  const [ownerDesignation, setOwnerDesignation] = useState("");
  const [practiceCourseId, setPracticeCourseId] = useState("");
  const [flashcardWorkspaceId, setFlashcardWorkspaceId] = useState("");
  const [report, setReport] = useState<HistoricalMigrationDryRun | null>(null);
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState("");

  async function load() {
    setLoading(true);
    setError("");
    try {
      const [nextSources, nextCourses] = await Promise.all([
        listHistoricalSources(),
        listCourses(),
      ]);
      setSources(nextSources);
      setCourses(nextCourses);
      const first = nextSources.find((item) => item.compatible) || nextSources[0];
      setSourceId((current) => current || first?.id || "");
      const activeAcademic = nextCourses.find(
        (item) => item.state === "active" && item.workspace_kind === "academic_course",
      );
      const activeWorkspace =
        nextCourses.find(
          (item) => item.state === "active" && item.workspace_kind === "general_study",
        ) || activeAcademic;
      setPracticeCourseId((current) => current || activeAcademic?.id || "");
      setFlashcardWorkspaceId((current) => current || activeWorkspace?.id || "");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not inspect historical data.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  const source = useMemo(
    () => sources.find((item) => item.id === sourceId) || null,
    [sourceId, sources],
  );
  const orderedOwners = useMemo(
    () => [...(source?.owners || [])].sort((a, b) => profileActivity(b) - profileActivity(a)),
    [source],
  );
  useEffect(() => {
    if (!orderedOwners.some((owner) => owner.designation === ownerDesignation)) {
      setOwnerDesignation(orderedOwners.length === 1 ? orderedOwners[0].designation : "");
    }
    setReport(null);
  }, [orderedOwners, ownerDesignation]);

  const academicCourses = courses.filter(
    (course) => course.state === "active" && course.workspace_kind === "academic_course",
  );
  const flashcardDestinations = courses.filter((course) => course.state === "active");

  async function runDryScan() {
    if (!source || !ownerDesignation) return;
    setScanning(true);
    setError("");
    setReport(null);
    try {
      setReport(
        await createHistoricalDryRun({
          sourceId: source.id,
          legacyOwnerDesignation: ownerDesignation,
          practiceCourseId: practiceCourseId || null,
          flashcardWorkspaceId: flashcardWorkspaceId || null,
        }),
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The safe scan did not finish.");
    } finally {
      setScanning(false);
    }
  }

  return (
    <div className="mx-auto max-w-5xl pb-16">
      <header className="mb-7">
        <div className="flex items-center gap-2 text-[13px] font-medium text-[var(--muted-foreground)]">
          <DatabaseBackup size={16} /> Historical learning data
        </div>
        <h1 className="mt-2 font-serif text-[28px] font-semibold tracking-tight">
          Review what can move safely
        </h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-[var(--muted-foreground)]">
          TEEECHR can inspect the preserved older learner database without changing it. Choose
          the historical profile that is yours and where eligible study material should
          eventually go. This page only creates a review report—nothing is imported.
        </p>
      </header>

      <section className="mb-6 grid gap-3 sm:grid-cols-3">
        <Boundary icon={LockKeyhole} title="Read-only source" body="The older database is opened in query-only mode." />
        <Boundary icon={ShieldCheck} title="No ownership guesses" body="Titles and knowledge-base names never choose an owner." />
        <Boundary icon={Archive} title="No live mastery changes" body="Old scores remain archival evidence during this phase." />
      </section>

      <section className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5 sm:p-6">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-lg font-semibold">1. Find the preserved data</h2>
            <p className="mt-1 text-sm text-[var(--muted-foreground)]">
              The browser cannot enter a file path. Only the server-approved historical source is visible.
            </p>
          </div>
          <button
            type="button"
            onClick={() => void load()}
            disabled={loading}
            className="inline-flex items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-2 text-sm disabled:opacity-50"
          >
            <RefreshCw size={14} className={loading ? "animate-spin" : ""} /> Refresh
          </button>
        </div>

        {loading ? (
          <p role="status" className="mt-5 text-sm text-[var(--muted-foreground)]">Checking the preserved database…</p>
        ) : sources.length === 0 ? (
          <div className="mt-5 rounded-xl border border-dashed border-[var(--border)] p-5 text-sm">
            No historical database is configured on this server. Set the server-only
            <code className="mx-1 rounded bg-[var(--muted)] px-1.5 py-0.5">TEEECHR_LEGACY_CHAT_DB</code>
            path and refresh this page.
          </div>
        ) : (
          <div className="mt-5 grid gap-3">
            {sources.map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => setSourceId(item.id)}
                className={`rounded-xl border p-4 text-left ${sourceId === item.id ? "border-[var(--primary)] bg-[var(--primary)]/5" : "border-[var(--border)]"}`}
              >
                <div className="flex items-center justify-between gap-3">
                  <span className="font-medium">{item.label}</span>
                  <span className={`text-xs ${item.compatible ? "text-emerald-600" : "text-amber-600"}`}>
                    {item.compatible ? "Ready to inspect" : "Needs attention"}
                  </span>
                </div>
                <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-xs text-[var(--muted-foreground)]">
                  <span>{formatBytes(item.size_bytes)}</span>
                  <span>Database proof {shortFingerprint(item.database_sha256)}</span>
                  <span>{item.owners.length} historical profile{item.owners.length === 1 ? "" : "s"}</span>
                </div>
              </button>
            ))}
          </div>
        )}
      </section>

      {source?.compatible ? (
        <>
          <section className="mt-6 rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5 sm:p-6">
            <h2 className="text-lg font-semibold">2. Choose your historical profile</h2>
            <p className="mt-1 text-sm text-[var(--muted-foreground)]">
              We do not show old usernames or private titles. Use the activity counts to identify the profile you recognize.
            </p>
            <div className="mt-5 grid gap-3 sm:grid-cols-2">
              {orderedOwners.map((owner, index) => (
                <label
                  key={owner.designation}
                  className={`cursor-pointer rounded-xl border p-4 ${ownerDesignation === owner.designation ? "border-[var(--primary)] bg-[var(--primary)]/5" : "border-[var(--border)]"}`}
                >
                  <div className="flex items-center gap-3">
                    <input
                      type="radio"
                      name="legacy-owner"
                      checked={ownerDesignation === owner.designation}
                      onChange={() => setOwnerDesignation(owner.designation)}
                    />
                    <span className="font-medium">Historical profile {index + 1}</span>
                  </div>
                  <div className="mt-3 grid grid-cols-3 gap-2 text-center text-xs">
                    <ActivityCount value={owner.session_count} label="Chats" />
                    <ActivityCount value={owner.practice_attempt_count} label="Quizzes" />
                    <ActivityCount value={owner.flashcard_deck_count} label="Decks" />
                  </div>
                </label>
              ))}
            </div>
          </section>

          <section className="mt-6 rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5 sm:p-6">
            <h2 className="text-lg font-semibold">3. Preview the destinations</h2>
            <p className="mt-1 text-sm text-[var(--muted-foreground)]">
              This choice is part of the dry-run report. It does not move anything yet.
            </p>
            <div className="mt-5 grid gap-4 sm:grid-cols-2">
              <label className="grid gap-2 text-sm font-medium">
                Historical Practice
                <select
                  value={practiceCourseId}
                  onChange={(event) => { setPracticeCourseId(event.target.value); setReport(null); }}
                  className="rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2.5 font-normal"
                >
                  <option value="">Decide later</option>
                  {academicCourses.map((course) => <option key={course.id} value={course.id}>{course.title}</option>)}
                </select>
                <span className="text-xs font-normal text-[var(--muted-foreground)]">Practice needs one active academic Course.</span>
              </label>
              <label className="grid gap-2 text-sm font-medium">
                Historical Flashcards
                <select
                  value={flashcardWorkspaceId}
                  onChange={(event) => { setFlashcardWorkspaceId(event.target.value); setReport(null); }}
                  className="rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2.5 font-normal"
                >
                  <option value="">Decide later</option>
                  {flashcardDestinations.map((course) => (
                    <option key={course.id} value={course.id}>
                      {course.title}{course.workspace_kind === "general_study" ? " (General Study)" : ""}
                    </option>
                  ))}
                </select>
                <span className="text-xs font-normal text-[var(--muted-foreground)]">General Study keeps cards separate from Course mastery.</span>
              </label>
            </div>
            <div className="mt-5 flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={() => void runDryScan()}
                disabled={!ownerDesignation || scanning}
                className="inline-flex items-center gap-2 rounded-lg bg-[var(--primary)] px-4 py-2.5 text-sm font-medium text-[var(--primary-foreground)] disabled:opacity-50"
              >
                <FileSearch size={16} /> {scanning ? "Inspecting safely…" : "Create zero-write report"}
              </button>
              <span className="inline-flex items-center gap-1.5 text-xs text-[var(--muted-foreground)]">
                <LockKeyhole size={13} /> Import remains locked
              </span>
            </div>
          </section>
        </>
      ) : null}

      {error ? (
        <div role="alert" className="mt-6 flex gap-3 rounded-xl border border-red-500/30 bg-red-500/5 p-4 text-sm text-red-700 dark:text-red-300">
          <AlertTriangle size={18} className="mt-0.5 shrink-0" /> {error}
        </div>
      ) : null}

      {report ? <MigrationReport report={report} /> : null}
    </div>
  );
}

function Boundary({ icon: Icon, title, body }: { icon: typeof LockKeyhole; title: string; body: string }) {
  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--card)] p-4">
      <Icon size={17} className="text-emerald-600" />
      <div className="mt-2 text-sm font-medium">{title}</div>
      <div className="mt-1 text-xs leading-5 text-[var(--muted-foreground)]">{body}</div>
    </div>
  );
}

function ActivityCount({ value, label }: { value: number; label: string }) {
  return <div className="rounded-lg bg-[var(--muted)]/50 px-2 py-2"><div className="text-base font-semibold">{value}</div><div className="text-[var(--muted-foreground)]">{label}</div></div>;
}

function MigrationReport({ report }: { report: HistoricalMigrationDryRun }) {
  return (
    <section className="mt-6 rounded-2xl border border-emerald-500/30 bg-emerald-500/5 p-5 sm:p-6">
      <div className="flex items-start gap-3">
        <CheckCircle2 size={21} className="mt-0.5 shrink-0 text-emerald-600" />
        <div>
          <h2 className="text-lg font-semibold">Safe inspection complete</h2>
          <p className="mt-1 text-sm text-[var(--muted-foreground)]">
            No records were imported, changed, deleted, or added to mastery.
          </p>
        </div>
      </div>

      <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-5">
        <Total value={report.totals.importable} label="Eligible" tone="text-emerald-600" />
        <Total value={report.totals.ambiguous} label="Needs a decision" tone="text-amber-600" />
        <Total value={report.totals.orphaned} label="Missing parent" tone="text-orange-600" />
        <Total value={report.totals.duplicate} label="Already represented" tone="text-blue-600" />
        <Total value={report.totals.rejected} label="Cannot import" tone="text-red-600" />
      </div>

      <div className="mt-5 overflow-x-auto rounded-xl border border-[var(--border)] bg-[var(--background)]">
        <table className="w-full min-w-[720px] text-left text-sm">
          <thead className="border-b border-[var(--border)] text-xs text-[var(--muted-foreground)]">
            <tr><th className="px-4 py-3">Historical material</th><th className="px-3 py-3">Eligible</th><th className="px-3 py-3">Decision</th><th className="px-3 py-3">Missing</th><th className="px-3 py-3">Duplicate</th><th className="px-3 py-3">Rejected</th></tr>
          </thead>
          <tbody>
            {report.classifications.map((item) => (
              <tr key={item.table} className="border-b border-[var(--border)]/60 last:border-0">
                <td className="px-4 py-3 font-medium">{TABLE_LABELS[item.table] || item.table}</td>
                <td className="px-3 py-3">{item.counts.importable}</td>
                <td className="px-3 py-3">{item.counts.ambiguous}</td>
                <td className="px-3 py-3">{item.counts.orphaned}</td>
                <td className="px-3 py-3">{item.counts.duplicate}</td>
                <td className="px-3 py-3">{item.counts.rejected}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {report.required_decisions.length ? (
        <div className="mt-5 rounded-xl border border-amber-500/30 bg-amber-500/5 p-4">
          <h3 className="text-sm font-semibold">Before any future import</h3>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-[var(--muted-foreground)]">
            {report.required_decisions.map((decision) => <li key={decision}>{decision}</li>)}
          </ul>
        </div>
      ) : null}

      <div className="mt-5 flex flex-wrap gap-x-6 gap-y-2 text-xs text-[var(--muted-foreground)]">
        <span>Campaign {report.campaign_id}</span>
        <span>Manifest {shortFingerprint(report.manifest_sha256)}</span>
        <span>Database {shortFingerprint(report.source_database_sha256)}</span>
      </div>

      <div className="mt-5 rounded-xl border border-[var(--border)] bg-[var(--card)] p-4 text-sm">
        <strong>Import is intentionally unavailable.</strong>{" "}
        Review this report first. The later apply phase will require a second explicit approval and a locked copy of this exact manifest.
      </div>
    </section>
  );
}

function Total({ value, label, tone }: { value: number; label: string; tone: string }) {
  return <div className="rounded-xl border border-[var(--border)] bg-[var(--background)] p-3"><div className={`text-2xl font-semibold ${tone}`}>{value}</div><div className="mt-1 text-xs text-[var(--muted-foreground)]">{label}</div></div>;
}
