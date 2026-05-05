import { apiFetch } from "@/lib/api";

export type FlashcardSource = "topic" | "knowledge";
export type FlashcardStyle = "mixed" | "definition" | "concept";
export type FlashcardRating = "new" | "got_it" | "missed" | "skipped";
export type FlashcardReviewMode = "full_deck" | "missed_only";

interface ApiFlashcardCard {
  id: string;
  front: string;
  back: string;
  hint?: string;
  tag?: string;
  source_ref?: string;
}

interface ApiFlashcardDeck {
  id: string;
  source_type: FlashcardSource;
  title: string;
  topic: string;
  source_summary: string;
  source_kb_names: string[];
  style: FlashcardStyle;
  card_count: number;
  generation_settings?: {
    status?: string;
    requested_count?: number;
    ready_count?: number;
    progressive?: boolean;
  };
  created_at: number;
  updated_at: number;
  last_reviewed_at?: number | null;
  cards?: ApiFlashcardCard[];
  summary?: {
    ratings?: Record<string, { rating?: FlashcardRating; reviewed_at?: number }>;
    counts?: Partial<Record<FlashcardRating, number>>;
    remaining?: number;
  };
  latest_session_review?: ApiFlashcardSessionReview | null;
}

interface ApiFlashcardSessionReview {
  id: string;
  deck_id: string;
  review_mode: FlashcardReviewMode;
  card_ids: string[];
  cards_reviewed: number;
  got_it_count: number;
  missed_count: number;
  skipped_count: number;
  analysis_summary: string;
  analysis_strengths: string[];
  analysis_weak_spots: string[];
  analysis_recommended_next_step: string;
  analysis_focus_topics: string[];
  created_at: number;
}

export interface FlashcardCard {
  id: string;
  front: string;
  back: string;
  hint?: string;
  tag: string;
  sourceRef?: string;
}

export interface FlashcardDeck {
  id: string;
  sourceType: FlashcardSource;
  title: string;
  topic: string;
  sourceSummary: string;
  sourceKbNames: string[];
  style: FlashcardStyle;
  cardCount: number;
  generationStatus: string;
  requestedCardCount: number;
  readyCardCount: number;
  createdAt: number;
  updatedAt: number;
  lastReviewedAt?: number | null;
  cards: FlashcardCard[];
  summary: {
    ratings: Record<string, { rating: FlashcardRating; reviewedAt?: number }>;
    counts: Record<FlashcardRating, number>;
    remaining: number;
  };
  latestSessionReview?: FlashcardSessionReview | null;
}

export interface FlashcardSessionReview {
  id: string;
  deckId: string;
  reviewMode: FlashcardReviewMode;
  cardIds: string[];
  cardsReviewed: number;
  gotItCount: number;
  missedCount: number;
  skippedCount: number;
  analysisSummary: string;
  analysisStrengths: string[];
  analysisWeakSpots: string[];
  analysisRecommendedNextStep: string;
  analysisFocusTopics: string[];
  createdAt: number;
}

