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
  | "completed"
  | "failed";

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
) {
  return {
    title,
    source_ids: sourceIds,
    objective_ids: objectiveIds,
    expected_course_write_epoch: courseWriteEpoch,
    item_limit: 8,
    context_char_limit: 12_000,
  };
}

export function createGeneratedFlashcardDeck(
  courseId: string,
  title: string,
  sourceIds: string[],
  objectiveIds: string[],
  courseWriteEpoch: number,
  idempotencyKey: string,
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
