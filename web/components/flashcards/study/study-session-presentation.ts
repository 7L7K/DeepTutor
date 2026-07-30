import type { FlashcardRating } from "../../../lib/flashcards-api";

/** The only learner-facing review choices in a focused study session. */
export type StudySessionRating = Extract<FlashcardRating, "again" | "good">;

export const studySessionActions: Readonly<{
  gotIt: StudySessionRating;
  studyAgain: StudySessionRating;
}> = {
  gotIt: "good",
  studyAgain: "again",
};

export function cardsLeftLabel(cardsLeft: number): string {
  const safeCardsLeft = Math.max(0, Math.floor(cardsLeft));
  return `${safeCardsLeft} ${safeCardsLeft === 1 ? "card" : "cards"} left`;
}

export function completedCardsLabel(reviewedCards: number): string {
  const safeReviewedCards = Math.max(0, Math.floor(reviewedCards));
  return `You reviewed ${safeReviewedCards} ${safeReviewedCards === 1 ? "card" : "cards"}.`;
}

/** Find the next unfinished card after an arbitrary learner navigation jump. */
export function nextIncompleteStudyIndex(
  totalCards: number,
  completedIndexes: ReadonlySet<number>,
  currentIndex: number,
): number {
  const safeTotal = Math.max(0, Math.floor(totalCards));
  if (!safeTotal || completedIndexes.size >= safeTotal) return safeTotal;
  for (let offset = 1; offset <= safeTotal; offset += 1) {
    const candidate = (currentIndex + offset) % safeTotal;
    if (!completedIndexes.has(candidate)) return candidate;
  }
  return safeTotal;
}
