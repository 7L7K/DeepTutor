import { apiFetch, apiUrl } from "./api";

export type FlashcardDeckState = "draft" | "ready" | "archived";
export type FlashcardRating = "again" | "hard" | "good" | "easy";

export interface FlashcardDeck {
  id: string;
  owner_user_id: string;
  course_id: string;
  title: string;
  mode: "manual" | "generated";
  state: FlashcardDeckState;
  source_snapshot: Array<Record<string, unknown>>;
  generation_receipt: Record<string, unknown> | null;
  revision: number;
  write_epoch: number;
  created_at: number;
  updated_at: number;
  ready_at: number | null;
  archived_at: number | null;
}

export interface Flashcard {
  id: string;
  deck_id: string;
  prompt: string;
  answer: string;
  hint: string | null;
  card_type:
    | "definition"
    | "concept"
    | "comparison"
    | "application"
    | "process"
    | "recall";
  objective_ids: string[];
  citations: Array<Record<string, unknown>>;
  ordinal: number;
  revision: number;
  state: "active" | "archived";
  created_at: number;
  updated_at: number;
  archived_at: number | null;
}

export interface FlashcardSchedule {
  card_id: string;
  review_count: number;
  interval_seconds: number;
  next_review_at: number;
  last_review_id: string | null;
}

export interface FlashcardReviewSummary {
  at: number;
  total_active_cards: number;
  due_cards: number;
  completed_cards: number;
  review_count: number;
}

export interface FlashcardReview {
  id: string;
  owner_user_id: string;
  course_id: string;
  deck_id: string;
  card_id: string;
  rating: FlashcardRating;
  idempotency_key: string;
  course_write_epoch: number;
  deck_revision: number;
  card_revision: number;
  review_count: number;
  interval_seconds: number;
  was_due: boolean;
  reviewed_at: number;
  next_review_at: number;
}

export interface FlashcardDeckView {
  deck: FlashcardDeck;
  cards: Flashcard[];
  schedules: FlashcardSchedule[];
  review_summary: FlashcardReviewSummary;
}

export type FlashcardGenerationState =
  | "queued"
  | "running"
  | "awaiting_review"
  | "completed"
  | "failed"
  | "cancelling"
  | "cancelled";

export interface FlashcardSourceReceipt {
  source_id: string;
  source_revision: number;
  content_sha256: string;
}

export interface FlashcardGenerationOperation {
  id: string;
  owner_user_id: string;
  course_id: string;
  deck_id: string;
  supersedes_deck_id: string | null;
  idempotency_key: string;
  request_fingerprint: string;
  source_snapshot: FlashcardSourceReceipt[];
  objective_ids: string[];
  generation_brief: FlashcardGenerationBrief;
  origin: FlashcardGenerationOrigin;
  candidates: FlashcardCandidate[] | null;
  candidate_revision: number;
  provider_receipt: FlashcardProviderReceipt | null;
  cancel_requested_at: number | null;
  review_expires_at: number | null;
  course_write_epoch: number;
  deck_write_epoch: number;
  item_limit: number;
  context_char_limit: number;
  state: FlashcardGenerationState;
  error_code: string | null;
  created_at: number;
  started_at: number | null;
  completed_at: number | null;
  updated_at: number;
}

export type FlashcardCardType =
  | "definition"
  | "concept"
  | "comparison"
  | "application"
  | "process"
  | "recall";

export interface FlashcardGenerationBrief {
  focus: string;
  desired_count: number;
  card_type_mix: FlashcardCardType[];
  difficulty: "introductory" | "intermediate" | "advanced" | "mixed";
  answer_length: "short" | "medium";
  include_hints: boolean;
}

export interface FlashcardGenerationOrigin {
  kind: "workspace" | "chat" | "practice_remediation" | "general_chat";
  session_id: string | null;
  message_id: number | null;
  practice_attempt_id: string | null;
  selected_message_ids?: number[];
  context_sha256?: string | null;
  context_summary?: string | null;
}

export interface FlashcardProviderReceipt {
  provider: "deterministic-local" | "openai";
  requested_model: string;
  actual_model: string;
  request_id: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
}

export interface FlashcardCandidate {
  candidate_id: string;
  prompt: string;
  answer: string;
  hint: string | null;
  card_type: FlashcardCardType;
  objective_ids: string[];
  citations: Array<Record<string, unknown>>;
}

export interface FlashcardGenerationBriefReceipt {
  course_id: string;
  course_write_epoch: number;
  brief: FlashcardGenerationBrief;
  source_snapshot: FlashcardSourceReceipt[];
  objective_ids: string[];
  origin: FlashcardGenerationOrigin;
  provider_available: boolean;
  warnings: string[];
}

export interface FlashcardGenerationOptions extends FlashcardGenerationBrief {
  context_char_limit?: number;
  origin?: FlashcardGenerationOrigin;
}

export interface FlashcardGenerationRequest {
  deck_id: string;
  operation: FlashcardGenerationOperation;
}

export interface FlashcardRequestScope {
  identity: string | null;
  courseId: string | null;
  epoch: number;
  viewEpoch: number;
}

