import { apiFetch, apiUrl } from "./api";
import type { FlashcardGenerationBriefReceipt } from "./flashcards-api";

/**
 * Course-owned Practice transport.  The browser only keeps transient editor
 * state: revision content, attempt order, answer revisions, and results are
 * always reloaded from the private Course service.
 */

export type PracticeSetState = "draft" | "archived";
export type PracticeRevisionState = "draft" | "ready" | "superseded";
export type QuizAttemptState =
  | "in_progress"
  | "submitted"
  | "graded"
  | "abandoned"
  | "archived";

export interface PracticeSet {
  id: string;
  owner_user_id: string;
  course_id: string;
  title: string;
  mode: "manual" | "generated";
  state: PracticeSetState;
  current_revision_id: string | null;
  draft_revision_id?: string | null;
  revision: number;
  write_epoch: number;
  created_at: number;
  updated_at: number;
  archived_at: number | null;
}

/** Prefer the published revision, otherwise recover its durable editable draft. */
export function practiceSetRevisionId(practiceSet: PracticeSet): string | null {
  return practiceSet.current_revision_id ?? practiceSet.draft_revision_id ?? null;
}

export type PracticeDetailState = "idle" | "loading" | "loaded" | "error";

/** A new draft may start only after a settled, revision-free manual-set read. */
export function canStartManualPracticeDraft(
  practiceSet: PracticeSet,
  detailState: PracticeDetailState,
): boolean {
  return (
    practiceSet.mode === "manual" &&
    practiceSet.state !== "archived" &&
    practiceSetRevisionId(practiceSet) === null &&
    detailState === "loaded"
  );
}

export interface PracticeRevision {
  id: string;
  practice_set_id: string;
  revision_number: number;
  state: PracticeRevisionState;
  source_snapshot: Array<Record<string, unknown>>;
  objective_ids: string[];
  created_at: number;
  ready_at: number | null;
}

export type PracticeGenerationState = "queued" | "running" | "completed" | "failed";

export interface PracticeSourceReceipt {
  source_id: string;
  source_revision: number;
  content_sha256: string;
}

export interface PracticeGenerationPlan {
  id: string;
  owner_user_id: string;
  course_id: string;
  title: string;
  focus: string;
  source_snapshot: PracticeSourceReceipt[];
  objective_ids: string[];
  item_limit: number;
  difficulty: "foundation" | "mixed" | "challenge";
  timing_mode: "untimed" | "practice_timer";
  origin: {
    kind: "practice" | "course_chat";
    session_id: string | null;
    assistant_message_id: number | null;
  };
  course_write_epoch: number;
  revision: number;
  state: "draft" | "confirmed" | "expired";
  confirmed_operation_id: string | null;
  created_at: number;
  updated_at: number;
  confirmed_at: number | null;
}

export interface PracticeGenerationOperation {
  id: string;
  owner_user_id: string;
  course_id: string;
  practice_set_id: string;
  practice_set_revision_id: string;
  source_snapshot: PracticeSourceReceipt[];
  objective_ids: string[];
  item_limit: number;
  context_char_limit: number;
  focus: string;
  difficulty: "foundation" | "mixed" | "challenge";
  timing_mode: "untimed" | "practice_timer";
  state: PracticeGenerationState;
  error_code: string | null;
  cancel_requested_at: number | null;
  cancelled_at: number | null;
  created_at: number;
  updated_at: number;
}

export interface PracticeGenerationConfirmation {
  plan: PracticeGenerationPlan;
  request: {
    practice_set_id: string;
    practice_set_revision_id: string;
    operation: PracticeGenerationOperation;
  };
}

/** Keep failed unpublished generation shells out of the learner's Study list. */
export function practiceLibrarySets(
  sets: PracticeSet[],
  operations: PracticeGenerationOperation[],
): PracticeSet[] {
  const failedSetIds = new Set(
    operations
      .filter((operation) => operation.state === "failed")
      .map((operation) => operation.practice_set_id),
  );
  return sets.filter(
    (practiceSet) =>
      Boolean(practiceSet.current_revision_id) ||
      !failedSetIds.has(practiceSet.id),
  );
}