async function expectJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail = `Request failed: ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body?.detail) detail = body.detail;
    } catch {
      // Use default detail.
    }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

function normalizeDeck(deck: ApiFlashcardDeck): FlashcardDeck {
  const cards = (deck.cards ?? []).map((card) => ({
    id: card.id,
    front: card.front,
    back: card.back,
    hint: card.hint || undefined,
    tag: card.tag || "Recall",
    sourceRef: card.source_ref || undefined,
  }));
  const counts = {
    new: deck.summary?.counts?.new ?? cards.length,
    got_it: deck.summary?.counts?.got_it ?? 0,
    missed: deck.summary?.counts?.missed ?? 0,
    skipped: deck.summary?.counts?.skipped ?? 0,
  };
  const ratings = Object.fromEntries(
    Object.entries(deck.summary?.ratings ?? {}).map(([cardId, value]) => [
      cardId,
      {
        rating: (value?.rating || "new") as FlashcardRating,
        reviewedAt: value?.reviewed_at,
      },
    ]),
  );
  const generationSettings = deck.generation_settings ?? {};
  const requestedCardCount = Number(generationSettings.requested_count ?? deck.card_count ?? cards.length);
  const readyCardCount = Number(generationSettings.ready_count ?? cards.length);
  return {
    id: deck.id,
    sourceType: deck.source_type,
    title: deck.title,
    topic: deck.topic,
    sourceSummary: deck.source_summary,
    sourceKbNames: deck.source_kb_names ?? [],
    style: deck.style,
    cardCount: deck.card_count,
    generationStatus: generationSettings.status || "complete",
    requestedCardCount,
    readyCardCount,
    createdAt: deck.created_at,
    updatedAt: deck.updated_at,
    lastReviewedAt: deck.last_reviewed_at,
    cards,
    summary: {
      ratings,
      counts,
      remaining: deck.summary?.remaining ?? counts.new,
    },
    latestSessionReview: deck.latest_session_review
      ? normalizeSessionReview(deck.latest_session_review)
      : null,
  };
}

function normalizeSessionReview(review: ApiFlashcardSessionReview): FlashcardSessionReview {
  return {
    id: review.id,
    deckId: review.deck_id,
    reviewMode: review.review_mode,
    cardIds: review.card_ids ?? [],
    cardsReviewed: review.cards_reviewed,
    gotItCount: review.got_it_count,
    missedCount: review.missed_count,
    skippedCount: review.skipped_count,
    analysisSummary: review.analysis_summary || "",
    analysisStrengths: review.analysis_strengths ?? [],
    analysisWeakSpots: review.analysis_weak_spots ?? [],
    analysisRecommendedNextStep: review.analysis_recommended_next_step || "",
    analysisFocusTopics: review.analysis_focus_topics ?? [],
    createdAt: review.created_at,
  };
}

export async function createFlashcardDeck(payload: {
  sourceType: FlashcardSource;
  topic: string;
  knowledgeBaseNames: string[];
  cardCount: number;
  style: FlashcardStyle;
  reuseExisting?: boolean;
}): Promise<{ deck: FlashcardDeck; reusedExisting: boolean }> {
  const response = await apiFetch("/api/v1/practice/flashcards/generate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      source_type: payload.sourceType,
      topic: payload.topic,
      knowledge_base_names: payload.knowledgeBaseNames,
      card_count: payload.cardCount,
      style: payload.style,
      reuse_existing: payload.reuseExisting ?? true,
    }),
  });
  const data = await expectJson<{ deck: ApiFlashcardDeck; reused_existing: boolean }>(response);
  return {
    deck: normalizeDeck(data.deck),
    reusedExisting: data.reused_existing,
  };
}

export async function listFlashcardDecks(limit = 12, offset = 0): Promise<FlashcardDeck[]> {
  const response = await apiFetch(`/api/v1/practice/flashcards/decks?limit=${limit}&offset=${offset}`, {
    cache: "no-store",
  });
  const data = await expectJson<{ decks: ApiFlashcardDeck[] }>(response);
  return (data.decks ?? []).map(normalizeDeck);
}

export async function getFlashcardDeck(deckId: string): Promise<FlashcardDeck> {
  const response = await apiFetch(`/api/v1/practice/flashcards/decks/${deckId}`, {
    cache: "no-store",
  });
  const data = await expectJson<{ deck: ApiFlashcardDeck }>(response);
  return normalizeDeck(data.deck);
}

export async function reviewFlashcardCard(
  deckId: string,
  cardId: string,
  rating: Exclude<FlashcardRating, "new">,
): Promise<FlashcardDeck> {
  const response = await apiFetch(`/api/v1/practice/flashcards/decks/${deckId}/reviews`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ card_id: cardId, rating }),
  });
  const data = await expectJson<{ deck: ApiFlashcardDeck }>(response);
  return normalizeDeck(data.deck);
}

export async function resetFlashcardDeckReviews(deckId: string): Promise<FlashcardDeck> {
  const response = await apiFetch(`/api/v1/practice/flashcards/decks/${deckId}/restart`, {
    method: "POST",
  });
  const data = await expectJson<{ deck: ApiFlashcardDeck }>(response);
  return normalizeDeck(data.deck);
}

export async function completeFlashcardPass(
  deckId: string,
  payload: { reviewMode: FlashcardReviewMode; cardIds: string[] },
): Promise<{ deck: FlashcardDeck; sessionReview: FlashcardSessionReview }> {
  const response = await apiFetch(`/api/v1/practice/flashcards/decks/${deckId}/complete`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      review_mode: payload.reviewMode,
      card_ids: payload.cardIds,
    }),
  });
  const data = await expectJson<{
    deck: ApiFlashcardDeck;
    session_review: ApiFlashcardSessionReview;
  }>(response);
  return {
    deck: normalizeDeck(data.deck),
    sessionReview: normalizeSessionReview(data.session_review),
  };
}

export async function getFlashcardTopicSuggestions(payload: {
  knowledgeBaseNames: string[];
  hint?: string;
}): Promise<string[]> {
  const response = await apiFetch("/api/v1/practice/flashcards/topic-suggestions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      knowledge_base_names: payload.knowledgeBaseNames,
      hint: payload.hint ?? "",
    }),
  });
  const data = await expectJson<{ suggestions: string[] }>(response);
  return Array.isArray(data.suggestions) ? data.suggestions : [];
}
