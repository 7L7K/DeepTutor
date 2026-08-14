export type FlashcardSource = "topic" | "knowledge";
export type FlashcardReviewMode = "full_deck" | "missed_only";

interface FlashcardDeckSourceSummary {
  sourceType: FlashcardSource;
  sourceSummary: string;
  sourceKbNames: string[];
}

export function getSourceTrustBadge(sourceType: FlashcardSource): { label: string; detail: string; tone: "grounded" | "starter" } {
  if (sourceType === "knowledge") {
    return {
      label: "Grounded source",
      detail: "Built from selected Knowledge excerpts",
      tone: "grounded",
    };
  }
  return {
    label: "Topic starter",
    detail: "AI-generated from the topic prompt",
    tone: "starter",
  };
}

export function getDeckSourceBadges(deck: FlashcardDeckSourceSummary): string[] {
  const trustBadge = getSourceTrustBadge(deck.sourceType);
  return [
    `${trustBadge.label}: ${deck.sourceSummary}`,
    ...deck.sourceKbNames.map((name) => `KB: ${name}`),
  ];
}

export function getCompletionTitle(reviewMode: FlashcardReviewMode): string {
  return reviewMode === "missed_only" ? "Missed review complete" : "Deck complete";
}

export function getCompletionNudge(reviewMode: FlashcardReviewMode, missedCount: number): string {
  if (reviewMode === "missed_only" && missedCount === 0) {
    return "You cleared the missed-card pass. The coach review is saved on this deck.";
  }
  if (reviewMode === "missed_only") {
    return "This missed-card pass is saved. Keep the next loop narrow until the misses are gone.";
  }
  return "This full-deck pass is saved. Use Review missed only for a deliberate second loop.";
}