const PRACTICE_PLAN_HANDOFF_PREFIX = "teeechr:practice-plan:v1";

function planHandoffKey(identity: string, courseId: string): string {
  return `${PRACTICE_PLAN_HANDOFF_PREFIX}:${identity}:${courseId}`;
}

/** Keep only an opaque durable plan ID in the browser handoff. */
export function storePracticePlanHandoff(
  identity: string,
  courseId: string,
  planId: string,
): void {
  sessionStorage.setItem(
    planHandoffKey(identity, courseId),
    JSON.stringify({ planId, createdAt: Date.now() }),
  );
}

export function consumePracticePlanHandoff(
  identity: string,
  courseId: string,
): string | null {
  const key = planHandoffKey(identity, courseId);
  const raw = sessionStorage.getItem(key);
  sessionStorage.removeItem(key);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as { planId?: unknown; createdAt?: unknown };
    if (
      typeof parsed.planId !== "string" ||
      !parsed.planId.startsWith("pln_") ||
      typeof parsed.createdAt !== "number" ||
      Date.now() - parsed.createdAt > 15 * 60_000
    ) {
      return null;
    }
    return parsed.planId;
  } catch {
    return null;
  }
}

export interface SingleChoiceOption {
  option_id: string;
  text: string;
}

export type PracticeAnswerContract =
  | { kind: "exact"; answer: string }
  | {
      kind: "bounded_short_answer_v1";
      canonical_answer: string;
      accepted_normalized_answers: string[];
      normalization_version: "bounded-text-normalization-v1";
    }
  | { kind: "single_choice_v1"; correct_option_id: string };

export interface PracticeQuestion {
  id: string;
  practice_set_revision_id: string;
  question_type: "short_answer" | "single_choice";
  prompt: string;
  /** Learner-safe choices; correctness remains server-owned until grading. */
  options: SingleChoiceOption[];
  /** Present only in the draft-authoring response; never trusted by quiz UI. */
  answer_contract?: PracticeAnswerContract;
  /** Revealed only for draft authoring or after the owned attempt is graded. */
  explanation?: string;
  objective_ids: string[];
  /** Revealed only after grading because locators can contain answer-adjacent evidence. */
  citations?: Array<Record<string, unknown>>;
  content_quality?: "valid" | "invalidated";
  ordinal: number;
  created_at: number;
}

export interface QuizAttempt {
  id: string;
  owner_user_id: string;
  course_id: string;
  practice_set_id: string;
  practice_set_revision_id: string;
  timing_mode: "untimed" | "practice_timer";
  state: QuizAttemptState;
  score: { correct?: number; total?: number; fraction?: number } | null;
  revision: number;
  course_write_epoch: number;
  practice_set_write_epoch: number;
  started_at: number;
  submitted_at: number | null;
  graded_at: number | null;
  archived_at: number | null;
  updated_at: number;
  /** Learner history never presents a superseded invalidated raw score. */
  content_quality?: "valid" | "adjusted_for_invalidated_question";
}

export interface QuizAttemptItem {
  id: string;
  attempt_id: string;
  question_id: string;
  display_ordinal: number;
  option_order: string[] | null;
  randomized_values: Record<string, unknown> | null;
  grading: Record<string, unknown> | null;
  error_type: string | null;
  graded_at: number | null;
  /** Present in Results; invalidated items are withdrawn from score authority. */
  content_quality?: "valid" | "invalidated";
}

export type QuizAttemptResponse = { answer: string } | { option_id: string };

export interface QuizAttemptAnswer {
  attempt_item_id: string;
  response: QuizAttemptResponse | null;
  revision: number;
  answered_at: number | null;
}

