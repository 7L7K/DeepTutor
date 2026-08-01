import type { FlashcardGenerationState } from "./flashcards-api";

const DEFAULT_UNAVAILABLE_REASON =
  "Grounded generation is not enabled on this server";
const MANUAL_FALLBACK = "Manual Flashcards remain available.";

export type FlashcardsView = "study" | "create" | "activity";

export type FlashcardCreateMode = "choose" | "grounded" | "manual";

export type GroundedCreateStage =
  | "editing"
  | "confirming"
  | "generating"
  | "publishing";

export interface FlashcardsViewPresentation {
  label: string;
}

export const FLASHCARDS_VIEW_PRESENTATION: Readonly<
  Record<FlashcardsView, FlashcardsViewPresentation>
> = {
  study: { label: "Study" },
  create: { label: "Create" },
  activity: { label: "Activity" },
};

/** Query state is presentation-only, so an unknown value safely returns Study. */
export function flashcardsViewFromQuery(
  view: string | null | undefined,
): FlashcardsView {
  if (view === "create" || view === "activity" || view === "study") {
    return view;
  }
  return "study";
}

export type FlashcardGenerationOperationKind =
  | "active"
  | "review"
  | "completed"
  | "recovery"
  | "cancelled";

export interface FlashcardGenerationStatePresentation {
  label: string;
  description: string;
  kind: FlashcardGenerationOperationKind;
}

const GENERATION_STATE_PRESENTATION: Readonly<
  Record<FlashcardGenerationState, FlashcardGenerationStatePresentation>
> = {
  queued: {
    label: "Waiting to start",
    description: "Your card request is waiting to start.",
    kind: "active",
  },
  running: {
    label: "Creating cards",
    description: "TEEECHR is creating your cards. You can leave this page.",
    kind: "active",
  },
  awaiting_review: {
    label: "Finishing your cards",
    description: "Your cards passed validation and are being saved.",
    kind: "review",
  },
  completed: {
    label: "Cards published",
    description: "Your selected cards are ready to study.",
    kind: "completed",
  },
  failed: {
    label: "Needs your attention",
    description: "Your card request is ready to review or update.",
    kind: "recovery",
  },
  cancelling: {
    label: "Cancelling creation",
    description: "TEEECHR is stopping this card request.",
    kind: "active",
  },
  cancelled: {
    label: "Creation cancelled",
    description: "This card request was cancelled.",
    kind: "cancelled",
  },
};

export function flashcardGenerationStatePresentation(
  state: FlashcardGenerationState,
): FlashcardGenerationStatePresentation {
  return GENERATION_STATE_PRESENTATION[state];
}

/**
 * These categories are deliberately learner-safe. Backend failure codes remain
 * diagnostics and never become the primary learner-facing text.
 */
export type FlashcardGenerationFailureCategory =
  | "unavailable"
  | "interrupted"
  | "request-needs-update"
  | "card-quality"
  | "limit-reached"
  | "cancelled"
  | "unknown";

export function flashcardGenerationFailureCategory(
  errorCode: string | null | undefined,
): FlashcardGenerationFailureCategory {
  switch (errorCode) {
    case "provider_unavailable":
    case "configuration_error":
      return "unavailable";
    case "provider_failed":
    case "provider_timed_out":
    case "interrupted":
      return "interrupted";
    case "source_changed":
    case "authority_changed":
      return "request-needs-update";
    case "invalid_output":
    case "insufficient_valid_cards":
      return "card-quality";
    case "quota_exceeded":
      return "limit-reached";
    case "cancelled":
      return "cancelled";
    default:
      return "unknown";
  }
}

export type FlashcardGenerationRecoveryAction =
  | "try-again"
  | "change-request"
  | "create-manually"
  | "none";

export interface FlashcardGenerationFailurePresentation {
  title: string;
  detail: string;
  category: FlashcardGenerationFailureCategory;
  primaryAction: FlashcardGenerationRecoveryAction;
}

const FAILURE_TITLE = "We could not create these cards.";
const REQUEST_PRESERVED = "Your request is still here.";

const FAILURE_DETAIL: Readonly<
  Record<FlashcardGenerationFailureCategory, string>
> = {
  unavailable: "Card generation is unavailable right now. You can create cards manually.",
  interrupted: REQUEST_PRESERVED,
  "request-needs-update": "Your Course materials changed. Review your request before creating cards.",
  "card-quality": "This request needs an update before TEEECHR can create useful cards.",
  "limit-reached": "Card generation is unavailable right now. You can create cards manually.",
  cancelled: "This card request was cancelled.",
  unknown: REQUEST_PRESERVED,
};

/**
 * Retry permission comes from the server's explicit safety decision. Never
 * infer it from a provider failure code: an uncertain provider response must
 * not be retried automatically or presented as safe to retry.
 */
export function flashcardGenerationFailurePresentation(
  errorCode: string | null | undefined,
  retryAllowed: boolean | null | undefined,
): FlashcardGenerationFailurePresentation {
  const category = flashcardGenerationFailureCategory(errorCode);
  const primaryAction: FlashcardGenerationRecoveryAction =
    category === "cancelled"
      ? "none"
      : category === "unavailable" || category === "limit-reached"
        ? "create-manually"
        : retryAllowed === true
          ? "try-again"
          : "change-request";

  return {
    title: category === "cancelled" ? "Card creation cancelled." : FAILURE_TITLE,
    detail: FAILURE_DETAIL[category],
    category,
    primaryAction,
  };
}

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

/** Keep import implementation names out of the learner-facing source picker. */
export function flashcardCourseSourceLabel(
  displayName: string | null | undefined,
  kind: string | null | undefined,
): string {
  const name = displayName?.trim() ?? "";
  const technicalIdentity = `${kind ?? ""} ${name}`.toLowerCase();
  if (
    technicalIdentity.includes("blueway") &&
    technicalIdentity.includes("course") &&
    technicalIdentity.includes("bundle")
  ) {
    return "Imported BlueWay Course material";
  }
  return name || "Course material";
}
