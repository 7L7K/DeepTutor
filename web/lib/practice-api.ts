import { apiFetch, apiUrl } from "./api";

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

export async function listPracticeAttempts(courseId: string, practiceSetId: string): Promise<QuizAttempt[]> {
  const body = await json<{ attempts?: QuizAttempt[] }>(apiFetch(apiUrl(path(
    courseId,
    `/${encodeURIComponent(practiceSetId)}/attempts`,
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