export type PracticeAnswerSaveState =
  | { state: "saving" }
  | { state: "saved" }
  | { state: "error"; message: string };

export interface PracticeAnswerSaveQueue {
  enqueue: (itemId: string, response: QuizAttemptResponse) => void;
  flush: (
    itemId: string,
    save: (
      answer: QuizAttemptAnswer,
      response: QuizAttemptResponse,
      idempotencyKey: string,
    ) => Promise<QuizAttemptAnswer>,
    onState?: (itemId: string, state: PracticeAnswerSaveState) => void,
  ) => Promise<boolean>;
  hasPending: (itemId: string) => boolean;
  getAnswer: (itemId: string) => QuizAttemptAnswer | null;
  syncAnswer: (answer: QuizAttemptAnswer) => void;
}

/**
 * Serialize answer writes per attempt item. A failed head write stays queued
 * with the same idempotency key; the key rotates only after that write is
 * durably acknowledged, so a later response can never race answer_revision.
 */
export function createPracticeAnswerSaveQueue({
  initialAnswers,
  createIdempotencyKey,
}: {
  initialAnswers: QuizAttemptAnswer[];
  createIdempotencyKey: () => string;
}): PracticeAnswerSaveQueue {
  const answers = new Map(
    initialAnswers.map((answer) => [answer.attempt_item_id, answer]),
  );
  const queued = new Map<string, QuizAttemptResponse[]>();
  const keys = new Map<string, string>();
  const running = new Map<string, Promise<boolean>>();

  const sameResponse = (left: QuizAttemptResponse, right: QuizAttemptResponse) =>
    "answer" in left && "answer" in right
      ? left.answer === right.answer
      : "option_id" in left && "option_id" in right
        ? left.option_id === right.option_id
        : false;

  const enqueue = (itemId: string, response: QuizAttemptResponse) => {
    const itemQueue = queued.get(itemId) ?? [];
    if (!itemQueue.length || !sameResponse(itemQueue[itemQueue.length - 1]!, response)) {
      itemQueue.push(response);
      queued.set(itemId, itemQueue);
    }
  };

  const flush: PracticeAnswerSaveQueue["flush"] = async (itemId, save, onState) => {
    const active = running.get(itemId);
    if (active) {
      const succeeded = await active;
      if (!succeeded) return false;
      return (queued.get(itemId)?.length ?? 0) ? flush(itemId, save, onState) : true;
    }

    const operation = (async () => {
      const itemQueue = queued.get(itemId);
      while (itemQueue?.length) {
        const answer = answers.get(itemId) ?? null;
        if (!answer) {
          onState?.(itemId, {
            state: "error",
            message: "The saved answer revision is unavailable.",
          });
          return false;
        }
        const response = itemQueue[0]!;
        const idempotencyKey = keys.get(itemId) ?? createIdempotencyKey();
        keys.set(itemId, idempotencyKey);
        onState?.(itemId, { state: "saving" });
        try {
          const saved = await save(answer, response, idempotencyKey);
          answers.set(saved.attempt_item_id, saved);
          itemQueue.shift();
          keys.set(itemId, createIdempotencyKey());
          onState?.(itemId, { state: "saved" });
        } catch (cause) {
          onState?.(itemId, {
            state: "error",
            message: cause instanceof Error ? cause.message : "Answer save failed.",
          });
          return false;
        }
      }
      queued.delete(itemId);
      return true;
    })();

    running.set(itemId, operation);
    try {
      return await operation;
    } finally {
      if (running.get(itemId) === operation) running.delete(itemId);
    }
  };

  return {
    enqueue,
    flush,
    hasPending: (itemId: string) => Boolean(queued.get(itemId)?.length || running.has(itemId)),
    getAnswer: (itemId: string) => answers.get(itemId) ?? null,
    syncAnswer: (answer: QuizAttemptAnswer) => {
      const known = answers.get(answer.attempt_item_id);
      if (!known || answer.revision >= known.revision) {
        answers.set(answer.attempt_item_id, answer);
      }
    },
  };
}

