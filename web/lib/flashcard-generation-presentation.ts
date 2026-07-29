const DEFAULT_UNAVAILABLE_REASON =
  "Grounded generation is not enabled on this server";
const MANUAL_FALLBACK = "Manual Flashcards remain available.";

export function flashcardGenerationUnavailableCopy(
  reason: string | null | undefined,
): string {
  const normalized = reason?.trim().replace(/[.\s]+$/, "");
  if (!normalized) {
    return `${DEFAULT_UNAVAILABLE_REASON}. ${MANUAL_FALLBACK}`;
  }
  if (normalized.includes(MANUAL_FALLBACK.replace(/\.$/, ""))) {
    return `${normalized}.`;
  }
  return `${normalized}. ${MANUAL_FALLBACK}`;
}