export function isCurrentFlashcardResponse(
  response: FlashcardRequestScope,
  current: FlashcardRequestScope,
): boolean {
  return (
    response.identity === current.identity &&
    response.courseId === current.courseId &&
    response.epoch === current.epoch &&
    response.viewEpoch === current.viewEpoch
  );
}

export function advanceFlashcardViewScope(
  scope: FlashcardRequestScope,
): FlashcardRequestScope {
  return { ...scope, viewEpoch: scope.viewEpoch + 1 };
}

export function flashcardProposalStorageKey(
  identity: string,
  courseId: string,
): string {
  return `teeechr:flashcard-proposal:${encodeURIComponent(identity)}:${encodeURIComponent(courseId)}`;
}

export function storeFlashcardProposal(
  identity: string,
  courseId: string,
  proposal: FlashcardGenerationBriefReceipt,
): void {
  globalThis.sessionStorage?.setItem(
    flashcardProposalStorageKey(identity, courseId),
    JSON.stringify(proposal),
  );
}

export function consumeFlashcardProposal(
  identity: string,
  courseId: string,
): FlashcardGenerationBriefReceipt | null {
  const key = flashcardProposalStorageKey(identity, courseId);
  const raw = globalThis.sessionStorage?.getItem(key);
  globalThis.sessionStorage?.removeItem(key);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as FlashcardGenerationBriefReceipt;
    return parsed.course_id === courseId ? parsed : null;
  } catch {
    return null;
  }
}

export function clearFlashcardProposal(
  identity: string | null,
  courseId: string | null,
): void {
  if (identity && courseId) {
    globalThis.sessionStorage?.removeItem(
      flashcardProposalStorageKey(identity, courseId),
    );
  }
}

/** Again keeps a missed card in the current pass; all other ratings advance. */
export function requeueAgainCard<T>(
  cards: T[],
  card: T,
  rating: FlashcardRating,
): T[] {
  return rating === "again" ? [...cards, card] : cards;
}

export function isFlashcardCourseWritable(
  state: "active" | "archived" | null | undefined,
): boolean {
  return state === "active";
}

async function json<T>(response: Response | Promise<Response>): Promise<T> {
  const resolved = await response;
  const body = await resolved.json().catch(() => ({}));
  if (!resolved.ok) {
    throw new Error(
      String(
        (body as { detail?: unknown }).detail ||
          `Request failed: ${resolved.status}`,
      ),
    );
  }
  return body as T;
}

function path(courseId: string, suffix = ""): string {
  return `/api/v1/courses/${encodeURIComponent(courseId)}/flashcards${suffix}`;
}

function mutation(body: unknown, method: "POST" | "PATCH" = "POST"): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

export async function listFlashcardDecks(
  courseId: string,
  offset = 0,
): Promise<FlashcardDeck[]> {
  const body = await json<{ flashcard_decks: FlashcardDeck[] }>(
    apiFetch(apiUrl(`${path(courseId)}?include_archived=true&limit=50&offset=${offset}`), {
      cache: "no-store",
    }),
  );
  return body.flashcard_decks;
}

export function createFlashcardDeck(
  courseId: string,
  title: string,
  courseWriteEpoch: number,
) {
  return json<FlashcardDeck>(
    apiFetch(
      apiUrl(path(courseId)),
      mutation({ title, expected_course_write_epoch: courseWriteEpoch }),
    ),
  );
}

export function getFlashcardDeck(courseId: string, deckId: string) {
  return json<FlashcardDeckView>(
    apiFetch(
      apiUrl(path(courseId, `/${encodeURIComponent(deckId)}`)),
      { cache: "no-store" },
    ),
  );
}

export function addFlashcard(
  courseId: string,
  deck: FlashcardDeck,
  courseWriteEpoch: number,
  input: { prompt: string; answer: string; objective_ids: string[] },
) {
  return json<Flashcard>(
    apiFetch(
      apiUrl(path(courseId, `/${encodeURIComponent(deck.id)}/cards`)),
      mutation({
        ...input,
        expected_deck_revision: deck.revision,
        expected_course_write_epoch: courseWriteEpoch,
      }),
    ),
  );
}

export function readyFlashcardDeck(
  courseId: string,
  deck: FlashcardDeck,
  courseWriteEpoch: number,
) {
  return json<FlashcardDeck>(
    apiFetch(
      apiUrl(path(courseId, `/${encodeURIComponent(deck.id)}/ready`)),
      mutation({
        expected_revision: deck.revision,
        expected_course_write_epoch: courseWriteEpoch,
      }),
    ),
  );
}

export function archiveOrRestoreFlashcardDeck(
  courseId: string,
  deck: FlashcardDeck,
  courseWriteEpoch: number,
) {
  const action = deck.state === "archived" ? "restore" : "archive";
  return json<FlashcardDeck>(
    apiFetch(
      apiUrl(path(courseId, `/${encodeURIComponent(deck.id)}/${action}`)),
      mutation({
        expected_revision: deck.revision,
        expected_course_write_epoch: courseWriteEpoch,
      }),
    ),
  );
}