export interface QuizAttemptView {
  attempt: QuizAttempt;
  items: QuizAttemptItem[];
  answers: QuizAttemptAnswer[];
  content_quality?: {
    invalidated_question_ids?: string[];
    status?: "valid" | "adjusted_for_invalidated_question";
  };
}

export interface QuizResult extends QuizAttemptView {
  /** Answer contracts are revealed only by the server after durable grading. */
  questions: PracticeQuestion[];
  effective_score?: QuizAttempt["score"];
  content_quality?: {
    invalidated_question_ids?: string[];
    invalidated_evidence_ids?: string[];
    status?: "valid" | "adjusted_for_invalidated_question";
  };
}

export interface PracticeResultsPresentation {
  headline: string;
  guidance: string;
  hasMisses: boolean;
}

export interface PracticeRevisionAvailability {
  totalQuestionCount: number;
  validQuestionCount: number;
  canStart: boolean;
  status: "Ready for quiz attempts" | "No trustworthy questions remain";
}

/** Derive attempt admission from server-owned content quality, not revision state. */
export function practiceRevisionAvailability(
  questions: PracticeQuestion[],
): PracticeRevisionAvailability {
  const validQuestionCount = questions.filter(
    (question) => question.content_quality !== "invalidated",
  ).length;
  return {
    totalQuestionCount: questions.length,
    validQuestionCount,
    canStart: validQuestionCount > 0,
    status: validQuestionCount > 0
      ? "Ready for quiz attempts"
      : "No trustworthy questions remain",
  };
}

/** Keep zero-effective-total Results distinct from a perfect scored attempt. */
export function practiceResultsPresentation(
  score: QuizAttempt["score"] | undefined,
  fallbackTotal = 0,
): PracticeResultsPresentation {
  const correct = typeof score?.correct === "number" ? score.correct : 0;
  const total = typeof score?.total === "number" ? score.total : fallbackTotal;
  if (total === 0) {
    return {
      headline: "No scored questions remain after review",
      guidance: "Withdrawn questions are excluded from your score and learning evidence.",
      hasMisses: false,
    };
  }
  const hasMisses = correct < total;
  return {
    headline: `${correct} correct out of ${total}`,
    guidance: hasMisses
      ? "Review the missed answers and explanations below."
      : "You got every question correct.",
    hasMisses,
  };
}

/**
 * Defense in depth for learner Results: an invalidated row cannot retain an
 * answer key, rationale, citations, or a correctness decision even if a stale
 * server accidentally includes those historical fields.
 */
export function withdrawInvalidatedPracticeResults(result: QuizResult): QuizResult {
  const invalidatedQuestionIds = new Set(
    result.content_quality?.invalidated_question_ids ?? [],
  );
  for (const question of result.questions) {
    if (question.content_quality === "invalidated") {
      invalidatedQuestionIds.add(question.id);
    }
  }
  for (const item of result.items) {
    if (item.content_quality === "invalidated") {
      invalidatedQuestionIds.add(item.question_id);
    }
  }

  return {
    ...result,
    attempt: invalidatedQuestionIds.size
      ? {
          ...result.attempt,
          score: null,
          content_quality: "adjusted_for_invalidated_question",
        }
      : result.attempt,
    items: result.items.map((item) =>
      invalidatedQuestionIds.has(item.question_id)
        ? { ...item, grading: null, error_type: null, content_quality: "invalidated" }
        : item,
    ),
    questions: result.questions.map((question) => {
      if (!invalidatedQuestionIds.has(question.id)) return question;
      const {
        answer_contract: _answerContract,
        explanation: _explanation,
        citations: _citations,
        ...withdrawn
      } = question;
      return { ...withdrawn, content_quality: "invalidated" };
    }),
  };
}

