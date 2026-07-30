"use client";

import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import type { Flashcard } from "@/lib/flashcards-api";
import {
  cardsLeftLabel,
  completedCardsLabel,
  studySessionActions,
  type StudySessionRating,
} from "./study-session-presentation";

type StudyCard = Pick<Flashcard, "id" | "prompt" | "answer" | "hint">;

export interface FlashcardStudySessionProps {
  /** The current due card, or null once the parent has completed the pass. */
  card: StudyCard | null;
  /** Includes the current card while it is being studied. */
  cardsLeft: number;
  reviewedCards: number;
  answerVisible: boolean;
  hintVisible?: boolean;
  sourceVisible?: boolean;
  sourceDisclosure?: ReactNode;
  busy?: boolean;
  complete?: boolean;
  onReveal: () => void;
  onRate: (rating: StudySessionRating) => void;
  onHintVisibilityChange?: (visible: boolean) => void;
  onSourceVisibilityChange?: (visible: boolean) => void;
  onDone?: () => void;
  onKeepStudying?: () => void;
}

/**
 * Presentational, controlled study surface. Its parent remains responsible for
 * loading cards, recording ratings, and keeping the durable scheduler current.
 */
export function FlashcardStudySession({
  card,
  cardsLeft,
  reviewedCards,
  answerVisible,
  hintVisible = false,
  sourceVisible = false,
  sourceDisclosure,
  busy = false,
  complete = false,
  onReveal,
  onRate,
  onHintVisibilityChange,
  onSourceVisibilityChange,
  onDone,
  onKeepStudying,
}: FlashcardStudySessionProps) {
  const { t } = useTranslation();

  if (complete) {
    return (
      <section
        aria-label={t("Study complete")}
        className="space-y-4 rounded-xl border border-[var(--border)] bg-[var(--card)] p-5"
      >
        <div>
          <p className="text-sm text-[var(--muted-foreground)]">
            {t(cardsLeftLabel(cardsLeft))}
          </p>
          <h2 className="mt-1 text-xl font-semibold">{t("Study complete")}</h2>
          <p className="mt-2 text-sm text-[var(--muted-foreground)]">
            {t(completedCardsLabel(reviewedCards))}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {onDone ? (
            <button
              type="button"
              disabled={busy}
              onClick={onDone}
              className="rounded-lg bg-[var(--primary)] px-3 py-2 text-sm text-[var(--primary-foreground)] disabled:opacity-50"
            >
              {t("Done")}
            </button>
          ) : null}
          {onKeepStudying ? (
            <button
              type="button"
              disabled={busy}
              onClick={onKeepStudying}
              className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm disabled:opacity-50"
            >
              {t("Keep studying")}
            </button>
          ) : null}
        </div>
      </section>
    );
  }

  if (!card) return null;

  return (
    <section
      aria-label={t("Flashcard study session")}
      className="space-y-4 rounded-xl border border-[var(--border)] bg-[var(--card)] p-5"
    >
      <div className="flex items-center justify-between gap-3 text-sm text-[var(--muted-foreground)]">
        <span>{t("Study session")}</span>
        <span aria-live="polite">{t(cardsLeftLabel(cardsLeft))}</span>
      </div>

      <div className="space-y-2">
        <h2 className="text-sm font-medium text-[var(--muted-foreground)]">
          {t("Question")}
        </h2>
        <p className="text-lg font-medium">{card.prompt}</p>
      </div>

      {!answerVisible ? (
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            disabled={busy}
            onClick={onReveal}
            className="rounded-lg bg-[var(--primary)] px-3 py-2 text-sm text-[var(--primary-foreground)] disabled:opacity-50"
          >
            {t("Show answer")}
          </button>
          {card.hint && onHintVisibilityChange ? (
            <button
              type="button"
              disabled={busy}
              aria-expanded={hintVisible}
              onClick={() => onHintVisibilityChange(!hintVisible)}
              className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm disabled:opacity-50"
            >
              {hintVisible ? t("Hide hint") : t("Give me a hint")}
            </button>
          ) : null}
        </div>
      ) : null}

      {!answerVisible && hintVisible && card.hint ? (
        <aside className="rounded-lg bg-[var(--secondary)] p-3 text-sm">
          <span className="font-medium">{t("Hint:")} </span>
          {card.hint}
        </aside>
      ) : null}

      {answerVisible ? (
        <>
          <div className="space-y-2 rounded-lg bg-[var(--secondary)] p-4">
            <h2 className="text-sm font-medium text-[var(--muted-foreground)]">
              {t("Answer")}
            </h2>
            <p>{card.answer}</p>
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            <button
              type="button"
              disabled={busy}
              onClick={() => onRate(studySessionActions.gotIt)}
              className="rounded-lg bg-[var(--primary)] px-3 py-2 text-sm text-[var(--primary-foreground)] disabled:opacity-50"
            >
              {t("Got it")}
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => onRate(studySessionActions.studyAgain)}
              className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm disabled:opacity-50"
            >
              {t("Study again")}
            </button>
          </div>
          {sourceDisclosure && onSourceVisibilityChange ? (
            <div className="space-y-2">
              <button
                type="button"
                disabled={busy}
                aria-expanded={sourceVisible}
                onClick={() => onSourceVisibilityChange(!sourceVisible)}
                className="text-sm text-[var(--muted-foreground)] underline underline-offset-4 disabled:opacity-50"
              >
                {sourceVisible ? t("Hide source") : t("Show source")}
              </button>
              {sourceVisible ? (
                <aside className="rounded-lg border border-[var(--border)] p-3 text-sm">
                  {sourceDisclosure}
                </aside>
              ) : null}
            </div>
          ) : null}
        </>
      ) : null}
    </section>
  );
}