export async function getDueFlashcards(
  courseId: string,
  deckId: string,
): Promise<FlashcardDeckView> {
  return json<FlashcardDeckView>(
    apiFetch(
      apiUrl(path(courseId, `/${encodeURIComponent(deckId)}/reviews`)),
      { cache: "no-store" },
    ),
  );
}

export function reviewFlashcard(
  courseId: string,
  deck: FlashcardDeck,
  card: Flashcard,
  rating: FlashcardRating,
  courseWriteEpoch: number,
  idempotencyKey: string,
) {
  return json<{
    review: FlashcardReview;
    schedule: FlashcardSchedule;
    review_summary: FlashcardReviewSummary;
  }>(
    apiFetch(
      apiUrl(path(courseId, `/${encodeURIComponent(deck.id)}/reviews`)),
      mutation({
        card_id: card.id,
        rating,
        idempotency_key: idempotencyKey,
        expected_deck_revision: deck.revision,
        expected_card_revision: card.revision,
        expected_course_write_epoch: courseWriteEpoch,
      }),
    ),
  );
}

function generationInput(
  title: string,
  sourceIds: string[],
  objectiveIds: string[],
  courseWriteEpoch: number,
  options?: Partial<FlashcardGenerationOptions>,
) {
  const desiredCount = options?.desired_count ?? 8;
  return {
    title,
    source_ids: sourceIds,
    objective_ids: objectiveIds,
    expected_course_write_epoch: courseWriteEpoch,
    focus: options?.focus ?? title,
    item_limit: desiredCount,
    card_type_mix: options?.card_type_mix ?? ["recall"],
    difficulty: options?.difficulty ?? "mixed",
    answer_length: options?.answer_length ?? "short",
    include_hints: options?.include_hints ?? true,
    origin: options?.origin,
    context_char_limit: options?.context_char_limit ?? 12_000,
  };
}

export function createGeneratedFlashcardDeck(
  courseId: string,
  title: string,
  sourceIds: string[],
  objectiveIds: string[],
  courseWriteEpoch: number,
  idempotencyKey: string,
  options?: Partial<FlashcardGenerationOptions>,
) {
  return json<FlashcardGenerationRequest>(
    apiFetch(
      apiUrl(`/api/v1/courses/${encodeURIComponent(courseId)}/flashcard-generation`),
      {
        ...mutation(
          generationInput(
            title,
            sourceIds,
            objectiveIds,
            courseWriteEpoch,
            options,
          ),
        ),
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": idempotencyKey,
        },
      },
    ),
  );
}

export function createGeneratedFlashcardSuccessor(
  courseId: string,
  deckId: string,
  title: string,
  sourceIds: string[],
  objectiveIds: string[],
  courseWriteEpoch: number,
  idempotencyKey: string,
  options?: Partial<FlashcardGenerationOptions>,
) {
  return json<FlashcardGenerationRequest>(
    apiFetch(
      apiUrl(
        `/api/v1/courses/${encodeURIComponent(courseId)}/flashcards/${encodeURIComponent(deckId)}/flashcard-generation`,
      ),
      {
        ...mutation(
          generationInput(
            title,
            sourceIds,
            objectiveIds,
            courseWriteEpoch,
            options,
          ),
        ),
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": idempotencyKey,
        },
      },
    ),
  );
}

export function prepareFlashcardGenerationBrief(
  courseId: string,
  title: string,
  sourceIds: string[],
  objectiveIds: string[],
  courseWriteEpoch: number,
  options?: Partial<FlashcardGenerationOptions>,
) {
  return json<FlashcardGenerationBriefReceipt>(
    apiFetch(
      apiUrl(
        `/api/v1/courses/${encodeURIComponent(courseId)}/flashcard-generation/brief`,
      ),
      mutation(
        generationInput(
          title,
          sourceIds,
          objectiveIds,
          courseWriteEpoch,
          options,
        ),
      ),
    ),
  );
}

export function publishFlashcardCandidates(
  courseId: string,
  operationId: string,
  candidateIds: string[],
  expectedCandidateRevision: number,
) {
  return json<FlashcardGenerationOperation>(
    apiFetch(
      apiUrl(
        `/api/v1/courses/${encodeURIComponent(courseId)}/flashcard-generation/${encodeURIComponent(operationId)}/publish`,
      ),
      mutation({
        candidate_ids: candidateIds,
        expected_candidate_revision: expectedCandidateRevision,
      }),
    ),
  );
}

export function cancelFlashcardGeneration(
  courseId: string,
  operationId: string,
) {
  return json<FlashcardGenerationOperation>(
    apiFetch(
      apiUrl(
        `/api/v1/courses/${encodeURIComponent(courseId)}/flashcard-generation/${encodeURIComponent(operationId)}/cancel`,
      ),
      mutation({}),
    ),
  );
}

export async function listFlashcardGenerationOperations(
  courseId: string,
): Promise<FlashcardGenerationOperation[]> {
  const body = await json<{ operations: FlashcardGenerationOperation[] }>(
    apiFetch(
      apiUrl(
        `/api/v1/courses/${encodeURIComponent(courseId)}/flashcard-generation`,
      ),
      { cache: "no-store" },
    ),
  );
  return body.operations;
}