/** Render the server-authoritative score as an accessible percentage and ratio. */
export function formatPracticeScore(
  score: QuizAttempt["score"],
): string | null {
  if (!score) return null;
  const { correct, total } = score;
  if (
    typeof correct !== "number" ||
    typeof total !== "number" ||
    !Number.isFinite(correct) ||
    !Number.isFinite(total) ||
    !Number.isInteger(correct) ||
    !Number.isInteger(total) ||
    total <= 0 ||
    correct < 0 ||
    correct > total
  ) {
    return null;
  }
  return `${Math.round((correct / total) * 100)}% (${correct}/${total})`;
}

export function practiceAttemptHistoryLabel(attempt: QuizAttempt): string | null {
  if (attempt.content_quality === "adjusted_for_invalidated_question") {
    return "Adjusted after review";
  }
  return formatPracticeScore(attempt.score);
}

export interface PracticeRequestScope {
  identity: string | null;
  courseId: string | null;
  epoch: number;
  /** Advances for every set or attempt view selection within one Course. */
  viewEpoch: number;
}

/** A request is applicable only to the exact identity, Course, and UI epoch. */
export function isCurrentPracticeResponse(
  response: PracticeRequestScope,
  current: PracticeRequestScope,
): boolean {
  return (
    response.identity === current.identity &&
    response.courseId === current.courseId &&
    response.epoch === current.epoch &&
    response.viewEpoch === current.viewEpoch
  );
}

/** Start a new set/attempt detail view without changing the ownership scope. */
export function advancePracticeViewScope(scope: PracticeRequestScope): PracticeRequestScope {
  return { ...scope, viewEpoch: scope.viewEpoch + 1 };
}

/** Submission must wait until every visible value matches its server revision. */
export function hasUnsavedPracticeAnswers(
  values: Record<string, string>,
  answers: QuizAttemptAnswer[],
): boolean {
  return answers.some(
    (answer) =>
      (values[answer.attempt_item_id] ?? "") !== practiceResponseValue(answer.response),
  );
}

/** Return the one learner-visible value from the strict autosave response union. */
export function practiceResponseValue(response: QuizAttemptResponse | null): string {
  if (!response) return "";
  return "answer" in response ? response.answer : response.option_id;
}

/** Resolve choices only through the server-frozen attempt presentation. */
export function orderedPracticeOptions(
  question: PracticeQuestion,
  item: QuizAttemptItem,
): SingleChoiceOption[] {
  if (question.question_type !== "single_choice" || !item.option_order) return [];
  const byId = new Map(question.options.map((option) => [option.option_id, option]));
  if (
    byId.size !== question.options.length ||
    item.option_order.length !== byId.size ||
    new Set(item.option_order).size !== item.option_order.length ||
    item.option_order.some((optionId) => !byId.has(optionId))
  ) {
    return [];
  }
  return item.option_order.map((optionId) => byId.get(optionId)!);
}

/** Do not keep answer-adjacent draft fields once a revision is ready. */
export function learnerSafePracticeQuestions(
  questions: PracticeQuestion[],
): PracticeQuestion[] {
  return questions.map(({
    answer_contract: _answerContract,
    explanation: _explanation,
    citations: _citations,
    ...question
  }) => question);
}

async function json<T>(response: Response | Promise<Response>): Promise<T> {
  const resolved = await response;
  const body = await resolved.json().catch(() => ({}));
  if (!resolved.ok) {
    throw new Error(String((body as { detail?: unknown }).detail || `Request failed: ${resolved.status}`));
  }
  return body as T;
}

function path(courseId: string, suffix = ""): string {
  return `/api/v1/courses/${encodeURIComponent(courseId)}/practice${suffix}`;
}

function generationPath(courseId: string, suffix = ""): string {
  return `/api/v1/courses/${encodeURIComponent(courseId)}/practice-generation${suffix}`;
}

