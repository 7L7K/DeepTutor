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
  revision: number;
  write_epoch: number;
  created_at: number;
  updated_at: number;
  archived_at: number | null;
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

export interface PracticeQuestion {
  id: string;
  practice_set_revision_id: string;
  question_type: string;
  prompt: string;
  /** Present only in the draft-authoring response; never trusted by quiz UI. */
  answer_contract?: { kind: "exact"; answer: string };
  /** Revealed only for draft authoring or after the owned attempt is graded. */
  explanation?: string;
  objective_ids: string[];
  citations: Array<Record<string, unknown>>;
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
}

export interface QuizAttemptAnswer {
  attempt_item_id: string;
  response: { answer: string } | null;
  revision: number;
  answered_at: number | null;
}

export interface QuizAttemptView {
  attempt: QuizAttempt;
  items: QuizAttemptItem[];
  answers: QuizAttemptAnswer[];
}

export interface QuizResult extends QuizAttemptView {
  /** Answer contracts are revealed only by the server after durable grading. */
  questions: PracticeQuestion[];
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
    (answer) => (values[answer.attempt_item_id] ?? "") !== (answer.response?.answer ?? ""),
  );
}

/** Do not keep draft answer contracts in the browser once a revision is ready. */
export function learnerSafePracticeQuestions(
  questions: PracticeQuestion[],
): PracticeQuestion[] {
  return questions.map(({ answer_contract: _answerContract, ...question }) => question);
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
    question_type: string;
    prompt: string;
    answer_contract: { kind: "exact"; answer: string };
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
  return json<QuizResult>(apiFetch(apiUrl(path(
    courseId,
    `/${encodeURIComponent(practiceSetId)}/attempts/${encodeURIComponent(attemptId)}`,
  )), { cache: "no-store" }));
}

export function autosavePracticeAnswer(
  courseId: string,
  practiceSet: PracticeSet,
  attempt: QuizAttempt,
  answer: QuizAttemptAnswer,
  response: { answer: string },
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

export function getPracticeResults(courseId: string, practiceSetId: string, attemptId: string) {
  return json<QuizResult>(apiFetch(apiUrl(path(
    courseId,
    `/${encodeURIComponent(practiceSetId)}/attempts/${encodeURIComponent(attemptId)}/results`,
  )), { cache: "no-store" }));
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
