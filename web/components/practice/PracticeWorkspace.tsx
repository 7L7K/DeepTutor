"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Archive, CheckCircle2, ClipboardCheck, Loader2, Play, RotateCcw, Save, Send, XCircle } from "lucide-react";
import { useRouter } from "next/navigation";
import { CourseBar } from "@/components/courses/CourseBar";
import { useCourses } from "@/context/CourseContext";
import { fetchAuthStatus } from "@/lib/auth";
import {
  abandonPracticeAttempt,
  addPracticeQuestion,
  advancePracticeViewScope,
  archivePracticeSet,
  autosavePracticeAnswer,
  createPracticeRevision,
  createPracticeSet,
  formatPracticeScore,
  getPracticeAttempt,
  getPracticeSet,
  getPracticeResults,
  getPracticeRevision,
  gradePracticeAttempt,
  hasUnsavedPracticeAnswers,
  isCurrentPracticeResponse,
  learnerSafePracticeQuestions,
  listPracticeAttempts,
  listPracticeQuestions,
  listPracticeSets,
  preparePracticeRemediationFlashcards,
  readyPracticeRevision,
  restorePracticeSet,
  startPracticeAttempt,
  submitPracticeAttempt,
  type PracticeQuestion,
  type PracticeRequestScope,
  type PracticeRevision,
  type PracticeSet,
  type QuizAttempt,
  type QuizAttemptAnswer,
  type QuizAttemptView,
  type QuizResult,
} from "@/lib/practice-api";
import { storeFlashcardProposal } from "@/lib/flashcards-api";