function mutation(body: unknown, idempotencyKey?: string): RequestInit {
  return {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(idempotencyKey ? { "Idempotency-Key": idempotencyKey } : {}),
    },
    body: JSON.stringify(body),
  };
}

export async function listPracticeSets(courseId: string): Promise<PracticeSet[]> {
  const body = await json<{ practice_sets?: PracticeSet[]; sets?: PracticeSet[] }>(
    await apiFetch(apiUrl(path(courseId)), { cache: "no-store" }),
  );
  return body.practice_sets ?? body.sets ?? [];
}

export function createPracticeGenerationPlan(
  courseId: string,
  body: {
    title: string;
    focus: string;
    source_ids: string[];
    objective_ids: string[];
    expected_course_write_epoch: number;
    item_limit: number;
    difficulty: PracticeGenerationPlan["difficulty"];
    timing_mode: PracticeGenerationPlan["timing_mode"];
  },
  idempotencyKey: string,
) {
  return json<PracticeGenerationPlan>(
    apiFetch(
      apiUrl(generationPath(courseId, "/plans")),
      mutation(body, idempotencyKey),
    ),
  );
}

export function getPracticeGenerationPlan(courseId: string, planId: string) {
  return json<PracticeGenerationPlan>(
    apiFetch(
      apiUrl(
        generationPath(courseId, `/plans/${encodeURIComponent(planId)}`),
      ),
      { cache: "no-store" },
    ),
  );
}

export function updatePracticeGenerationPlan(
  courseId: string,
  plan: PracticeGenerationPlan,
  body: {
    title: string;
    focus: string;
    source_ids: string[];
    objective_ids: string[];
    item_limit: number;
    difficulty: PracticeGenerationPlan["difficulty"];
    timing_mode: PracticeGenerationPlan["timing_mode"];
  },
) {
  const updateBody = {
    title: body.title,
    focus: body.focus,
    source_ids: body.source_ids,
    objective_ids: body.objective_ids,
    item_limit: body.item_limit,
    difficulty: body.difficulty,
    timing_mode: body.timing_mode,
    expected_revision: plan.revision,
  };
  return json<PracticeGenerationPlan>(
    apiFetch(
      apiUrl(
        generationPath(courseId, `/plans/${encodeURIComponent(plan.id)}`),
      ),
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(updateBody),
      },
    ),
  );
}

export function confirmPracticeGenerationPlan(
  courseId: string,
  plan: PracticeGenerationPlan,
  idempotencyKey: string,
) {
  return json<PracticeGenerationConfirmation>(
    apiFetch(
      apiUrl(
        generationPath(
          courseId,
          `/plans/${encodeURIComponent(plan.id)}/confirm`,
        ),
      ),
      mutation({ expected_revision: plan.revision }, idempotencyKey),
    ),
  );
}

export function getPracticeGenerationOperation(
  courseId: string,
  operationId: string,
) {
  return json<PracticeGenerationOperation>(
    apiFetch(
      apiUrl(generationPath(courseId, `/${encodeURIComponent(operationId)}`)),
      { cache: "no-store" },
    ),
  );
}

export async function listPracticeGenerationOperations(
  courseId: string,
): Promise<PracticeGenerationOperation[]> {
  const body = await json<{ operations?: PracticeGenerationOperation[] }>(
    apiFetch(apiUrl(generationPath(courseId)), { cache: "no-store" }),
  );
  return body.operations ?? [];
}

export function cancelPracticeGenerationOperation(
  courseId: string,
  operationId: string,
) {
  return json<PracticeGenerationOperation>(
    apiFetch(
      apiUrl(
        generationPath(courseId, `/${encodeURIComponent(operationId)}/cancel`),
      ),
      mutation({}),
    ),
  );
}

export function createPracticeSet(courseId: string, title: string, courseWriteEpoch: number) {
  return json<PracticeSet>(apiFetch(apiUrl(path(courseId)), mutation({
    title,
    expected_course_write_epoch: courseWriteEpoch,
  })));
}

