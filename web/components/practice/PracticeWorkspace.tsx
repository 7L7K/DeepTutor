"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Archive, CheckCircle2, ClipboardCheck, Loader2, Play, RotateCcw, Save, Send, Sparkles, XCircle } from "lucide-react";
import { useRouter } from "next/navigation";
import { CourseBar } from "@/components/courses/CourseBar";
import { useCourseShell } from "@/components/courses/CourseShell";
import { useCourses } from "@/context/CourseContext";
import { fetchAuthStatus } from "@/lib/auth";
import {
  getCourseCapabilities,
  listCourseSources,
  type CourseSource,
} from "@/lib/course-api";
import {
  abandonPracticeAttempt,
  addPracticeQuestion,
  advancePracticeViewScope,
  archivePracticeSet,
  autosavePracticeAnswer,
  canStartManualPracticeDraft,
  createPracticeGenerationPlan,
  cancelPracticeGenerationOperation,
  confirmPracticeGenerationPlan,
  consumePracticePlanHandoff,
  createPracticeAnswerSaveQueue,
  createPracticeRevision,
  createPracticeSet,
  getPracticeAttempt,
  getPracticeSet,
  getPracticeResults,
  getPracticeRevision,
  getPracticeGenerationOperation,
  getPracticeGenerationPlan,
  gradePracticeAttempt,
  hasUnsavedPracticeAnswers,
  isCurrentPracticeResponse,
  learnerSafePracticeQuestions,
  listPracticeGenerationOperations,
  listPracticeAttempts,
  listPracticeQuestions,
  listPracticeSets,
  orderedPracticeOptions,
  practiceResponseValue,
  practiceRevisionAvailability,
  practiceAttemptHistoryLabel,
  preparePracticeRemediationFlashcards,
  practiceResultsPresentation,
  practiceLibrarySets,
  practiceSetRevisionId,
  reportPracticeQuestion,
  readyPracticeRevision,
  restorePracticeSet,
  startPracticeAttempt,
  submitPracticeAttempt,
  type PracticeQuestion,
  type PracticeGenerationOperation,
  type PracticeGenerationPlan,
  type PracticeDetailState,
  type PracticeRequestScope,
  type PracticeRevision,
  type PracticeSet,
  type PracticeAnswerSaveState,
  type QuizAttempt,
  type QuizAttemptAnswer,
  type QuizAttemptResponse,
  type QuizAttemptView,
  type QuizResult,
  updatePracticeGenerationPlan,
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

type PracticeTab = "take" | "history";

type PracticeHistoryRow = {
  attempt: QuizAttempt;
  practiceSet: PracticeSet;
};

type PlanDraft = {
  title: string;
  focus: string;
  sourceIds: string[];
  objectiveIds: string;
  itemLimit: number;
  difficulty: PracticeGenerationPlan["difficulty"];
  timingMode: PracticeGenerationPlan["timing_mode"];
};

const emptyPlanDraft: PlanDraft = {
  title: "",
  focus: "",
  sourceIds: [],
  objectiveIds: "",
  itemLimit: 5,
  difficulty: "mixed",
  timingMode: "untimed",
};

const emptyQuestion: QuestionDraft = {
  prompt: "",
  answer: "",
  explanation: "",
  objectiveIds: "",
};

function automaticPracticeTitle(focus: string, courseTitle: string): string {
  const normalized = focus.replace(/\s+/g, " ").trim();
  if (!normalized) return `${courseTitle} practice`;
  const shortened = normalized.length > 72
    ? `${normalized.slice(0, 69).trimEnd()}…`
    : normalized;
  return `Practice: ${shortened}`;
}

function practiceDifficultyLabel(value: PlanDraft["difficulty"]): string {
  if (value === "foundation") return "Foundation";
  if (value === "challenge") return "Challenge";
  return "Mixed";
}

function practiceTimingLabel(value: PlanDraft["timingMode"]): string {
  return value === "untimed" ? "Untimed" : "Timed";
}

function friendlySourceName(displayName: string): string {
  const stem = displayName.replace(/\.[^/.]+$/, "").replace(/[-_]+/g, " ").trim();
  return stem ? stem.replace(/\b\w/g, (character) => character.toUpperCase()) : displayName;
}

function practiceAttemptStatus(attempt: QuizAttempt): string {
  if (attempt.state === "in_progress") return "In progress";
  if (attempt.state === "submitted") return "Ready to grade";
  if (attempt.state === "abandoned") return "Abandoned";
  if (attempt.state === "archived") return "Archived";
  return practiceAttemptHistoryLabel(attempt) ?? "Completed";
}

function practiceHistoryRows(rows: PracticeHistoryRow[]): PracticeHistoryRow[] {
  return [...rows].sort((left, right) => right.attempt.updated_at - left.attempt.updated_at);
}

const ALL_QUESTIONS_WITHDRAWN_MESSAGE =
  "All questions in this revision were withdrawn after review.";
const QUESTION_WITHDRAWN_LABEL = "Withdrawn after review";
const REPORTED_AND_WITHDRAWN_LABEL = "Reported and withdrawn";
const WITHDRAWN_ATTEMPT_MESSAGE =
  "This attempt contains a question withdrawn after review. Answers and submission are locked; leave this attempt to start a trustworthy replacement.";
const WITHDRAWN_SUBMITTED_MESSAGE =
  "A question was withdrawn after review, so this attempt cannot be graded.";
const SUBMITTED_MESSAGE = "Grade the quiz to see your results and explanations.";

/** Private Course Practice workspace with durable manual and grounded quiz flows. */
export default function PracticeWorkspace({
  initialPracticeSetId = null,
  initialAttemptId = null,
}: {
  initialPracticeSetId?: string | null;
  initialAttemptId?: string | null;
}) {
  const router = useRouter();
  const { activeCourse: sharedActiveCourse, refresh: refreshCourses } = useCourses();
  const courseShell = useCourseShell();
  const activeCourse = courseShell?.course ?? sharedActiveCourse;
  const [identity, setIdentity] = useState<string | null>(null);
  const [sets, setSets] = useState<PracticeSet[]>([]);
  const [selectedSetId, setSelectedSetId] = useState<string | null>(null);
  const [revision, setRevision] = useState<PracticeRevision | null>(null);
  const [detailState, setDetailState] = useState<PracticeDetailState>("idle");
  const [questions, setQuestions] = useState<PracticeQuestion[]>([]);
  const [attempts, setAttempts] = useState<QuizAttempt[]>([]);
  const [attemptsHaveMore, setAttemptsHaveMore] = useState(false);
  const [attemptView, setAttemptView] = useState<QuizAttemptView | null>(null);
  const [resultView, setResultView] = useState<QuizResult | null>(null);
  const [draft, setDraft] = useState<QuestionDraft>(emptyQuestion);
  const [manualTitle, setManualTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<PracticeTab>("take");
  const [courseSources, setCourseSources] = useState<CourseSource[]>([]);
  const [generationEnabled, setGenerationEnabled] = useState(false);
  const [courseLoading, setCourseLoading] = useState(false);
  const [loadedCourseId, setLoadedCourseId] = useState<string | null>(null);
  const [plan, setPlan] = useState<PracticeGenerationPlan | null>(null);
  const [planDraft, setPlanDraft] = useState<PlanDraft>(emptyPlanDraft);
  const [planOpen, setPlanOpen] = useState(false);
  const [generationOperation, setGenerationOperation] =
    useState<PracticeGenerationOperation | null>(null);
  const [generationOperations, setGenerationOperations] =
    useState<PracticeGenerationOperation[]>([]);
  const [historyRows, setHistoryRows] = useState<PracticeHistoryRow[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyLoadedCourseId, setHistoryLoadedCourseId] = useState<string | null>(null);
  const launchedOperationIdRef = useRef<string | null>(null);
  const reviewPlanButtonRef = useRef<HTMLButtonElement | null>(null);
  const planDialogRef = useRef<HTMLElement | null>(null);
  const epochRef = useRef(0);
  const scopeRef = useRef<PracticeRequestScope>({ identity: null, courseId: null, epoch: 0, viewEpoch: 0 });

  const selectedSet = useMemo(
    () => sets.find((item) => item.id === selectedSetId) ?? null,
    [sets, selectedSetId],
  );
  const librarySets = useMemo(
    () => practiceLibrarySets(sets, generationOperations),
    [generationOperations, sets],
  );
  const activeLibrarySets = useMemo(
    () => librarySets
      .filter((item) => item.state !== "archived" && Boolean(item.current_revision_id))
      .sort((left, right) => Number(Boolean(right.current_revision_id)) - Number(Boolean(left.current_revision_id))),
    [librarySets],
  );
  const draftLibrarySets = useMemo(
    () => librarySets.filter((item) => item.state !== "archived" && !item.current_revision_id),
    [librarySets],
  );
  const archivedLibrarySets = useMemo(
    () => librarySets.filter((item) => item.state === "archived"),
    [librarySets],
  );
  const sourceNames = useMemo(
    () => new Map(courseSources.map((source) => [source.id, source.display_name])),
    [courseSources],
  );
  const courseId = activeCourse?.id ?? null;
  const scopeReady = Boolean(
    identity &&
      courseId &&
      scopeRef.current.identity === identity &&
      scopeRef.current.courseId === courseId,
  );
  const courseReady = Boolean(
    identity && courseId && loadedCourseId === courseId && scopeReady,
  );
  const courseWritable = activeCourse?.state === "active" && courseReady;
  const readOnly = !courseWritable || selectedSet?.state === "archived";
  const revisionAvailability = useMemo(
    () => practiceRevisionAvailability(questions),
    [questions],
  );
  const sortedHistoryRows = useMemo(() => practiceHistoryRows(historyRows), [historyRows]);

  const invalidate = useCallback((nextIdentity: string | null, nextCourseId: string | null) => {
    const scope = { identity: nextIdentity, courseId: nextCourseId, epoch: ++epochRef.current, viewEpoch: 0 };
    scopeRef.current = scope;
    setSets([]);
    setSelectedSetId(null);
    setRevision(null);
    setDetailState("idle");
    setQuestions([]);
    setAttempts([]);
    setAttemptsHaveMore(false);
    setAttemptView(null);
    setResultView(null);
    setDraft(emptyQuestion);
    setManualTitle("");
    setBusy(false);
    setStatus(null);
    setError(null);
    setActiveTab("take");
    setCourseSources([]);
    setGenerationEnabled(false);
    setCourseLoading(false);
    setLoadedCourseId(null);
    setPlan(null);
    setPlanDraft(emptyPlanDraft);
    setPlanOpen(false);
    setGenerationOperation(null);
    setGenerationOperations([]);
    setHistoryRows([]);
    setHistoryLoadedCourseId(null);
    setHistoryLoading(false);
    launchedOperationIdRef.current = null;
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

  const loadSetDetail = useCallback(async (scope: PracticeRequestScope, practiceSet: PracticeSet, revisionId: string | null, requestedAttemptId: string | null = null) => {
    const [history, initialRevision, requestedView] = await Promise.all([
      listPracticeAttempts(practiceSet.course_id, practiceSet.id),
      revisionId ? getPracticeRevision(practiceSet.course_id, practiceSet.id, revisionId) : Promise.resolve(null),
      requestedAttemptId
        ? getPracticeAttempt(practiceSet.course_id, practiceSet.id, requestedAttemptId)
        : Promise.resolve(null),
    ]);
    if (!current(scope)) return;
    setAttempts(history);
    setAttemptsHaveMore(history.length === 50);
    const targetRevisionId = requestedView?.attempt.practice_set_revision_id ?? revisionId;
    const loadedRevision = targetRevisionId === initialRevision?.id
      ? initialRevision
      : targetRevisionId
        ? await getPracticeRevision(practiceSet.course_id, practiceSet.id, targetRevisionId)
        : null;
    if (!current(scope)) return;
    setRevision(loadedRevision);
    if (!loadedRevision) {
      setQuestions([]);
      return;
    }
    const loadedQuestions = await listPracticeQuestions(practiceSet.course_id, practiceSet.id, loadedRevision.id);
    if (!current(scope)) return;
    setQuestions(loadedQuestions);
    const selectedAttempt = requestedView?.attempt ?? history.find(
      (attempt) =>
        attempt.state === "in_progress" &&
        attempt.practice_set_revision_id === loadedRevision.id,
    ) ?? null;
    if (!selectedAttempt) {
      setAttemptView(null);
      setResultView(null);
      return;
    }
    const resumed = requestedView ?? await getPracticeAttempt(
      practiceSet.course_id, practiceSet.id, selectedAttempt.id,
    );
    if (!current(scope)) return;
    setAttemptView(resumed);
    if (resumed.attempt.state === "graded") {
      setResultView(await getPracticeResults(practiceSet.course_id, practiceSet.id, resumed.attempt.id));
    } else {
      setResultView(null);
    }
  }, [current]);

  const replaceHistoryForSet = useCallback((practiceSet: PracticeSet, nextAttempts: QuizAttempt[]) => {
    setHistoryRows((previous) => practiceHistoryRows([
      ...previous.filter((row) => row.practiceSet.id !== practiceSet.id),
      ...nextAttempts.map((attempt) => ({ attempt, practiceSet })),
    ]));
  }, []);

  const loadHistory = useCallback(async () => {
    if (!activeCourse || !courseReady || historyLoadedCourseId === activeCourse.id) return;
    const scope = scopeRef.current;
    setHistoryLoading(true);
    setError(null);
    try {
      const rows = (await Promise.all(
        sets.map(async (practiceSet) => {
          const attempts = await listPracticeAttempts(activeCourse.id, practiceSet.id);
          return attempts.map((attempt) => ({ attempt, practiceSet }));
        }),
      )).flat();
      if (!current(scope)) return;
      setHistoryRows(practiceHistoryRows(rows));
      setHistoryLoadedCourseId(activeCourse.id);
    } catch (cause) {
      if (current(scope)) setError(errorText(cause));
    } finally {
      if (current(scope)) setHistoryLoading(false);
    }
  }, [activeCourse, courseReady, current, historyLoadedCourseId, sets]);

  const handleTabChange = useCallback((tab: PracticeTab) => {
    setActiveTab(tab);
    if (tab === "history") void loadHistory();
  }, [loadHistory]);

  const startNewPractice = useCallback(() => {
    setActiveTab("take");
    setPlan(null);
    setPlanOpen(false);
    setPlanDraft({
      ...emptyPlanDraft,
      sourceIds: courseSources.map((source) => source.id),
    });
    setStatus(null);
    setError(null);
    window.requestAnimationFrame(() => {
      document.querySelector<HTMLTextAreaElement>('textarea[aria-label="Practice topic"]')?.focus();
    });
  }, [courseSources]);

  const loadCourse = useCallback(async (scope: PracticeRequestScope) => {
    if (!scope.courseId) return;
    const [listed, sources, capabilities, operations] = await Promise.all([
      listPracticeSets(scope.courseId),
      listCourseSources(scope.courseId).catch(() => [] as CourseSource[]),
      getCourseCapabilities().catch(() => null),
      listPracticeGenerationOperations(scope.courseId).catch(
        () => [] as PracticeGenerationOperation[],
      ),
    ]);
    if (!current(scope)) return;
    setSets(listed);
    const readySources = sources.filter((source) => source.state === "ready");
    setCourseSources(readySources);
    setGenerationEnabled(Boolean(capabilities?.practice_generation));
    const activeOperation =
      operations.find((operation) =>
        ["queued", "running"].includes(operation.state),
      ) ?? null;
    const latestFailure =
      operations.find((operation) => operation.state === "failed") ?? null;
    const visibleOperation = activeOperation ?? latestFailure;
    setGenerationOperation(visibleOperation);
    setGenerationOperations(operations);
    if (activeOperation) setActiveTab("take");
    setPlanDraft((previous) => ({
      ...previous,
      sourceIds: previous.sourceIds.length
        ? previous.sourceIds.filter((sourceId) =>
            readySources.some((source) => source.id === sourceId),
          )
        : readySources.map((source) => source.id),
    }));
    const generated = activeOperation
      ? listed.find((item) => item.id === activeOperation.practice_set_id)
      : null;
    const failedSetIds = new Set(
      operations
        .filter((operation) => operation.state === "failed")
        .map((operation) => operation.practice_set_id),
    );
    const requested = initialPracticeSetId
      ? listed.find((item) => item.id === initialPracticeSetId) ?? null
      : null;
    const usable = initialPracticeSetId
      ? requested
      : (generated?.state !== "archived" ? generated : null) ??
        listed.find((set) => set.state === "draft" && practiceSetRevisionId(set)) ??
        listed.find(
          (set) => set.state === "draft" && !failedSetIds.has(set.id),
        ) ??
        null;
    setSelectedSetId(usable?.id ?? null);
    setDetailState(usable ? "loading" : "idle");
    if (initialAttemptId && !usable) {
      setError("Practice attempt could not be loaded.");
    }
    if (usable) {
      const detailScope = advanceView();
      try {
        await loadSetDetail(
          detailScope,
          usable,
          practiceSetRevisionId(usable),
          initialAttemptId,
        );
        if (current(detailScope)) setDetailState("loaded");
      } catch (cause) {
        if (current(detailScope)) {
          setDetailState("error");
          setError(errorText(cause));
        }
      }
    }
    if (
      scopeRef.current.epoch === scope.epoch &&
      scopeRef.current.identity === scope.identity &&
      scopeRef.current.courseId === scope.courseId
    ) {
      setLoadedCourseId(scope.courseId);
      setCourseLoading(false);
    }
  }, [advanceView, current, initialAttemptId, initialPracticeSetId, loadSetDetail]);

  useEffect(() => {
    let alive = true;
    const update = async () => {
      const auth = await fetchAuthStatus();
      if (!alive) return;
      const nextIdentity = auth?.authenticated ? auth.user_id ?? null : null;
      setIdentity(nextIdentity);
      const scope = invalidate(nextIdentity, courseId);
      if (nextIdentity && courseId) {
        setCourseLoading(true);
        try {
          await loadCourse(scope);
        } catch (cause) {
          if (current(scope)) setError(errorText(cause));
        } finally {
          if (current(scope)) setCourseLoading(false);
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
          setCourseLoading(true);
          try { await loadCourse(nextScope); } catch (cause) { if (current(nextScope)) setError(errorText(cause)); }
          finally { if (current(nextScope)) setCourseLoading(false); }
        }
      });
      void scope;
    };
    window.addEventListener("dt:auth-changed", onAuthChanged);
    return () => window.removeEventListener("dt:auth-changed", onAuthChanged);
  }, [activeCourse?.id, current, invalidate, loadCourse]);

  useEffect(() => {
    if (!identity || !activeCourse || !scopeReady) return;
    const planId = consumePracticePlanHandoff(identity, activeCourse.id);
    if (!planId) return;
    const scope = scopeRef.current;
    setBusy(true);
    setError(null);
    void getPracticeGenerationPlan(activeCourse.id, planId)
      .then((loaded) => {
        if (!current(scope)) return;
        setPlan(loaded);
        setPlanDraft({
          title: loaded.title,
          focus: loaded.focus,
          sourceIds: loaded.source_snapshot.map((item) => item.source_id),
          objectiveIds: loaded.objective_ids.join(", "),
          itemLimit: loaded.item_limit,
          difficulty: loaded.difficulty,
          timingMode: loaded.timing_mode,
        });
        setActiveTab("take");
        setPlanOpen(true);
      })
      .catch((cause) => {
        if (current(scope)) setError(errorText(cause));
      })
      .finally(() => {
        if (current(scope)) setBusy(false);
      });
  }, [activeCourse, current, identity, scopeReady]);

  const openPlanReview = useCallback(async () => {
    if (
      !activeCourse ||
      !courseWritable ||
      !planDraft.focus.trim() ||
      !planDraft.sourceIds.length
    ) {
      return;
    }
    const scope = scopeRef.current;
    setBusy(true);
    setError(null);
    try {
      const title = planDraft.title.trim() || automaticPracticeTitle(planDraft.focus, activeCourse.title);
      const body = {
        title,
        focus: planDraft.focus.trim(),
        source_ids: planDraft.sourceIds,
        objective_ids: planDraft.objectiveIds
          .split(",")
          .map((value) => value.trim())
          .filter(Boolean),
        expected_course_write_epoch: activeCourse.write_epoch,
        item_limit: planDraft.itemLimit,
        difficulty: planDraft.difficulty,
        timing_mode: planDraft.timingMode,
      };
      const created =
        plan?.state === "draft"
          ? await updatePracticeGenerationPlan(activeCourse.id, plan, body)
          : await createPracticeGenerationPlan(
              activeCourse.id,
              body,
              newIdempotencyKey(),
            );
      if (!current(scope)) return;
      setPlanDraft((previous) => ({ ...previous, title }));
      setPlan(created);
      setPlanOpen(true);
      setStatus("Review the quiz plan before creating questions.");
    } catch (cause) {
      if (current(scope)) setError(errorText(cause));
    } finally {
      if (current(scope)) setBusy(false);
    }
  }, [activeCourse, courseWritable, current, plan, planDraft]);

  const closePlanReview = useCallback(() => {
    setPlanOpen(false);
    window.requestAnimationFrame(() => reviewPlanButtonRef.current?.focus());
  }, []);

  const handlePlanDialogKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLDivElement>) => {
      if (event.key === "Escape" && !busy) {
        event.preventDefault();
        closePlanReview();
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = Array.from(
        planDialogRef.current?.querySelectorAll<HTMLElement>(
          'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ) ?? [],
      );
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    },
    [busy, closePlanReview],
  );

  const confirmPlan = useCallback(async () => {
    if (!activeCourse || !plan || plan.state !== "draft" || !courseWritable) {
      return;
    }
    const scope = scopeRef.current;
    setBusy(true);
    setError(null);
    try {
      const confirmation = await confirmPracticeGenerationPlan(
        activeCourse.id,
        plan,
        newIdempotencyKey(),
      );
      if (!current(scope)) return;
      setPlan(confirmation.plan);
      setGenerationOperation(confirmation.request.operation);
      setGenerationOperations((previous) => [
        confirmation.request.operation,
        ...previous.filter((item) => item.id !== confirmation.request.operation.id),
      ]);
      setPlanOpen(false);
      setStatus("Creating your quiz from the selected Course materials.");
    } catch (cause) {
      if (current(scope)) setError(errorText(cause));
    } finally {
      if (current(scope)) setBusy(false);
    }
  }, [activeCourse, courseWritable, current, plan]);

  const launchGeneratedQuiz = useCallback(
    async (operation: PracticeGenerationOperation) => {
      if (
        !activeCourse ||
        launchedOperationIdRef.current === operation.id
      ) {
        return;
      }
      launchedOperationIdRef.current = operation.id;
      const scope = advanceView();
      setBusy(true);
      setError(null);
      try {
        const generatedSet = await getPracticeSet(
          activeCourse.id,
          operation.practice_set_id,
        );
        const generatedRevision = await getPracticeRevision(
          activeCourse.id,
          generatedSet.id,
          operation.practice_set_revision_id,
        );
        const generatedQuestions = await listPracticeQuestions(
          activeCourse.id,
          generatedSet.id,
          generatedRevision.id,
        );
        if (!current(scope)) return;
        const listed = await listPracticeSets(activeCourse.id);
        if (!current(scope)) return;
        setSets(listed);
        setSelectedSetId(generatedSet.id);
        setRevision(generatedRevision);
        setDetailState("loaded");
        setQuestions(generatedQuestions);
        setAttemptView(null);
        setResultView(null);
        setGenerationOperation(operation);
        setGenerationOperations((previous) => [
          operation,
          ...previous.filter((item) => item.id !== operation.id),
        ]);
        setActiveTab("take");
        setHistoryLoadedCourseId(null);
        setStatus("Your quiz is ready. Start it when you are ready.");
        router.replace(`/classes/${encodeURIComponent(activeCourse.id)}/practice`);
      } catch (cause) {
        launchedOperationIdRef.current = null;
        if (current(scope)) setError(errorText(cause));
      } finally {
        if (current(scope)) setBusy(false);
      }
    },
    [activeCourse, advanceView, current, router],
  );

  const cancelGeneration = useCallback(async () => {
    if (!activeCourse || !generationOperation) return;
    const scope = scopeRef.current;
    setBusy(true);
    setError(null);
    try {
      const cancelled = await cancelPracticeGenerationOperation(
        activeCourse.id,
        generationOperation.id,
      );
      if (!current(scope)) return;
      setGenerationOperation(cancelled);
      setGenerationOperations((previous) => [
        cancelled,
        ...previous.filter((item) => item.id !== cancelled.id),
      ]);
      setStatus("Quiz creation stopped. No quiz was published.");
    } catch (cause) {
      if (current(scope)) setError(errorText(cause));
    } finally {
      if (current(scope)) setBusy(false);
    }
  }, [activeCourse, current, generationOperation]);

  useEffect(() => {
    if (
      !activeCourse ||
      !generationOperation ||
      !["queued", "running"].includes(generationOperation.state)
    ) {
      return;
    }
    let cancelled = false;
    const poll = async () => {
      try {
        const next = await getPracticeGenerationOperation(
          activeCourse.id,
          generationOperation.id,
        );
        if (cancelled) return;
        setGenerationOperation(next);
        setGenerationOperations((previous) => [
          next,
          ...previous.filter((item) => item.id !== next.id),
        ]);
        if (next.state === "completed") {
          await launchGeneratedQuiz(next);
        } else if (next.state === "failed") {
          setError(
            "Quiz generation did not finish. No quiz was published and your existing Practice was not changed.",
          );
          setActiveTab("take");
        }
      } catch (cause) {
        if (!cancelled) setError(errorText(cause));
      }
    };
    const timer = window.setInterval(() => void poll(), 800);
    void poll();
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [activeCourse, generationOperation, launchGeneratedQuiz]);

  useEffect(() => {
    if (
      !generationOperation ||
      generationOperation.state !== "completed" ||
      launchedOperationIdRef.current === generationOperation.id
    ) {
      return;
    }
    void launchGeneratedQuiz(generationOperation);
  }, [generationOperation, launchGeneratedQuiz]);

  const selectSet = useCallback(async (practiceSet: PracticeSet) => {
    const scope = advanceView();
    setSelectedSetId(practiceSet.id);
    // Fail closed while the next set detail is loading: never render or edit
    // the prior set/revision beneath the newly selected set title.
    setRevision(null);
    setDetailState("loading");
    setQuestions([]);
    setAttempts([]);
    setAttemptsHaveMore(false);
    setAttemptView(null);
    setResultView(null);
    setDraft(emptyQuestion);
    setStatus(null);
    setError(null);
    try {
      await loadSetDetail(scope, practiceSet, practiceSetRevisionId(practiceSet));
      if (current(scope)) setDetailState("loaded");
    } catch (cause) {
      if (current(scope)) {
        setDetailState("error");
        setError(errorText(cause));
      }
    }
  }, [advanceView, current, loadSetDetail]);

  const retrySetDetail = useCallback(async () => {
    if (!activeCourse || !selectedSet) return;
    const scope = advanceView();
    setDetailState("loading");
    setRevision(null);
    setQuestions([]);
    setAttempts([]);
    setAttemptsHaveMore(false);
    setAttemptView(null);
    setResultView(null);
    setError(null);
    try {
      const updatedSet = await getPracticeSet(activeCourse.id, selectedSet.id);
      if (!current(scope)) return;
      setSets((previous) => previous.map((item) =>
        item.id === updatedSet.id ? updatedSet : item,
      ));
      await loadSetDetail(scope, updatedSet, practiceSetRevisionId(updatedSet));
      if (current(scope)) setDetailState("loaded");
    } catch (cause) {
      if (current(scope)) {
        setDetailState("error");
        setError(errorText(cause));
      }
    }
  }, [activeCourse, advanceView, current, loadSetDetail, selectedSet]);

  const createManualPractice = useCallback(async () => {
    if (!activeCourse || !courseWritable) return;
    const title = manualTitle.trim() || `${activeCourse.title} practice`;
    const scope = advanceView();
    setBusy(true);
    setError(null);
    setStatus(null);
    try {
      const createdSet = await createPracticeSet(
        activeCourse.id,
        title,
        activeCourse.write_epoch,
      );
      if (!current(scope)) return;
      setSets((previous) => [
        createdSet,
        ...previous.filter((item) => item.id !== createdSet.id),
      ]);
      setSelectedSetId(createdSet.id);
      setRevision(null);
      setDetailState("loaded");
      setQuestions([]);
      setAttempts([]);
      setAttemptsHaveMore(false);
      setAttemptView(null);
      setResultView(null);
      setDraft(emptyQuestion);
      setActiveTab("take");
      const createdRevision = await createPracticeRevision(
        activeCourse.id,
        createdSet.id,
        activeCourse.write_epoch,
      );
      // Re-read after the revision write so editor/archive actions keep a
      // fresh owner-scoped set receipt. Drafts publish as current only at ready.
      const updatedSet = await getPracticeSet(activeCourse.id, createdSet.id);
      if (!current(scope)) return;
      setSets((previous) => [
        updatedSet,
        ...previous.filter((item) => item.id !== updatedSet.id),
      ]);
      setSelectedSetId(updatedSet.id);
      setRevision(createdRevision);
      setDetailState("loaded");
      setQuestions([]);
      setAttempts([]);
      setAttemptsHaveMore(false);
      setAttemptView(null);
      setResultView(null);
      setDraft(emptyQuestion);
      setManualTitle("");
      setActiveTab("take");
      setHistoryLoadedCourseId(null);
      setStatus("Manual Practice draft created. Add your first question.");
    } catch (cause) {
      if (current(scope)) setError(errorText(cause));
    } finally {
      if (current(scope)) setBusy(false);
    }
  }, [activeCourse, advanceView, courseWritable, current, manualTitle]);

  const startManualDraft = useCallback(async () => {
    if (
      !activeCourse ||
      !selectedSet ||
      busy ||
      readOnly ||
      !canStartManualPracticeDraft(selectedSet, detailState)
    ) return;
    const scope = advanceView();
    setDetailState("loading");
    setBusy(true);
    setError(null);
    setStatus(null);
    try {
      const createdRevision = await createPracticeRevision(
        activeCourse.id,
        selectedSet.id,
        activeCourse.write_epoch,
      );
      const updatedSet = await getPracticeSet(activeCourse.id, selectedSet.id);
      if (!current(scope)) return;
      setSets((previous) => previous.map((item) =>
        item.id === updatedSet.id ? updatedSet : item,
      ));
      await loadSetDetail(scope, updatedSet, createdRevision.id);
      if (current(scope)) {
        setDetailState("loaded");
        setStatus("Practice draft started. Add your first question.");
      }
    } catch (cause) {
      if (current(scope)) {
        setDetailState("error");
        setError(errorText(cause));
      }
    } finally {
      if (current(scope)) setBusy(false);
    }
  }, [activeCourse, advanceView, busy, current, detailState, loadSetDetail, readOnly, selectedSet]);

  const addQuestion = useCallback(async () => {
    if (!activeCourse || !selectedSet || !revision || revision.state !== "draft" || readOnly) return;
    if (!draft.prompt.trim() || !draft.answer.trim()) return;
    const scope = scopeRef.current;
    setBusy(true); setError(null);
    try {
      const question = await addPracticeQuestion(activeCourse.id, selectedSet.id, revision.id, {
        question_type: "short_answer",
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

  const startOrResume = useCallback(async () => {
    if (!activeCourse || !selectedSet || !revision || revision.state !== "ready" || revision.id !== selectedSet.current_revision_id || readOnly) return;
    const scope = scopeRef.current;
    setBusy(true); setError(null);
    try {
      const view = await startPracticeAttempt(activeCourse.id, selectedSet, revision.id, activeCourse.write_epoch);
      if (!current(scope)) return;
      setAttemptView(view); setResultView(null); setStatus(view.attempt.state === "in_progress" ? "Quiz resumed." : "Quiz loaded.");
      router.replace(`/classes/${encodeURIComponent(activeCourse.id)}/practice/${encodeURIComponent(selectedSet.id)}/attempts/${encodeURIComponent(view.attempt.id)}`);
      const history = await listPracticeAttempts(activeCourse.id, selectedSet.id);
      if (current(scope)) {
        setAttempts(history);
        setAttemptsHaveMore(history.length === 50);
        replaceHistoryForSet(selectedSet, history);
      }
    } catch (cause) { if (current(scope)) setError(errorText(cause)); }
    finally { if (current(scope)) setBusy(false); }
  }, [activeCourse, current, readOnly, replaceHistoryForSet, revision, router, selectedSet]);

  const openHistoryAttempt = useCallback(async (row: PracticeHistoryRow) => {
    if (!activeCourse) return;
    const scope = advanceView();
    setActiveTab("take");
    setSelectedSetId(row.practiceSet.id);
    setRevision(null);
    setQuestions([]);
    setAttemptView(null);
    setResultView(null);
    setError(null);
    try {
      await loadSetDetail(
        scope,
        row.practiceSet,
        row.practiceSet.current_revision_id,
        row.attempt.id,
      );
      if (current(scope)) {
        router.replace(
          `/classes/${encodeURIComponent(activeCourse.id)}/practice/${encodeURIComponent(row.practiceSet.id)}/attempts/${encodeURIComponent(row.attempt.id)}`,
        );
      }
    } catch (cause) {
      if (current(scope)) setError(errorText(cause));
    }
  }, [activeCourse, advanceView, current, loadSetDetail, router]);

  const startHistoryRetake = useCallback(async (row: PracticeHistoryRow) => {
    if (!activeCourse || row.practiceSet.state === "archived") return;
    const scope = advanceView();
    setActiveTab("take");
    setSelectedSetId(row.practiceSet.id);
    setRevision(null);
    setQuestions([]);
    setAttemptView(null);
    setResultView(null);
    setError(null);
    setBusy(true);
    try {
      const practiceSet = await getPracticeSet(activeCourse.id, row.practiceSet.id);
      if (!practiceSet.current_revision_id) throw new Error("This Practice is not ready to retake yet.");
      const currentRevision = await getPracticeRevision(
        activeCourse.id,
        practiceSet.id,
        practiceSet.current_revision_id,
      );
      if (currentRevision.state !== "ready") throw new Error("This Practice is not ready to retake yet.");
      const view = await startPracticeAttempt(
        activeCourse.id,
        practiceSet,
        currentRevision.id,
        activeCourse.write_epoch,
      );
      const attemptQuestions = await listPracticeQuestions(
        activeCourse.id,
        practiceSet.id,
        currentRevision.id,
      );
      if (!current(scope)) return;
      setSets((previous) => previous.map((item) => item.id === practiceSet.id ? practiceSet : item));
      setRevision(currentRevision);
      setQuestions(attemptQuestions);
      setAttemptView(view);
      setResultView(null);
      const history = await listPracticeAttempts(activeCourse.id, practiceSet.id);
      if (current(scope)) {
        setAttempts(history);
        setAttemptsHaveMore(history.length === 50);
        replaceHistoryForSet(practiceSet, history);
      }
      router.replace(
        `/classes/${encodeURIComponent(activeCourse.id)}/practice/${encodeURIComponent(practiceSet.id)}/attempts/${encodeURIComponent(view.attempt.id)}`,
      );
    } catch (cause) {
      if (current(scope)) setError(errorText(cause));
    } finally {
      if (current(scope)) setBusy(false);
    }
  }, [activeCourse, advanceView, current, replaceHistoryForSet, router]);

  const saveAnswer = useCallback(async (
    answer: QuizAttemptAnswer,
    response: QuizAttemptResponse,
    idempotencyKey: string,
  ): Promise<QuizAttemptAnswer> => {
    if (!activeCourse || !selectedSet || !attemptView || attemptView.attempt.state !== "in_progress" || readOnly) {
      throw new Error("This quiz attempt is no longer writable.");
    }
    const scope = scopeRef.current;
    const saved = await autosavePracticeAnswer(
      activeCourse.id,
      selectedSet,
      attemptView.attempt,
      answer,
      response,
      idempotencyKey,
    );
    if (current(scope)) {
      setAttemptView((previous) => previous ? {
        ...previous,
        answers: previous.answers.map((item) => item.attempt_item_id === saved.attempt_item_id ? saved : item),
      } : previous);
    }
    return saved;
  }, [activeCourse, attemptView, current, readOnly, selectedSet]);

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
        replaceHistoryForSet(selectedSet, history);
      }
      if (current(scope)) setStatus(action === "submit" ? "Quiz submitted." : action === "grade" ? "Quiz graded." : "Quiz abandoned.");
    } catch (cause) { if (current(scope)) setError(errorText(cause)); }
    finally { if (current(scope)) setBusy(false); }
  }, [activeCourse, attemptView, current, readOnly, replaceHistoryForSet, selectedSet]);

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
      router.push(`/classes/${encodeURIComponent(activeCourse.id)}/review`);
    } catch (cause) {
      if (current(scope)) setError(errorText(cause));
    } finally {
      if (current(scope)) setBusy(false);
    }
  }, [activeCourse, attemptView, current, identity, router, selectedSet]);

  const reportQuestion = useCallback(async (questionId: string) => {
    if (!activeCourse || !selectedSet || !revision || !resultView) return;
    setBusy(true);
    setError(null);
    try {
      await reportPracticeQuestion(
        activeCourse.id,
        selectedSet.id,
        revision.id,
        questionId,
        "Learner reported a possible answer, citation, or wording problem.",
      );
      setStatus("Thanks. This question is queued for review; it will not be treated as invalid until reviewed.");
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setBusy(false);
    }
  }, [activeCourse, resultView, revision, selectedSet]);

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

  return (
    <div className="flex h-full min-h-0 min-w-0 flex-col overflow-x-hidden overflow-y-auto">
      {courseShell ? null : <CourseBar />}
      <main className="mx-auto min-w-0 w-full max-w-6xl space-y-5 px-5 py-6">
        {activeCourse && !courseShell ? <p className="mb-4 text-sm text-[var(--muted-foreground)]">Active Course: <strong className="font-medium text-[var(--foreground)]">{activeCourse.title}</strong></p> : null}

        {!identity ? <p className="rounded-lg border border-[var(--border)] p-4 text-sm text-[var(--muted-foreground)]">Sign in to use private Course Practice.</p> : null}
        {identity && !activeCourse ? <p className="rounded-lg border border-[var(--border)] p-4 text-sm text-[var(--muted-foreground)]">Select or create a Course above to create private Practice sets.</p> : null}
        {identity && activeCourse && (courseLoading || !courseReady) ? <div role="status" aria-live="polite" className="mb-5 flex items-center gap-2 rounded-xl border border-[var(--border)] bg-[var(--card)] p-4 text-sm text-[var(--muted-foreground)]"><Loader2 className="animate-spin" size={18} />Loading {activeCourse.title} Practice…</div> : null}
        {identity && activeCourse && courseReady ? <nav aria-label="Practice sections" role="tablist" className="flex items-center gap-5 border-b border-[var(--border)] pb-2 text-sm">
          {(["take", "history"] as PracticeTab[]).map((tab) => <button key={tab} type="button" role="tab" aria-selected={activeTab === tab} onClick={() => handleTabChange(tab)} className={`border-b-2 pb-2 font-medium transition ${activeTab === tab ? "border-[var(--primary)] text-[var(--foreground)]" : "border-transparent text-[var(--muted-foreground)] hover:text-[var(--foreground)]"}`}>{tab === "take" ? "Practice" : "History"}</button>)}
        </nav> : null}

        {activeCourse && courseReady && activeTab === "take" ? <>
          {!attemptView ? <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <h1 className="text-2xl font-semibold">Practice</h1>
              <p className="mt-1 text-sm text-[var(--muted-foreground)]">Tell me what you need help with.</p>
            </div>
            {selectedSet ? <button type="button" onClick={startNewPractice} className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm hover:bg-[var(--muted)]">New practice</button> : null}
          </div> : null}
          {generationOperation && (["queued", "running"].includes(generationOperation.state) || generationOperation.state === "failed" || generationOperation.cancelled_at) ? <section role="status" aria-live="polite" className="mb-5 rounded-xl border border-[var(--border)] bg-[var(--card)] p-4">
            <div className="flex items-center gap-2">{["queued", "running"].includes(generationOperation.state) ? <Loader2 className="animate-spin" size={18} /> : <XCircle size={18} />}<strong>{generationOperation.state === "queued" ? "Your quiz is waiting to start" : generationOperation.state === "running" ? "Creating your quiz" : "Quiz creation did not finish"}</strong></div>
            <p className="mt-2 text-sm text-[var(--muted-foreground)]">{generationOperation.cancelled_at ? "Quiz creation was stopped. No quiz was published." : generationOperation.state === "failed" ? "No quiz was published. You can try again without changing your existing Practice." : "Your Course materials are being prepared for this quiz."}</p>
            {["queued", "running"].includes(generationOperation.state) && !generationOperation.cancel_requested_at ? <button type="button" disabled={busy} onClick={() => void cancelGeneration()} className="mt-3 rounded-lg border border-[var(--border)] px-3 py-2 text-sm disabled:opacity-50">Stop creating</button> : null}
            {generationOperation.state === "failed" || generationOperation.cancelled_at ? <button type="button" onClick={startNewPractice} className="mt-3 rounded-lg bg-[var(--primary)] px-3 py-2 text-sm text-[var(--primary-foreground)]">Try again</button> : null}
          </section> : null}

          {!attemptView ? <section aria-labelledby="new-practice-title" className="mb-5 border-b border-[var(--border)] pb-6">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h2 id="new-practice-title" className="text-2xl font-semibold sm:text-3xl">What do you want to practice?</h2>
                <p className="mt-2 max-w-2xl text-sm text-[var(--muted-foreground)]">Enter a topic, chapter, or lesson.</p>
              </div>
            </div>
            {generationEnabled ? <div className="mt-5 grid gap-4">
              <label className="grid gap-2 text-sm"><span className="sr-only">What do you want to practice?</span><textarea aria-label="Practice topic" value={planDraft.focus} onChange={(event) => setPlanDraft((value) => ({ ...value, focus: event.target.value }))} placeholder="e.g. mitosis, chapter 4, or what we covered this week" className="min-h-28 rounded-xl border border-[var(--border)] bg-[var(--card)] px-4 py-4 text-base outline-none transition focus:border-[var(--primary)]" /></label>
              <details className="overflow-hidden border-y border-[var(--border)]">
                <summary className="flex cursor-pointer flex-wrap items-center gap-3 py-3 text-sm font-medium"><span>Customize quiz</span><span className="flex flex-wrap items-center gap-1.5 text-xs font-normal text-[var(--muted-foreground)]"><span className="rounded-full border border-[var(--border)] px-2 py-1">{planDraft.itemLimit} questions</span><span className="rounded-full border border-[var(--border)] px-2 py-1">{practiceDifficultyLabel(planDraft.difficulty)}</span><span className="rounded-full border border-[var(--border)] px-2 py-1">{practiceTimingLabel(planDraft.timingMode)}</span><span className="rounded-full border border-[var(--border)] px-2 py-1">{courseSources.length} source{courseSources.length === 1 ? "" : "s"}</span></span></summary>
                <div className="border-t border-[var(--border)] py-4">
                  <div className="grid gap-3 sm:grid-cols-3">
                    <label className="grid gap-1.5 text-sm"><span>Questions</span><input aria-label="Question count" type="number" min={1} max={12} value={planDraft.itemLimit} onChange={(event) => setPlanDraft((value) => ({ ...value, itemLimit: Math.max(1, Math.min(12, Number(event.target.value) || 1)) }))} className="rounded-lg border border-[var(--border)] bg-[var(--card)] px-3 py-1.5" /></label>
                    <label className="grid gap-1.5 text-sm"><span>Difficulty</span><select aria-label="Quiz difficulty" value={planDraft.difficulty} onChange={(event) => setPlanDraft((value) => ({ ...value, difficulty: event.target.value as PlanDraft["difficulty"] }))} className="rounded-lg border border-[var(--border)] bg-[var(--card)] px-3 py-1.5"><option value="foundation">Foundation</option><option value="mixed">Mixed</option><option value="challenge">Challenge</option></select></label>
                    <label className="grid gap-1.5 text-sm"><span>Timing</span><select aria-label="Quiz timing" value={planDraft.timingMode} onChange={(event) => setPlanDraft((value) => ({ ...value, timingMode: event.target.value as PlanDraft["timingMode"] }))} className="rounded-lg border border-[var(--border)] bg-[var(--card)] px-3 py-1.5"><option value="untimed">Untimed</option><option value="practice_timer">Show practice timer</option></select></label>
                  </div>
                  {courseSources.length ? <fieldset className="mt-4 rounded-lg border border-[var(--border)] p-3"><legend className="px-1 text-sm font-medium">Sources</legend><p className="mb-3 text-xs text-[var(--muted-foreground)]">Ready course materials are selected by default.</p><div className="grid gap-2 sm:grid-cols-2">{courseSources.map((source) => <label key={source.id} className="flex items-center gap-2 text-sm"><input type="checkbox" checked={planDraft.sourceIds.includes(source.id)} onChange={(event) => setPlanDraft((value) => ({ ...value, sourceIds: event.target.checked ? [...value.sourceIds, source.id] : value.sourceIds.filter((item) => item !== source.id) }))} />{friendlySourceName(source.display_name)}</label>)}</div></fieldset> : <div className="mt-4 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm"><p>No ready Course materials are attached yet. Add one to create a grounded Practice quiz.</p><a className="mt-2 inline-block underline" href={`/classes/${encodeURIComponent(activeCourse.id)}/materials`}>Add Course materials</a></div>}
                </div>
              </details>
              <div className="flex justify-end pt-1">
                <button ref={reviewPlanButtonRef} type="button" disabled={busy || !courseWritable || !planDraft.focus.trim() || !planDraft.sourceIds.length} onClick={() => void openPlanReview()} className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-[var(--primary)] px-5 py-3 text-sm font-medium text-[var(--primary-foreground)] transition hover:brightness-105 disabled:opacity-50 sm:w-auto"><Sparkles size={16} />Quiz me</button>
              </div>
            </div> : <div className="mt-4 rounded-xl border border-[var(--border)] p-4">
              <h3 className="font-medium">Create a manual Practice quiz</h3>
              <p className="mt-1 text-sm text-[var(--muted-foreground)]">AI quiz creation is unavailable, but you can write the questions and answers yourself. No provider call will be attempted.</p>
              <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-end">
                <label className="grid min-w-0 flex-1 gap-1.5 text-sm"><span>Quiz title</span><input aria-label="Manual Practice title" value={manualTitle} disabled={!courseWritable || busy} onChange={(event) => setManualTitle(event.target.value)} placeholder={`${activeCourse.title} practice`} className="rounded-lg border border-[var(--border)] bg-[var(--card)] px-3 py-2 disabled:opacity-60" /></label>
                <button type="button" disabled={!courseWritable || busy} onClick={() => void createManualPractice()} className="inline-flex items-center justify-center gap-2 rounded-lg bg-[var(--primary)] px-4 py-2 text-sm font-medium text-[var(--primary-foreground)] disabled:opacity-50">{busy ? <Loader2 className="animate-spin" size={16} /> : <Save size={16} />}Create manual quiz</button>
              </div>
            </div>}
          </section> : null}
        </> : null}

        {activeCourse && courseReady && activeTab === "history" ? <section className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-4 sm:p-5">
          <div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="text-lg font-semibold">Practice history</h2><p className="mt-1 text-sm text-[var(--muted-foreground)]">Every attempt stays here, including unfinished and archived work.</p></div><button type="button" onClick={startNewPractice} className="rounded-lg bg-[var(--primary)] px-3 py-2 text-sm text-[var(--primary-foreground)]">New practice</button></div>
          {historyLoading ? <p role="status" className="mt-5 flex items-center gap-2 text-sm text-[var(--muted-foreground)]"><Loader2 className="animate-spin" size={16} />Loading your Practice history…</p> : sortedHistoryRows.length ? <div className="mt-5 space-y-3">{sortedHistoryRows.map((row) => { const score = practiceAttemptHistoryLabel(row.attempt); const resumable = row.attempt.state === "in_progress"; return <article key={row.attempt.id} className="rounded-xl border border-[var(--border)] p-4"><div className="flex flex-wrap items-start justify-between gap-3"><div><h3 className="font-medium">{row.practiceSet.title}</h3><p className="mt-1 text-sm text-[var(--muted-foreground)]">{practiceAttemptStatus(row.attempt)} · {new Date(row.attempt.updated_at * 1000).toLocaleString()}{score ? ` · ${score}` : ""}</p></div><div className="flex flex-wrap gap-2">{resumable ? <button type="button" disabled={busy} onClick={() => void openHistoryAttempt(row)} className="rounded-lg bg-[var(--primary)] px-3 py-2 text-sm text-[var(--primary-foreground)] disabled:opacity-50">Resume</button> : <button type="button" disabled={busy} onClick={() => void openHistoryAttempt(row)} className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm disabled:opacity-50">View results</button>}{!resumable && row.practiceSet.state !== "archived" ? <button type="button" disabled={busy} onClick={() => void startHistoryRetake(row)} className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm disabled:opacity-50">Retake</button> : null}</div></div></article>; })}</div> : <div className="mt-5 rounded-xl border border-dashed border-[var(--border)] p-6 text-sm text-[var(--muted-foreground)]">No attempts yet. Take a Practice quiz and it will appear here.</div>}
        </section> : null}

        {activeCourse && courseReady && activeTab === "take" && (selectedSet || activeLibrarySets.length || draftLibrarySets.length || archivedLibrarySets.length) ? <div className={`grid gap-5 ${attemptView || !selectedSet ? "" : "lg:grid-cols-[260px_minmax(0,1fr)]"}`}>
          {!attemptView ? <aside className="rounded-xl border border-[var(--border)] bg-[var(--card)] p-3">
            <div className="mb-3">
              <h2 className="font-medium">Recent quizzes</h2>
              <p className="mt-1 text-xs text-[var(--muted-foreground)]">Choose a quiz to take again.</p>
            </div>
            <div className="space-y-1">
              {activeLibrarySets.map((item) => <button key={item.id} onClick={() => void selectSet(item)} className={`w-full rounded-lg px-3 py-2 text-left text-sm ${item.id === selectedSetId ? "bg-[var(--accent)]" : "hover:bg-[var(--muted)]"}`}>
                <span className="block truncate font-medium">{item.title}</span><span className="text-xs text-[var(--muted-foreground)]">Ready</span>
              </button>)}
              {draftLibrarySets.length ? <div className="mt-3 border-t border-[var(--border)] pt-3"><p className="px-2 text-xs font-medium text-[var(--muted-foreground)]">Continue creating</p>{draftLibrarySets.map((item) => <button key={item.id} onClick={() => void selectSet(item)} className={`mt-1 w-full rounded-lg px-3 py-2 text-left text-sm ${item.id === selectedSetId ? "bg-[var(--accent)]" : "hover:bg-[var(--muted)]"}`}><span className="block truncate font-medium">{item.title}</span><span className="text-xs text-[var(--muted-foreground)]">Draft</span></button>)}</div> : null}
              {archivedLibrarySets.length ? <details className="mt-3 border-t border-[var(--border)] pt-3"><summary className="cursor-pointer text-xs font-medium text-[var(--muted-foreground)]">Archived quizzes ({archivedLibrarySets.length})</summary><div className="mt-2 space-y-1">{archivedLibrarySets.map((item) => <button key={item.id} onClick={() => void selectSet(item)} className={`w-full rounded-lg px-3 py-2 text-left text-sm ${item.id === selectedSetId ? "bg-[var(--accent)]" : "hover:bg-[var(--muted)]"}`}><span className="block truncate font-medium">{item.title}</span><span className="text-xs text-[var(--muted-foreground)]">Archived</span></button>)}</div></details> : null}
            </div>
          </aside> : null}

          {selectedSet ? <section className="min-w-0 rounded-xl border border-[var(--border)] bg-[var(--card)] p-4 sm:p-5">
            <>
              <div className="mb-5 flex flex-wrap items-center justify-between gap-3 border-b border-[var(--border)] pb-4">
                <div><p className="mb-1 text-xs font-medium uppercase tracking-wide text-[var(--muted-foreground)]">{activeCourse.title} / Practice{resultView ? " / Results" : ""}</p><h2 className="text-lg font-semibold">{selectedSet.title}</h2><p className="text-sm text-[var(--muted-foreground)]">{selectedSet.state === "archived" ? "Archived — read-only history" : revision?.state === "ready" ? revisionAvailability.status : "Draft revision"}</p></div>
                {!attemptView ? <button disabled={busy || !activeCourse} onClick={() => void archiveOrRestore()} className="inline-flex items-center gap-1 rounded-lg border border-[var(--border)] px-3 py-2 text-sm disabled:opacity-50">{selectedSet.state === "archived" ? <RotateCcw size={15} /> : <Archive size={15} />}{selectedSet.state === "archived" ? "Restore" : "Archive"}</button> : null}
              </div>
              {!attemptView && detailState === "loading" ? <div role="status" className="mb-6 flex items-center gap-2 rounded-lg border border-[var(--border)] p-4 text-sm text-[var(--muted-foreground)]"><Loader2 className="animate-spin" size={16} />Opening this quiz…</div> : null}
              {!attemptView && detailState === "error" ? <div className="mb-6 rounded-lg border border-[var(--border)] p-4">
                <h3 className="font-medium">This quiz could not be opened</h3>
                <p className="mt-1 text-sm text-[var(--muted-foreground)]">Its saved revision was not changed. Retry the detail request before editing.</p>
                <button type="button" onClick={() => void retrySetDetail()} className="mt-3 rounded-lg border border-[var(--border)] px-3 py-2 text-sm">Retry opening quiz</button>
              </div> : null}
              {!attemptView && !readOnly && canStartManualPracticeDraft(selectedSet, detailState) ? <div className="mb-6 rounded-lg border border-[var(--border)] p-4">
                <h3 className="font-medium">Start this draft</h3>
                <p className="mt-1 text-sm text-[var(--muted-foreground)]">This quiz exists, but its editable draft has not started yet. Starting it is safe to retry.</p>
                <button type="button" disabled={busy} onClick={() => void startManualDraft()} className="mt-3 inline-flex items-center gap-1 rounded-lg bg-[var(--primary)] px-3 py-2 text-sm text-[var(--primary-foreground)] disabled:opacity-50">{busy ? <Loader2 className="animate-spin" size={15} /> : <Save size={15} />}Start draft</button>
              </div> : null}
              {!attemptView && revision?.state === "draft" && !readOnly ? <div className="mb-6 rounded-lg border border-[var(--border)] p-4">
                <h3 className="mb-1 font-medium">Continue creating</h3>
                <p className="mb-3 text-sm text-[var(--muted-foreground)]">This draft is not ready to take yet. Add at least one question, then mark it ready.</p>
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
              {!attemptView && revision?.state === "ready" && !readOnly ? <div className="mb-5 flex flex-wrap items-center gap-2">{revision.id === selectedSet.current_revision_id ? revisionAvailability.canStart ? <button disabled={busy} onClick={() => void startOrResume()} className="inline-flex items-center gap-1 rounded-lg bg-[var(--primary)] px-3 py-2 text-sm text-[var(--primary-foreground)]"><Play size={15} />{attempts.some((attempt) => attempt.state === "in_progress") ? "Resume" : "Start quiz"}</button> : <span className="text-sm text-[var(--muted-foreground)]">{ALL_QUESTIONS_WITHDRAWN_MESSAGE}</span> : <span className="self-center text-sm text-[var(--muted-foreground)]">Historical revision — attempts are read-only.</span>}</div> : null}
              {!attemptView && revision?.state === "draft" && questions.length ? <ol className="mb-6 space-y-3">{questions.map((question) => <li key={question.id} className="rounded-lg border border-[var(--border)] p-3"><span className="mr-2 text-xs text-[var(--muted-foreground)]">{question.ordinal}.</span>{question.prompt}{question.content_quality === "invalidated" ? <p className="mt-2 text-xs font-medium text-amber-600">{QUESTION_WITHDRAWN_LABEL}</p> : <p className="mt-2 text-xs text-[var(--muted-foreground)]">Answer: {practiceCorrectAnswer(question)}</p>}</li>)}</ol> : null}
              {attemptView ? <AttemptRunner key={attemptView.attempt.id} view={attemptView} questions={questions} sourceNames={sourceNames} readOnly={readOnly || busy} withdrawn={Boolean(attemptView.content_quality?.invalidated_question_ids?.length)} onSave={saveAnswer} onTransition={(action) => void transitionAttempt(action)} onReviewMisses={() => void reviewMissesAsFlashcards()} onStartAgain={() => void startOrResume()} onClose={() => { setAttemptView(null); setResultView(null); router.replace(`/classes/${encodeURIComponent(activeCourse.id)}/practice`); }} onReportQuestion={reportQuestion} resultView={resultView} /> : null}
            </>
          </section> : null}
        </div> : null}
        {status ? <p role="status" className="mt-4 text-sm text-emerald-600">{status}</p> : null}
        {error ? <p role="alert" className="mt-4 text-sm text-red-600">{error}</p> : null}
        {planOpen && plan && activeCourse ? <div role="dialog" aria-modal="true" aria-labelledby="quiz-plan-title" onKeyDown={handlePlanDialogKeyDown} className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <section ref={planDialogRef} className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-2xl border border-[var(--border)] bg-[var(--background)] p-6 shadow-2xl">
            <div className="flex items-start justify-between gap-4"><div><h2 id="quiz-plan-title" className="text-xl font-semibold">Ready to create your quiz?</h2><p className="mt-1 text-sm text-[var(--muted-foreground)]">Review this summary. Choose Keep editing to make changes. Questions are generated only after you confirm.</p></div><button type="button" autoFocus aria-label="Close quiz plan" onClick={closePlanReview} className="rounded-lg p-2 hover:bg-[var(--muted)]"><XCircle size={20} /></button></div>
            <dl className="mt-5 grid gap-3 rounded-xl border border-[var(--border)] p-4 text-sm sm:grid-cols-2"><div><dt className="text-[var(--muted-foreground)]">Course</dt><dd className="font-medium">{activeCourse.title}</dd></div><div><dt className="text-[var(--muted-foreground)]">Destination</dt><dd className="font-medium">Private Practice library</dd></div><div><dt className="text-[var(--muted-foreground)]">Quiz</dt><dd className="font-medium">{planDraft.title}</dd></div><div><dt className="text-[var(--muted-foreground)]">Questions</dt><dd className="font-medium">{planDraft.itemLimit}</dd></div><div className="sm:col-span-2"><dt className="text-[var(--muted-foreground)]">What it covers</dt><dd className="font-medium">{planDraft.focus}</dd></div><div><dt className="text-[var(--muted-foreground)]">Difficulty</dt><dd className="font-medium capitalize">{planDraft.difficulty}</dd></div><div><dt className="text-[var(--muted-foreground)]">Timing</dt><dd className="font-medium">{planDraft.timingMode === "untimed" ? "Untimed" : "Practice timer"}</dd></div><div><dt className="text-[var(--muted-foreground)]">Course materials</dt><dd className="font-medium">{planDraft.sourceIds.length} selected</dd></div><div><dt className="text-[var(--muted-foreground)]">Creation</dt><dd className="font-medium">AI starts only after confirmation</dd></div></dl>
            <div className="mt-5 flex flex-wrap justify-end gap-2"><button type="button" disabled={busy} onClick={closePlanReview} className="rounded-lg border border-[var(--border)] px-4 py-2 text-sm">Keep editing</button><button type="button" disabled={busy} onClick={() => void confirmPlan()} className="inline-flex items-center gap-2 rounded-lg bg-[var(--primary)] px-4 py-2 text-sm text-[var(--primary-foreground)] disabled:opacity-50">{busy ? <Loader2 className="animate-spin" size={16} /> : <Sparkles size={16} />}Create quiz</button></div>
          </section>
        </div> : null}
      </main>
    </div>
  );
}

function AttemptRunner({ view, questions, sourceNames, readOnly, withdrawn, onSave, onTransition, onReviewMisses, onStartAgain, onClose, onReportQuestion, resultView }: {
  view: QuizAttemptView; questions: PracticeQuestion[]; sourceNames: Map<string, string>; readOnly: boolean; withdrawn: boolean; onSave: (answer: QuizAttemptAnswer, response: QuizAttemptResponse, idempotencyKey: string) => Promise<QuizAttemptAnswer>; onTransition: (action: "submit" | "abandon" | "grade") => void; onReviewMisses: () => void; onStartAgain: () => void; onClose: () => void; onReportQuestion: (questionId: string) => Promise<void>; resultView: QuizResult | null;
}) {
  const byId = useMemo(() => new Map((resultView?.questions ?? questions).map((question) => [question.id, question])), [questions, resultView?.questions]);
  const answerById = useMemo(
    () => new Map(view.answers.map((answer) => [answer.attempt_item_id, answer])),
    [view.answers],
  );
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(view.answers.map((answer) => [answer.attempt_item_id, practiceResponseValue(answer.response)])),
  );
  const valuesRef = useRef(values);
  const mountedRef = useRef(true);
  const debounceTimersRef = useRef(new Map<string, ReturnType<typeof setTimeout>>());
  const [saveStates, setSaveStates] = useState<Record<string, PracticeAnswerSaveState>>({});
  const [saveQueue] = useState(() =>
    createPracticeAnswerSaveQueue({
      initialAnswers: view.answers,
      createIdempotencyKey: newIdempotencyKey,
    }),
  );
  const [currentIndex, setCurrentIndex] = useState(0);
  const [confirmAbandon, setConfirmAbandon] = useState(false);
  const [reportedQuestionIds, setReportedQuestionIds] = useState<Set<string>>(new Set());
  const answerInputRef = useRef<HTMLInputElement | null>(null);
  const active = view.attempt.state === "in_progress";
  const interactionReadOnly = readOnly || withdrawn;
  const hasUnsaved = hasUnsavedPracticeAnswers(values, view.answers);
  const hasMissing = view.items.some((item) => !(values[item.id] ?? "").trim());
  const score = resultView?.effective_score ?? resultView?.attempt.score;
  const resultsPresentation = practiceResultsPresentation(score, view.items.length);
  const canStartAgain = (resultView?.questions ?? questions).some(
    (question) => question.content_quality !== "invalidated",
  );
  const currentItem = view.items[Math.min(currentIndex, Math.max(0, view.items.length - 1))];
  const currentQuestion = currentItem ? byId.get(currentItem.question_id) : null;
  const currentOptions = currentItem && currentQuestion
    ? orderedPracticeOptions(currentQuestion, currentItem)
    : [];
  const currentIsChoice = currentQuestion?.question_type === "single_choice";
  const currentSaveState = currentItem ? saveStates[currentItem.id] : undefined;

  useEffect(() => {
    for (const answer of view.answers) saveQueue.syncAnswer(answer);
  }, [saveQueue, view.answers]);
  useEffect(() => {
    const debounceTimers = debounceTimersRef.current;
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      for (const timer of debounceTimers.values()) clearTimeout(timer);
      debounceTimers.clear();
    };
  }, []);
  useEffect(() => {
    if (active && !interactionReadOnly) answerInputRef.current?.focus();
  }, [active, currentIndex, interactionReadOnly]);

  const setItemValue = (itemId: string, value: string) => {
    valuesRef.current = { ...valuesRef.current, [itemId]: value };
    setValues(valuesRef.current);
  };
  const setItemSaveState = (itemId: string, state: PracticeAnswerSaveState) => {
    setSaveStates((previous) => ({ ...previous, [itemId]: state }));
  };
  const updateQueueState = (itemId: string, state: PracticeAnswerSaveState) => {
    if (mountedRef.current) setItemSaveState(itemId, state);
  };
  const flushQueuedItem = (itemId: string) =>
    saveQueue.flush(itemId, onSave, updateQueueState);
  const changeShortAnswer = (itemId: string, value: string) => {
    setItemValue(itemId, value);
    const existingTimer = debounceTimersRef.current.get(itemId);
    if (existingTimer) clearTimeout(existingTimer);
    debounceTimersRef.current.delete(itemId);
    const durable = practiceResponseValue(saveQueue.getAnswer(itemId)?.response ?? null);
    const pending = saveQueue.hasPending(itemId);
    if (value === durable && !pending) {
      setItemSaveState(itemId, { state: "saved" });
      return;
    }
    if (!value.trim() && !durable.trim() && !pending) {
      setSaveStates((previous) => {
        const next = { ...previous };
        delete next[itemId];
        return next;
      });
      return;
    }
    setItemSaveState(itemId, { state: "saving" });
    const timer = setTimeout(() => {
      debounceTimersRef.current.delete(itemId);
      saveQueue.enqueue(itemId, { answer: valuesRef.current[itemId] ?? "" });
      void flushQueuedItem(itemId);
    }, 500);
    debounceTimersRef.current.set(itemId, timer);
  };
  const selectOption = (optionId: string) => {
    if (!currentItem || interactionReadOnly) return;
    setItemValue(currentItem.id, optionId);
    setItemSaveState(currentItem.id, { state: "saving" });
    saveQueue.enqueue(currentItem.id, { option_id: optionId });
    void flushQueuedItem(currentItem.id);
  };
  const flushItem = async (itemId: string): Promise<boolean> => {
    if (withdrawn) return true;
    const item = view.items.find((candidate) => candidate.id === itemId);
    const question = item ? byId.get(item.question_id) : null;
    if (!question) return false;
    while (true) {
      const timer = debounceTimersRef.current.get(itemId);
      if (timer) clearTimeout(timer);
      debounceTimersRef.current.delete(itemId);
      const value = valuesRef.current[itemId] ?? "";
      const durable = practiceResponseValue(saveQueue.getAnswer(itemId)?.response ?? null);
      if (value !== durable) {
        if (question.question_type === "single_choice") {
          if (value) saveQueue.enqueue(itemId, { option_id: value });
        } else if (value.trim() || durable.trim()) {
          saveQueue.enqueue(itemId, { answer: value });
        } else {
          return true;
        }
      }
      if (!(await flushQueuedItem(itemId))) return false;
      const latestValue = valuesRef.current[itemId] ?? "";
      const latestDurable = practiceResponseValue(
        saveQueue.getAnswer(itemId)?.response ?? null,
      );
      if (
        latestValue === latestDurable &&
        !saveQueue.hasPending(itemId) &&
        !debounceTimersRef.current.has(itemId)
      ) {
        return true;
      }
    }
  };
  const navigateTo = async (index: number) => {
    if (!currentItem || index === currentIndex) return;
    if (await flushItem(currentItem.id)) setCurrentIndex(index);
  };
  const submitAttempt = async () => {
    const outcomes = await Promise.all(view.items.map((item) => flushItem(item.id)));
    if (outcomes.some((succeeded) => !succeeded)) return;
    const missing = view.items.some((item) => !(valuesRef.current[item.id] ?? "").trim());
    const unsaved = view.items.some((item) =>
      (valuesRef.current[item.id] ?? "") !==
        practiceResponseValue(saveQueue.getAnswer(item.id)?.response ?? null),
    );
    if (!missing && !unsaved) onTransition("submit");
  };

  return <div className="mx-auto mb-6 min-w-0 w-full max-w-3xl">
    <div className="mb-5 flex flex-wrap items-center justify-between gap-3"><div><h3 className="text-xl font-semibold">{resultView ? "Results" : "Practice in progress"}</h3>{view.attempt.timing_mode === "practice_timer" && active ? <AdvisoryPracticeTimer startedAt={view.attempt.started_at} /> : null}</div>{active ? <span className="text-sm font-medium">Question {currentIndex + 1} of {view.items.length}</span> : null}</div>
    {active && withdrawn ? <p role="alert" className="mb-4 rounded-xl border border-amber-500/50 bg-amber-500/10 p-4 text-sm">{WITHDRAWN_ATTEMPT_MESSAGE}</p> : null}
    {active && currentItem ? <>
      <div aria-label="Question navigation" className="mb-4 flex flex-wrap gap-2">{view.items.map((item, index) => { const saved = Boolean(practiceResponseValue(answerById.get(item.id)?.response ?? null).trim()); return <button key={item.id} type="button" aria-label={`Go to question ${index + 1}${saved ? ", answered" : ", unanswered"}`} aria-current={index === currentIndex ? "step" : undefined} onClick={() => void navigateTo(index)} className={`h-9 w-9 rounded-full border text-sm ${index === currentIndex ? "border-[var(--primary)] bg-[var(--primary)] text-[var(--primary-foreground)]" : "border-[var(--border)]"}`}>{index + 1}</button>; })}</div>
      <form key={currentItem.id} onSubmit={(event) => { event.preventDefault(); void flushItem(currentItem.id); }} className="min-w-0 rounded-2xl border border-[var(--border)] bg-[var(--card)] p-4 sm:p-7">
        <p className="text-xs font-medium uppercase tracking-wide text-[var(--muted-foreground)]">Question {currentIndex + 1}</p>
        <p className="mt-3 text-lg font-medium">{currentQuestion?.prompt ?? "Question unavailable"}</p>
        {currentIsChoice ? <fieldset className="mt-6 grid gap-3" disabled={interactionReadOnly}>
          <legend className="text-sm font-medium">Your answer</legend>
          {currentOptions.length ? currentOptions.map((option, index) => <label key={option.option_id} className="flex cursor-pointer items-start gap-3 rounded-xl border border-[var(--border)] bg-[var(--background)] px-3 py-3 text-sm has-[:checked]:border-[var(--primary)] has-[:checked]:bg-[var(--muted)]">
            <input ref={index === 0 ? answerInputRef : undefined} type="radio" name={`answer-${currentItem.id}`} value={option.option_id} checked={(values[currentItem.id] ?? "") === option.option_id} onChange={() => selectOption(option.option_id)} className="mt-0.5" />
            <span>{option.text}</span>
          </label>) : <p role="alert" className="text-sm text-amber-600">Choices are unavailable for this question. Return to the Practice library and try again.</p>}
          <p className="text-xs text-[var(--muted-foreground)]">Your selection is saved immediately.</p>
        </fieldset> : <>
          <label className="mt-6 grid min-w-0 gap-2 text-sm"><span>Your answer</span><input ref={answerInputRef} aria-label={`Answer for question ${currentItem.display_ordinal}`} value={values[currentItem.id] ?? ""} disabled={interactionReadOnly} onChange={(event) => changeShortAnswer(currentItem.id, event.target.value)} className="min-w-0 w-full rounded-xl border border-[var(--border)] bg-[var(--background)] px-3 py-3 disabled:opacity-60" placeholder="Type your answer" /></label>
          <p className="mt-2 text-xs text-[var(--muted-foreground)]">Answers are checked deterministically after submission. Capitalization and surrounding spaces do not matter.</p>
        </>}
        {currentSaveState ? <p role={currentSaveState.state === "error" ? "alert" : "status"} aria-live="polite" className={`mt-3 text-xs ${currentSaveState.state === "error" ? "text-red-600" : "text-[var(--muted-foreground)]"}`}>{currentSaveState.state === "saving" ? "Saving…" : currentSaveState.state === "saved" ? "Saved" : `Save failed: ${currentSaveState.message}`}</p> : null}
        <div className="mt-6 flex flex-wrap items-center justify-between gap-3"><button type="button" disabled={currentIndex === 0 || interactionReadOnly} onClick={() => void navigateTo(Math.max(0, currentIndex - 1))} className="rounded-lg border border-[var(--border)] px-4 py-2 text-sm disabled:opacity-40">Previous</button><div className="flex gap-2">{currentIndex < view.items.length - 1 ? <button type="button" disabled={interactionReadOnly} onClick={() => void navigateTo(Math.min(currentIndex + 1, view.items.length - 1))} className="rounded-lg bg-[var(--primary)] px-4 py-2 text-sm text-[var(--primary-foreground)] disabled:opacity-50">Next</button> : null}</div></div>
      </form>
      <div className="mt-5 flex flex-wrap items-center gap-3"><button disabled={interactionReadOnly || hasMissing} onClick={() => void submitAttempt()} className="inline-flex items-center gap-1 rounded-lg bg-[var(--primary)] px-4 py-2 text-sm text-[var(--primary-foreground)] disabled:opacity-50"><Send size={15} />Submit quiz</button>{!confirmAbandon ? <button disabled={readOnly} onClick={() => setConfirmAbandon(true)} className="rounded-lg border border-[var(--border)] px-4 py-2 text-sm">Leave this attempt</button> : <><span className="text-sm">Leave and mark this attempt abandoned?</span><button onClick={() => onTransition("abandon")} className="rounded-lg border border-red-500 px-3 py-2 text-sm text-red-600">Yes, abandon</button><button onClick={() => setConfirmAbandon(false)} className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm">Keep studying</button></>}{hasUnsaved ? <span className="text-xs text-[var(--muted-foreground)]">Your latest answer will be saved before submitting.</span> : hasMissing ? <span className="text-xs text-[var(--muted-foreground)]">Answer every question before submitting.</span> : null}</div>
    </> : null}
    {view.attempt.state === "submitted" ? <div className="rounded-xl border border-[var(--border)] p-5"><p className="font-medium">Your answers are submitted and locked.</p><p className="mt-1 text-sm text-[var(--muted-foreground)]">{withdrawn ? WITHDRAWN_SUBMITTED_MESSAGE : SUBMITTED_MESSAGE}</p><button disabled={interactionReadOnly} onClick={() => onTransition("grade")} className="mt-4 inline-flex items-center gap-1 rounded-lg bg-[var(--primary)] px-4 py-2 text-sm text-[var(--primary-foreground)]"><ClipboardCheck size={15} />Grade quiz</button></div> : null}
    {resultView?.attempt.state === "graded" ? <div className="space-y-5"><div className="rounded-xl bg-[var(--muted)] p-5"><p className="text-xl font-semibold">{resultsPresentation.headline}</p><p className="mt-1 text-sm text-[var(--muted-foreground)]">{resultsPresentation.guidance}</p></div><div className="space-y-3">{resultView.items.map((item) => {
      const question = byId.get(item.question_id);
      const response = resultView.answers.find((answer) => answer.attempt_item_id === item.id)?.response ?? null;
      const correct = item.grading?.is_correct === true;
      const reported = question ? reportedQuestionIds.has(question.id) : false;
      const invalidated = question?.content_quality === "invalidated";
      const citations = question?.citations ?? [];
      return <article key={item.id} className="rounded-xl border border-[var(--border)] p-4">
        <p className="font-medium">{item.display_ordinal}. {question?.prompt ?? "Question unavailable"}</p>
        {invalidated ? <p className="mt-2 text-sm font-medium text-amber-600">Question withdrawn after review. This item is excluded from your score and learning evidence.</p> : <p className={`mt-2 text-sm font-medium ${correct ? "text-emerald-600" : "text-amber-600"}`}>{correct ? "Correct" : "Needs review"}</p>}
        <p className="mt-3 text-sm"><span className="font-medium">Your answer:</span> {practiceResultAnswer(question, response)}</p>
        {invalidated ? <p className="mt-2 text-sm text-[var(--muted-foreground)]">The answer key, explanation, and citations were withdrawn.</p> : <>
          <p className="mt-2 text-sm"><span className="font-medium">Correct answer:</span> {practiceCorrectAnswer(question)}</p>
          <p className="mt-2 text-sm"><span className="font-medium">Why:</span> {question?.explanation || "No explanation was provided."}</p>
          <div className="mt-3 text-sm"><p className="font-medium">Citations:</p>{citations.length ? <ul aria-label={`Citations for question ${item.display_ordinal}`} className="mt-2 flex flex-wrap gap-2 text-xs text-[var(--muted-foreground)]">{citations.map((citation, index) => { const sourceId = typeof citation.source_id === "string" ? citation.source_id : ""; return <li key={`${sourceId}-${index}`} className="rounded-full bg-[var(--muted)] px-2 py-1">{sourceNames.get(sourceId) ?? `Course source ${index + 1}`}</li>; })}</ul> : <p className="mt-1 text-xs text-[var(--muted-foreground)]">No citations were provided.</p>}</div>
        </>}
        <button type="button" disabled={readOnly || reported || invalidated || !question} onClick={() => { if (question) { void onReportQuestion(question.id).then(() => setReportedQuestionIds((previous) => new Set(previous).add(question.id))); } }} className="mt-3 rounded-lg border border-[var(--border)] px-3 py-2 text-xs disabled:opacity-50">{invalidated ? REPORTED_AND_WITHDRAWN_LABEL : reported ? "Reported for review" : "Report a problem with this question"}</button>
      </article>;
    })}</div><div className="flex flex-wrap gap-2">{canStartAgain ? <button type="button" disabled={readOnly} onClick={onStartAgain} className="rounded-lg bg-[var(--primary)] px-4 py-2 text-sm text-[var(--primary-foreground)] disabled:opacity-50">Try another Practice</button> : null}{resultsPresentation.hasMisses ? <button type="button" disabled={readOnly} onClick={onReviewMisses} className="rounded-lg border border-[var(--border)] px-4 py-2 text-sm disabled:opacity-50">Review mistakes</button> : null}<button type="button" onClick={onClose} className="rounded-lg border border-[var(--border)] px-4 py-2 text-sm">Back to Practice</button></div></div> : null}
  </div>;
}

function practiceResultAnswer(
  question: PracticeQuestion | undefined,
  response: QuizAttemptResponse | null,
): string {
  if (!response) return "No answer submitted.";
  if ("answer" in response) return response.answer || "No answer submitted.";
  return question?.options.find((option) => option.option_id === response.option_id)?.text
    ?? "Selected option unavailable.";
}

function practiceCorrectAnswer(question: PracticeQuestion | undefined): string {
  const contract = question?.answer_contract;
  if (!contract) return "Correct answer unavailable.";
  if (contract.kind === "exact") return contract.answer;
  if (contract.kind === "bounded_short_answer_v1") return contract.canonical_answer;
  return question.options.find((option) => option.option_id === contract.correct_option_id)?.text
    ?? "Correct option unavailable.";
}

function AdvisoryPracticeTimer({ startedAt }: { startedAt: number }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const interval = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(interval);
  }, []);
  const elapsed = Math.max(0, Math.floor(now / 1_000 - startedAt));
  const minutes = Math.floor(elapsed / 60);
  const seconds = elapsed % 60;
  return <p role="timer" aria-live="off" className="mt-1 text-xs text-[var(--muted-foreground)]">
    Elapsed {minutes}:{String(seconds).padStart(2, "0")} · advisory only
  </p>;
}