function newIdempotencyKey(): string {
  return globalThis.crypto?.randomUUID?.() ?? `practice-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function errorText(cause: unknown): string {
  return cause instanceof Error ? cause.message : "Practice request failed";
}

type QuestionDraft = {
  prompt: string;
  answer: string;
  explanation: string;
  objectiveIds: string;
};

const emptyQuestion: QuestionDraft = {
  prompt: "",
  answer: "",
  explanation: "",
  objectiveIds: "",
};

/** Minimal manual Course Practice workspace. No generated content or local quiz cache. */
export default function PracticeWorkspace() {
  const router = useRouter();
  const { activeCourse, refresh: refreshCourses } = useCourses();
  const [identity, setIdentity] = useState<string | null>(null);
  const [sets, setSets] = useState<PracticeSet[]>([]);
  const [selectedSetId, setSelectedSetId] = useState<string | null>(null);
  const [revision, setRevision] = useState<PracticeRevision | null>(null);
  const [questions, setQuestions] = useState<PracticeQuestion[]>([]);
  const [attempts, setAttempts] = useState<QuizAttempt[]>([]);
  const [attemptsHaveMore, setAttemptsHaveMore] = useState(false);
  const [attemptView, setAttemptView] = useState<QuizAttemptView | null>(null);
  const [resultView, setResultView] = useState<QuizResult | null>(null);
  const [setTitle, setSetTitle] = useState("");
  const [draft, setDraft] = useState<QuestionDraft>(emptyQuestion);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const epochRef = useRef(0);
  const scopeRef = useRef<PracticeRequestScope>({ identity: null, courseId: null, epoch: 0, viewEpoch: 0 });

  const selectedSet = useMemo(
    () => sets.find((item) => item.id === selectedSetId) ?? null,
    [sets, selectedSetId],
  );
  const courseId = activeCourse?.id ?? null;
  const scopeReady = Boolean(
    identity &&
      courseId &&
      scopeRef.current.identity === identity &&
      scopeRef.current.courseId === courseId,
  );
  const courseWritable = activeCourse?.state === "active" && scopeReady;
  const readOnly = !courseWritable || selectedSet?.state === "archived";

  const invalidate = useCallback((nextIdentity: string | null, nextCourseId: string | null) => {
    const scope = { identity: nextIdentity, courseId: nextCourseId, epoch: ++epochRef.current, viewEpoch: 0 };
    scopeRef.current = scope;
    setSets([]);
    setSelectedSetId(null);
    setRevision(null);
    setQuestions([]);
    setAttempts([]);
    setAttemptsHaveMore(false);
    setAttemptView(null);
    setResultView(null);
    setSetTitle("");
    setDraft(emptyQuestion);
    setBusy(false);
    setStatus(null);
    setError(null);
    return scope;
  }, []);

  const current = useCallback((scope: PracticeRequestScope) => isCurrentPracticeResponse(scope, scopeRef.current), []);

  const advanceView = useCallback(() => {
    const next = advancePracticeViewScope(scopeRef.current);
    scopeRef.current = next;
    // A new view deliberately invalidates any old write. Its old finally
    // cannot clear the shared busy flag, so clear it at the handoff point.
    setBusy(false);
    return next;
  }, []);

  const loadSetDetail = useCallback(async (scope: PracticeRequestScope, practiceSet: PracticeSet, revisionId: string | null) => {
    const [history, loadedRevision] = await Promise.all([
      listPracticeAttempts(practiceSet.course_id, practiceSet.id),
      revisionId ? getPracticeRevision(practiceSet.course_id, practiceSet.id, revisionId) : Promise.resolve(null),
    ]);
    if (!current(scope)) return;
    setAttempts(history);
    setAttemptsHaveMore(history.length === 50);
    setRevision(loadedRevision);
    if (!loadedRevision) {
      setQuestions([]);
      return;
    }
    const loadedQuestions = await listPracticeQuestions(practiceSet.course_id, practiceSet.id, loadedRevision.id);
    if (!current(scope)) return;
    setQuestions(loadedQuestions);
  }, [current]);

  const loadCourse = useCallback(async (scope: PracticeRequestScope) => {
    if (!scope.courseId) return;
    const listed = await listPracticeSets(scope.courseId);
    if (!current(scope)) return;
    setSets(listed);
    const usable = listed.find((set) => set.state === "draft") ?? null;
    setSelectedSetId(usable?.id ?? null);
    if (usable) {
      const detailScope = advanceView();
      try {
        await loadSetDetail(detailScope, usable, usable.current_revision_id);
      } catch (cause) {
        if (current(detailScope)) setError(errorText(cause));
      }
    }
  }, [advanceView, current, loadSetDetail]);

  useEffect(() => {
    let alive = true;
    const update = async () => {
      const auth = await fetchAuthStatus();
      if (!alive) return;
      const nextIdentity = auth?.authenticated ? auth.user_id ?? null : null;
      setIdentity(nextIdentity);
      const scope = invalidate(nextIdentity, courseId);
      if (nextIdentity && courseId) {
        try {
          await loadCourse(scope);
        } catch (cause) {
          if (current(scope)) setError(errorText(cause));
        }
      }
    };
    void update();
    return () => { alive = false; };
  }, [courseId, current, invalidate, loadCourse]);

  useEffect(() => {
    const onAuthChanged = () => {
      const scope = invalidate(null, null);
      setIdentity(null);
      void fetchAuthStatus().then(async (auth) => {
        const nextIdentity = auth?.authenticated ? auth.user_id ?? null : null;
        setIdentity(nextIdentity);
        const nextScope = invalidate(nextIdentity, activeCourse?.id ?? null);
        if (nextIdentity && nextScope.courseId) {
          try { await loadCourse(nextScope); } catch (cause) { if (current(nextScope)) setError(errorText(cause)); }
        }
      });
      void scope;
    };
    window.addEventListener("dt:auth-changed", onAuthChanged);
    return () => window.removeEventListener("dt:auth-changed", onAuthChanged);
  }, [activeCourse?.id, current, invalidate, loadCourse]);

  const selectSet = useCallback(async (practiceSet: PracticeSet) => {
    const scope = advanceView();
    setSelectedSetId(practiceSet.id);
    // Fail closed while the next set detail is loading: never render or edit
    // the prior set/revision beneath the newly selected set title.
    setRevision(null);
    setQuestions([]);
    setAttempts([]);
    setAttemptsHaveMore(false);
    setAttemptView(null);
    setResultView(null);
    setDraft(emptyQuestion);
    setStatus(null);
    setError(null);
    try {
      await loadSetDetail(scope, practiceSet, practiceSet.current_revision_id);
    } catch (cause) {
      if (current(scope)) setError(errorText(cause));
    }
  }, [advanceView, loadSetDetail]);

  const createSet = useCallback(async () => {
    if (!activeCourse || !setTitle.trim() || !courseWritable) return;
    // Advance before issuing writes. Advancing after a successful response
    // would invalidate this operation's own finally block and strand busy UI.
    const scope = advanceView();
    setBusy(true); setError(null);
    try {
      const created = await createPracticeSet(activeCourse.id, setTitle.trim(), activeCourse.write_epoch);
      // A successfully created set requires its initial revision. Finish this
      // dependent durable write even if a same-owner view refresh supersedes
      // the UI scope; the server still revalidates auth and Course ownership.
      const draftRevision = await createPracticeRevision(activeCourse.id, created.id, activeCourse.write_epoch);
      if (!current(scope)) return;
      setSets((previous) => [created, ...previous]);
      setSelectedSetId(created.id);
      setRevision(draftRevision);
      setQuestions([]); setAttempts([]); setAttemptsHaveMore(false); setAttemptView(null); setResultView(null); setSetTitle(""); setDraft(emptyQuestion);
      setStatus("Draft Practice set created.");
    } catch (cause) {
      if (current(scope)) setError(errorText(cause));
    } finally {
      if (current(scope)) setBusy(false);
    }
  }, [activeCourse, advanceView, courseWritable, current, setTitle]);

  const addQuestion = useCallback(async () => {
    if (!activeCourse || !selectedSet || !revision || revision.state !== "draft" || readOnly) return;
    if (!draft.prompt.trim() || !draft.answer.trim()) return;
    const scope = scopeRef.current;
    setBusy(true); setError(null);
    try {
      const question = await addPracticeQuestion(activeCourse.id, selectedSet.id, revision.id, {
        question_type: "exact",
        prompt: draft.prompt.trim(),
        answer_contract: { kind: "exact", answer: draft.answer.trim() },
        explanation: draft.explanation.trim(),
        objective_ids: draft.objectiveIds.split(",").map((value) => value.trim()).filter(Boolean),
        expected_course_write_epoch: activeCourse.write_epoch,
      });
      if (!current(scope)) return;
      setQuestions((previous) => [...previous, question]);
      setDraft(emptyQuestion);
      setStatus("Question added.");
    } catch (cause) {
      if (current(scope)) setError(errorText(cause));
    } finally { if (current(scope)) setBusy(false); }
  }, [activeCourse, current, draft, readOnly, revision, selectedSet]);

  const markReady = useCallback(async () => {
    if (!activeCourse || !selectedSet || !revision || readOnly) return;
    const scope = scopeRef.current;
    setBusy(true); setError(null);
    try {
      const ready = await readyPracticeRevision(activeCourse.id, selectedSet.id, revision.id, activeCourse.write_epoch);
      if (!current(scope)) return;
      // Publishing advances the set's epoch/revision. Re-read it before any
      // subsequent start/archive write so this tab cannot reuse stale authority.
      const updated = await getPracticeSet(activeCourse.id, selectedSet.id);
      if (!current(scope)) return;
      // Clear the pre-publication answer contracts synchronously, then replace
      // them with the server's learner-safe ready representation.
      setQuestions((previous) => learnerSafePracticeQuestions(previous));
      setDraft(emptyQuestion);
      const safeQuestions = await listPracticeQuestions(activeCourse.id, selectedSet.id, ready.id);
      if (!current(scope)) return;
      setSets((previous) => previous.map((item) => item.id === updated.id ? updated : item));
      setRevision(ready); setQuestions(safeQuestions); setStatus("Practice is ready to take.");
    } catch (cause) { if (current(scope)) setError(errorText(cause)); }
    finally { if (current(scope)) setBusy(false); }
  }, [activeCourse, current, readOnly, revision, selectedSet]);

  const createSuccessor = useCallback(async () => {
    if (!activeCourse || !selectedSet || readOnly) return;
    const scope = advanceView();
    setBusy(true); setError(null);
    try {
      const next = await createPracticeRevision(activeCourse.id, selectedSet.id, activeCourse.write_epoch, true);
      if (!current(scope)) return;
      setRevision(next); setQuestions([]); setAttemptView(null); setResultView(null); setDraft(emptyQuestion); setStatus("New draft revision created.");
    } catch (cause) { if (current(scope)) setError(errorText(cause)); }
    finally { if (current(scope)) setBusy(false); }
  }, [activeCourse, advanceView, current, readOnly, selectedSet]);

  const startOrResume = useCallback(async () => {
    if (!activeCourse || !selectedSet || !revision || revision.state !== "ready" || revision.id !== selectedSet.current_revision_id || readOnly) return;
    const scope = scopeRef.current;
    setBusy(true); setError(null);
    try {
      const view = await startPracticeAttempt(activeCourse.id, selectedSet, revision.id, activeCourse.write_epoch);
      if (!current(scope)) return;
      setAttemptView(view); setResultView(null); setStatus(view.attempt.state === "in_progress" ? "Quiz resumed." : "Quiz loaded.");
      const history = await listPracticeAttempts(activeCourse.id, selectedSet.id);
      if (current(scope)) {
        setAttempts(history);
        setAttemptsHaveMore(history.length === 50);
      }
    } catch (cause) { if (current(scope)) setError(errorText(cause)); }
    finally { if (current(scope)) setBusy(false); }
  }, [activeCourse, current, readOnly, revision, selectedSet]);

  const openAttempt = useCallback(async (attempt: QuizAttempt) => {
    if (!activeCourse || !selectedSet) return;
    const scope = advanceView();
    setBusy(true); setError(null);
    try {
      const view = await getPracticeAttempt(activeCourse.id, selectedSet.id, attempt.id);
      if (!current(scope)) return;
      const attemptRevision = await getPracticeRevision(activeCourse.id, selectedSet.id, view.attempt.practice_set_revision_id);
      if (!current(scope)) return;
      const attemptQuestions = await listPracticeQuestions(activeCourse.id, selectedSet.id, attemptRevision.id);
      if (!current(scope)) return;
      setRevision(attemptRevision);
      setQuestions(attemptQuestions);
      setAttemptView(view);
      if (view.attempt.state === "graded") {
        const results = await getPracticeResults(activeCourse.id, selectedSet.id, view.attempt.id);
        if (current(scope)) setResultView(results);
      } else setResultView(null);
    } catch (cause) { if (current(scope)) setError(errorText(cause)); }
    finally { if (current(scope)) setBusy(false); }
  }, [activeCourse, advanceView, current, selectedSet]);

  const answerFor = useCallback((itemId: string): QuizAttemptAnswer | null =>
    attemptView?.answers.find((answer) => answer.attempt_item_id === itemId) ?? null,
  [attemptView]);

  const saveAnswer = useCallback(async (itemId: string, value: string) => {
    if (!activeCourse || !selectedSet || !attemptView || attemptView.attempt.state !== "in_progress" || readOnly) return;
    const answer = answerFor(itemId);
    if (!answer) return;
    const scope = scopeRef.current;
    setBusy(true); setError(null);
    try {
      const saved = await autosavePracticeAnswer(activeCourse.id, selectedSet, attemptView.attempt, answer, { answer: value }, newIdempotencyKey());
      if (!current(scope)) return;
      setAttemptView((previous) => previous ? {
        ...previous,
        answers: previous.answers.map((item) => item.attempt_item_id === saved.attempt_item_id ? saved : item),
      } : previous);
      setStatus("Answer saved.");
    } catch (cause) { if (current(scope)) setError(errorText(cause)); }
    finally { if (current(scope)) setBusy(false); }
  }, [activeCourse, answerFor, attemptView, current, readOnly, selectedSet]);

  const transitionAttempt = useCallback(async (action: "submit" | "abandon" | "grade") => {
    if (!activeCourse || !selectedSet || !attemptView || readOnly) return;
    const scope = scopeRef.current;
    setBusy(true); setError(null);
    try {
      const changed = action === "submit"
        ? await submitPracticeAttempt(activeCourse.id, selectedSet, attemptView.attempt)
        : action === "abandon"
          ? await abandonPracticeAttempt(activeCourse.id, selectedSet, attemptView.attempt)
          : await gradePracticeAttempt(activeCourse.id, selectedSet, attemptView.attempt);
      if (!current(scope)) return;
      const view = await getPracticeAttempt(activeCourse.id, selectedSet.id, changed.id);
      if (!current(scope)) return;
      const attemptRevision = await getPracticeRevision(activeCourse.id, selectedSet.id, view.attempt.practice_set_revision_id);
      if (!current(scope)) return;
      const attemptQuestions = await listPracticeQuestions(activeCourse.id, selectedSet.id, attemptRevision.id);
      if (!current(scope)) return;
      setRevision(attemptRevision);
      setQuestions(attemptQuestions);
      setAttemptView(view);
      if (view.attempt.state === "graded") {
        const results = await getPracticeResults(activeCourse.id, selectedSet.id, changed.id);
        if (current(scope)) setResultView(results);
      }
      const history = await listPracticeAttempts(activeCourse.id, selectedSet.id);
      if (current(scope)) {
        setAttempts(history);
        setAttemptsHaveMore(history.length === 50);
      }
      if (current(scope)) setStatus(action === "submit" ? "Quiz submitted." : action === "grade" ? "Quiz graded." : "Quiz abandoned.");
    } catch (cause) { if (current(scope)) setError(errorText(cause)); }
    finally { if (current(scope)) setBusy(false); }
  }, [activeCourse, attemptView, current, readOnly, selectedSet]);

  const reviewMissesAsFlashcards = useCallback(async () => {
    if (
      !identity ||
      !activeCourse ||
      !selectedSet ||
      !attemptView ||
      attemptView.attempt.state !== "graded"
    ) return;
    const scope = scopeRef.current;
    setBusy(true); setError(null);
    try {
      const proposal = await preparePracticeRemediationFlashcards(
        activeCourse.id,
        selectedSet.id,
        attemptView.attempt.id,
      );
      if (!current(scope)) return;
      storeFlashcardProposal(identity, activeCourse.id, proposal);
      router.push("/flashcards");
    } catch (cause) {
      if (current(scope)) setError(errorText(cause));
    } finally {
      if (current(scope)) setBusy(false);
    }
  }, [activeCourse, attemptView, current, identity, router, selectedSet]);

  const archiveOrRestore = useCallback(async () => {
    if (!activeCourse || !selectedSet) return;
    const scope = scopeRef.current;
    setBusy(true); setError(null);
    try {
      const changed = selectedSet.state === "archived"
        ? await restorePracticeSet(activeCourse.id, selectedSet, activeCourse.write_epoch)
        : await archivePracticeSet(activeCourse.id, selectedSet, activeCourse.write_epoch);
      if (!current(scope)) return;
      setSets((previous) => previous.map((item) => item.id === changed.id ? changed : item));
      setStatus(changed.state === "archived" ? "Practice archived. Its history is retained." : "Practice restored.");
      if (changed.state === "archived") { setAttemptView(null); setResultView(null); }
      await refreshCourses();
    } catch (cause) { if (current(scope)) setError(errorText(cause)); }
    finally { if (current(scope)) setBusy(false); }
  }, [activeCourse, current, refreshCourses, selectedSet]);

  const loadMoreAttempts = useCallback(async () => {
    if (!activeCourse || !selectedSet || !attemptsHaveMore || busy) return;
    const scope = scopeRef.current;
    setBusy(true); setError(null);
    try {
      const next = await listPracticeAttempts(
        activeCourse.id,
        selectedSet.id,
        attempts.length,
      );
      if (!current(scope)) return;
      setAttempts((previous) => [...previous, ...next]);
      setAttemptsHaveMore(next.length === 50);
    } catch (cause) {
      if (current(scope)) setError(errorText(cause));
    } finally {
      if (current(scope)) setBusy(false);
    }
  }, [activeCourse, attempts.length, attemptsHaveMore, busy, current, selectedSet]);

  return (
    <div className="flex h-full min-h-0 flex-col overflow-y-auto">
      <CourseBar />
      <main className="mx-auto w-full max-w-6xl px-6 py-6">
        <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold">Practice</h1>
            <p className="mt-1 text-sm text-[var(--muted-foreground)]">Manual Course quizzes. Questions, answers, and results stay private to this Course.</p>
          </div>
          {activeCourse ? <div className="rounded-lg border border-[var(--border)] bg-[var(--card)] px-3 py-2 text-sm"><span className="text-[var(--muted-foreground)]">Active Course: </span><strong>{activeCourse.title}</strong></div> : null}
        </div>

        {!identity ? <p className="rounded-lg border border-[var(--border)] p-4 text-sm text-[var(--muted-foreground)]">Sign in to use private Course Practice.</p> : null}
        {identity && !activeCourse ? <p className="rounded-lg border border-[var(--border)] p-4 text-sm text-[var(--muted-foreground)]">Select or create a Course above to create private Practice sets.</p> : null}
        {activeCourse ? <div className="grid gap-5 lg:grid-cols-[260px_minmax(0,1fr)]">
          <aside className="rounded-xl border border-[var(--border)] bg-[var(--card)] p-3">
            <h2 className="mb-3 font-medium">Practice library</h2>
            <div className="mb-3 flex gap-2">
              <input aria-label="New Practice title" value={setTitle} onChange={(event) => setSetTitle(event.target.value)} disabled={!courseWritable || busy} placeholder="New Practice title" className="min-w-0 flex-1 rounded-lg border border-[var(--border)] bg-[var(--background)] px-2 py-1.5 text-sm" />
              <button disabled={!setTitle.trim() || !courseWritable || busy} onClick={() => void createSet()} className="rounded-lg bg-[var(--primary)] px-3 text-sm text-[var(--primary-foreground)] disabled:opacity-50">Create</button>
            </div>
            <div className="space-y-1">
              {sets.map((item) => <button key={item.id} onClick={() => void selectSet(item)} className={`w-full rounded-lg px-3 py-2 text-left text-sm ${item.id === selectedSetId ? "bg-[var(--accent)]" : "hover:bg-[var(--muted)]"}`}>
                <span className="block truncate font-medium">{item.title}</span><span className="text-xs text-[var(--muted-foreground)]">{item.state === "archived" ? "Archived" : item.current_revision_id ? "Ready" : "Draft"}</span>
              </button>)}
              {!sets.length ? <p className="px-2 py-3 text-sm text-[var(--muted-foreground)]">No Practice sets yet.</p> : null}
            </div>
          </aside>

          <section className="min-w-0 rounded-xl border border-[var(--border)] bg-[var(--card)] p-5">
            {selectedSet ? <>
              <div className="mb-5 flex flex-wrap items-center justify-between gap-3 border-b border-[var(--border)] pb-4">
                <div><h2 className="text-lg font-semibold">{selectedSet.title}</h2><p className="text-sm text-[var(--muted-foreground)]">{selectedSet.state === "archived" ? "Archived — read-only history" : revision?.state === "ready" ? "Ready for quiz attempts" : "Draft revision"}</p></div>
                <button disabled={busy || !activeCourse} onClick={() => void archiveOrRestore()} className="inline-flex items-center gap-1 rounded-lg border border-[var(--border)] px-3 py-2 text-sm disabled:opacity-50">{selectedSet.state === "archived" ? <RotateCcw size={15} /> : <Archive size={15} />}{selectedSet.state === "archived" ? "Restore" : "Archive"}</button>
              </div>
              {revision?.state === "draft" && !readOnly ? <div className="mb-6 rounded-lg border border-[var(--border)] p-4">
                <h3 className="mb-3 font-medium">Add exact-answer question</h3>
                <div className="grid gap-3">
                  <label className="grid gap-1 text-sm">
                    <span>Question prompt</span>
                    <textarea value={draft.prompt} onChange={(event) => setDraft((value) => ({ ...value, prompt: event.target.value }))} placeholder="What should the learner answer?" className="min-h-20 rounded-lg border border-[var(--border)] bg-[var(--background)] p-2 text-sm" />
                  </label>
                  <label className="grid gap-1 text-sm">
                    <span>Correct answer</span>
                    <input value={draft.answer} onChange={(event) => setDraft((value) => ({ ...value, answer: event.target.value }))} placeholder="Exact accepted answer" className="rounded-lg border border-[var(--border)] bg-[var(--background)] px-2 py-2 text-sm" />
                  </label>
                  <label className="grid gap-1 text-sm">
                    <span>Explanation <span className="text-[var(--muted-foreground)]">(optional)</span></span>
                    <textarea value={draft.explanation} onChange={(event) => setDraft((value) => ({ ...value, explanation: event.target.value }))} placeholder="Shown after grading" className="min-h-16 rounded-lg border border-[var(--border)] bg-[var(--background)] p-2 text-sm" />
                  </label>
                  <label className="grid gap-1 text-sm">
                    <span>Objective IDs <span className="text-[var(--muted-foreground)]">(optional)</span></span>
                    <input value={draft.objectiveIds} onChange={(event) => setDraft((value) => ({ ...value, objectiveIds: event.target.value }))} placeholder="Comma-separated objective IDs" className="rounded-lg border border-[var(--border)] bg-[var(--background)] px-2 py-2 text-sm" />
                  </label>
                </div>
                <div className="mt-3 flex flex-wrap gap-2"><button disabled={busy || !draft.prompt.trim() || !draft.answer.trim()} onClick={() => void addQuestion()} className="inline-flex items-center gap-1 rounded-lg bg-[var(--primary)] px-3 py-2 text-sm text-[var(--primary-foreground)] disabled:opacity-50"><Save size={15} />Add question</button><button disabled={busy || !questions.length} onClick={() => void markReady()} className="inline-flex items-center gap-1 rounded-lg border border-[var(--border)] px-3 py-2 text-sm disabled:opacity-50"><CheckCircle2 size={15} />Mark ready</button></div>
              </div> : null}
              {revision?.state === "ready" && !readOnly ? <div className="mb-5 flex flex-wrap gap-2">{revision.id === selectedSet.current_revision_id ? <button disabled={busy} onClick={() => void startOrResume()} className="inline-flex items-center gap-1 rounded-lg bg-[var(--primary)] px-3 py-2 text-sm text-[var(--primary-foreground)]"><Play size={15} />Start or resume quiz</button> : <span className="self-center text-sm text-[var(--muted-foreground)]">Historical revision — attempts are read-only.</span>}<button disabled={busy} onClick={() => void createSuccessor()} className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm">Create successor revision</button></div> : null}
              {questions.length ? <ol className="mb-6 space-y-3">{questions.map((question) => <li key={question.id} className="rounded-lg border border-[var(--border)] p-3"><span className="mr-2 text-xs text-[var(--muted-foreground)]">{question.ordinal}.</span>{question.prompt}{revision?.state === "ready" ? null : <p className="mt-2 text-xs text-[var(--muted-foreground)]">Answer: {question.answer_contract?.answer ?? "Stored server-side"}</p>}</li>)}</ol> : null}
              {attemptView ? <AttemptRunner key={attemptView.attempt.id} view={attemptView} questions={questions} readOnly={readOnly || busy} answerFor={answerFor} onSave={(item, value) => void saveAnswer(item, value)} onTransition={(action) => void transitionAttempt(action)} onReviewMisses={() => void reviewMissesAsFlashcards()} resultView={resultView} /> : null}
              <AttemptHistory attempts={attempts} onOpen={(item) => void openAttempt(item)} busy={busy} hasMore={attemptsHaveMore} onLoadMore={() => void loadMoreAttempts()} />
            </> : <p className="text-sm text-[var(--muted-foreground)]">Choose a Practice set or create one.</p>}
          </section>
        </div> : null}
        {status ? <p role="status" className="mt-4 text-sm text-emerald-600">{status}</p> : null}
        {error ? <p role="alert" className="mt-4 text-sm text-red-600">{error}</p> : null}
      </main>
    </div>
  );
}

function AttemptRunner({ view, questions, readOnly, answerFor, onSave, onTransition, onReviewMisses, resultView }: {
  view: QuizAttemptView; questions: PracticeQuestion[]; readOnly: boolean; answerFor: (itemId: string) => QuizAttemptAnswer | null; onSave: (itemId: string, value: string) => void; onTransition: (action: "submit" | "abandon" | "grade") => void; onReviewMisses: () => void; resultView: QuizResult | null;
}) {
  const byId = useMemo(() => new Map((resultView?.questions ?? questions).map((question) => [question.id, question])), [questions, resultView?.questions]);
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(view.answers.map((answer) => [answer.attempt_item_id, answer.response?.answer ?? ""])),
  );
  const active = view.attempt.state === "in_progress";
  const hasUnsaved = hasUnsavedPracticeAnswers(values, view.answers);
  const score = resultView?.attempt.score;
  const hasMisses =
    typeof score?.correct === "number" &&
    typeof score?.total === "number" &&
    score.correct < score.total;
  return <div className="mb-6 rounded-xl border border-[var(--border)] p-4"><div className="mb-4 flex flex-wrap items-center justify-between gap-2"><h3 className="font-semibold">Quiz attempt</h3><span className="rounded-full bg-[var(--muted)] px-2 py-1 text-xs">{view.attempt.state}{formatPracticeScore(view.attempt.score) ? ` · ${formatPracticeScore(view.attempt.score)}` : ""}</span></div>
    <div className="space-y-4">{view.items.map((item) => { const question = byId.get(item.question_id); const answer = answerFor(item.id); const dirty = (values[item.id] ?? "") !== (answer?.response?.answer ?? ""); return <article key={item.id} className="rounded-lg border border-[var(--border)] p-3"><p className="font-medium">{item.display_ordinal}. {question?.prompt ?? "Question unavailable"}</p><div className="mt-3 flex gap-2"><input aria-label={`Answer for question ${item.display_ordinal}`} value={values[item.id] ?? ""} disabled={!active || readOnly} onChange={(event) => setValues((previous) => ({ ...previous, [item.id]: event.target.value }))} className="min-w-0 flex-1 rounded-lg border border-[var(--border)] bg-[var(--background)] px-2 py-2 text-sm disabled:opacity-60" placeholder="Your answer" /><button disabled={!active || readOnly || !dirty} onClick={() => onSave(item.id, values[item.id] ?? "")} className="rounded-lg border border-[var(--border)] px-3 text-sm disabled:opacity-50">Save</button></div>{answer ? <p className="mt-1 text-xs text-[var(--muted-foreground)]">Saved revision {answer.revision}{dirty ? " · unsaved changes" : ""}</p> : null}{item.grading ? <p className="mt-2 text-sm">{String(item.grading.is_correct) === "true" ? "Correct" : "Review this answer"}{question?.explanation ? ` — ${question.explanation}` : ""}{resultView?.attempt.state === "graded" && question?.answer_contract ? ` Expected answer: ${question.answer_contract.answer}` : ""}</p> : null}</article>; })}</div>
    <div className="mt-4 flex flex-wrap gap-2">{active ? <><button disabled={readOnly || hasUnsaved} onClick={() => onTransition("submit")} className="inline-flex items-center gap-1 rounded-lg bg-[var(--primary)] px-3 py-2 text-sm text-[var(--primary-foreground)] disabled:opacity-50"><Send size={15} />Submit</button><button disabled={readOnly} onClick={() => onTransition("abandon")} className="inline-flex items-center gap-1 rounded-lg border border-[var(--border)] px-3 py-2 text-sm"><XCircle size={15} />Abandon</button>{hasUnsaved ? <span className="self-center text-xs text-[var(--muted-foreground)]">Save every changed answer before submitting.</span> : null}</> : null}{view.attempt.state === "submitted" ? <button disabled={readOnly} onClick={() => onTransition("grade")} className="inline-flex items-center gap-1 rounded-lg bg-[var(--primary)] px-3 py-2 text-sm text-[var(--primary-foreground)]"><ClipboardCheck size={15} />Grade</button> : null}</div>
    {resultView?.attempt.state === "graded" ? <div className="mt-4 rounded-lg bg-[var(--muted)] p-3 text-sm"><p>Results are server-authoritative. Score: {formatPracticeScore(resultView.attempt.score) ?? "available"}.</p>{hasMisses ? <button type="button" disabled={readOnly} onClick={onReviewMisses} className="mt-3 rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm disabled:opacity-50">Review misses as Flashcards</button> : <p className="mt-2 text-[var(--muted-foreground)]">No missed answers need a remediation deck.</p>}</div> : null}
  </div>;
}

function AttemptHistory({ attempts, onOpen, busy, hasMore, onLoadMore }: { attempts: QuizAttempt[]; onOpen: (attempt: QuizAttempt) => void; busy: boolean; hasMore: boolean; onLoadMore: () => void }) {
  return <section><h3 className="mb-2 font-medium">Attempt history</h3>{attempts.length ? <div className="space-y-1">{attempts.map((attempt) => <button key={attempt.id} disabled={busy} onClick={() => onOpen(attempt)} className="flex w-full items-center justify-between rounded-lg border border-[var(--border)] px-3 py-2 text-left text-sm hover:bg-[var(--muted)] disabled:opacity-50"><span>{attempt.state}</span><span className="text-[var(--muted-foreground)]">{formatPracticeScore(attempt.score) ?? new Date(attempt.updated_at * 1000).toLocaleString()}</span></button>)}{hasMore ? <button type="button" disabled={busy} onClick={onLoadMore} className="w-full rounded-lg border border-[var(--border)] px-3 py-2 text-sm disabled:opacity-50">Load more attempts</button> : null}</div> : <p className="text-sm text-[var(--muted-foreground)]">No attempts yet.</p>}</section>;
}