export function getPracticeSet(courseId: string, practiceSetId: string) {
  return json<PracticeSet>(apiFetch(apiUrl(path(courseId, `/${encodeURIComponent(practiceSetId)}`)), { cache: "no-store" }));
}

export function archivePracticeSet(courseId: string, practiceSet: PracticeSet, courseWriteEpoch: number) {
  return json<PracticeSet>(apiFetch(apiUrl(path(courseId, `/${encodeURIComponent(practiceSet.id)}/archive`)), mutation({
    expected_revision: practiceSet.revision,
    expected_course_write_epoch: courseWriteEpoch,
  })));
}

export function restorePracticeSet(courseId: string, practiceSet: PracticeSet, courseWriteEpoch: number) {
  return json<PracticeSet>(apiFetch(apiUrl(path(courseId, `/${encodeURIComponent(practiceSet.id)}/restore`)), mutation({
    expected_revision: practiceSet.revision,
    expected_course_write_epoch: courseWriteEpoch,
  })));
}

export function createPracticeRevision(
  courseId: string,
  practiceSetId: string,
  courseWriteEpoch: number,
  successor = false,
) {
  return json<PracticeRevision>(apiFetch(apiUrl(path(
    courseId,
    `/${encodeURIComponent(practiceSetId)}/revisions${successor ? "/successor" : ""}`,
  )), mutation({ expected_course_write_epoch: courseWriteEpoch })));
}

export function getPracticeRevision(courseId: string, practiceSetId: string, revisionId: string) {
  return json<PracticeRevision>(apiFetch(apiUrl(path(
    courseId,
    `/${encodeURIComponent(practiceSetId)}/revisions/${encodeURIComponent(revisionId)}`,
  )), { cache: "no-store" }));
}

export async function listPracticeQuestions(courseId: string, practiceSetId: string, revisionId: string) {
  const body = await json<{ questions?: PracticeQuestion[] }>(apiFetch(apiUrl(path(
    courseId,
    `/${encodeURIComponent(practiceSetId)}/revisions/${encodeURIComponent(revisionId)}/questions`,
  )), { cache: "no-store" }));
  return body.questions ?? [];
}

export function addPracticeQuestion(
  courseId: string,
  practiceSetId: string,
  revisionId: string,
  body: {
    question_type: PracticeQuestion["question_type"];
    prompt: string;
    options?: SingleChoiceOption[];
    answer_contract: PracticeAnswerContract;
    explanation: string;
    objective_ids: string[];
    expected_course_write_epoch: number;
  },
) {
  return json<PracticeQuestion>(apiFetch(apiUrl(path(
    courseId,
    `/${encodeURIComponent(practiceSetId)}/revisions/${encodeURIComponent(revisionId)}/questions`,
  )), mutation(body)));
}

export function readyPracticeRevision(courseId: string, practiceSetId: string, revisionId: string, courseWriteEpoch: number) {
  return json<PracticeRevision>(apiFetch(apiUrl(path(
    courseId,
    `/${encodeURIComponent(practiceSetId)}/revisions/${encodeURIComponent(revisionId)}/ready`,
  )), mutation({ expected_course_write_epoch: courseWriteEpoch })));
}

export function startPracticeAttempt(
  courseId: string,
  practiceSet: PracticeSet,
  practiceSetRevisionId: string,
  courseWriteEpoch: number,
) {
  return json<QuizAttemptView>(apiFetch(apiUrl(path(courseId, `/${encodeURIComponent(practiceSet.id)}/attempts`)), mutation({
    practice_set_revision_id: practiceSetRevisionId,
    expected_course_write_epoch: courseWriteEpoch,
    expected_practice_set_write_epoch: practiceSet.write_epoch,
  })));
}

export async function listPracticeAttempts(
  courseId: string,
  practiceSetId: string,
  offset = 0,
): Promise<QuizAttempt[]> {
  const body = await json<{ attempts?: QuizAttempt[] }>(apiFetch(apiUrl(path(
    courseId,
    `/${encodeURIComponent(practiceSetId)}/attempts?limit=50&offset=${offset}`,
  )), { cache: "no-store" }));
  return body.attempts ?? [];
}

export function getPracticeAttempt(courseId: string, practiceSetId: string, attemptId: string) {
  return json<QuizAttemptView>(apiFetch(apiUrl(path(
    courseId,
    `/${encodeURIComponent(practiceSetId)}/attempts/${encodeURIComponent(attemptId)}`,
  )), { cache: "no-store" }));
}

export function autosavePracticeAnswer(
  courseId: string,
  practiceSet: PracticeSet,
  attempt: QuizAttempt,
  answer: QuizAttemptAnswer,
  response: QuizAttemptResponse,
  idempotencyKey: string,
) {
  return json<QuizAttemptAnswer>(apiFetch(apiUrl(path(
    courseId,
    `/${encodeURIComponent(practiceSet.id)}/attempts/${encodeURIComponent(attempt.id)}`,
  )), {
    method: "PATCH",
    headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey },
    body: JSON.stringify({
      attempt_item_id: answer.attempt_item_id,
      response,
      expected_answer_revision: answer.revision,
      expected_course_write_epoch: attempt.course_write_epoch,
      expected_practice_set_write_epoch: attempt.practice_set_write_epoch,
    }),
  }));
}

function mutateAttempt(
  courseId: string,
  practiceSet: PracticeSet,
  attempt: QuizAttempt,
  action: "submit" | "abandon" | "grade",
) {
  return json<QuizAttempt>(apiFetch(apiUrl(path(
    courseId,
    `/${encodeURIComponent(practiceSet.id)}/attempts/${encodeURIComponent(attempt.id)}/${action}`,
  )), mutation({
    expected_course_write_epoch: attempt.course_write_epoch,
    expected_practice_set_write_epoch: attempt.practice_set_write_epoch,
  })));
}

export const submitPracticeAttempt = (courseId: string, practiceSet: PracticeSet, attempt: QuizAttempt) =>
  mutateAttempt(courseId, practiceSet, attempt, "submit");
export const abandonPracticeAttempt = (courseId: string, practiceSet: PracticeSet, attempt: QuizAttempt) =>
  mutateAttempt(courseId, practiceSet, attempt, "abandon");
export const gradePracticeAttempt = (courseId: string, practiceSet: PracticeSet, attempt: QuizAttempt) =>
  mutateAttempt(courseId, practiceSet, attempt, "grade");

export async function getPracticeResults(courseId: string, practiceSetId: string, attemptId: string) {
  const result = await json<QuizResult>(apiFetch(apiUrl(path(
    courseId,
    `/${encodeURIComponent(practiceSetId)}/attempts/${encodeURIComponent(attemptId)}/results`,
  )), { cache: "no-store" }));
  return withdrawInvalidatedPracticeResults(result);
}

export function reportPracticeQuestion(
  courseId: string,
  practiceSetId: string,
  revisionId: string,
  questionId: string,
  reason: string,
) {
  return json<{ id: string; state: "reported" }>(
    apiFetch(
      apiUrl(path(
        courseId,
        `/${encodeURIComponent(practiceSetId)}/revisions/${encodeURIComponent(revisionId)}/questions/${encodeURIComponent(questionId)}/quality-report`,
      )),
      mutation({ reason }),
    ),
  );
}

export function preparePracticeRemediationFlashcards(
  courseId: string,
  practiceSetId: string,
  attemptId: string,
) {
  return json<FlashcardGenerationBriefReceipt>(apiFetch(apiUrl(path(
    courseId,
    `/${encodeURIComponent(practiceSetId)}/attempts/${encodeURIComponent(attemptId)}/flashcard-brief`,
  )), mutation({})));
}
