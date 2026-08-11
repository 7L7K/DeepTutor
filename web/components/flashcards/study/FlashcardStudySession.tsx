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
  currentIndex: number;
  cardCount: number;
  completedIndexes?: readonly number[];
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
  onNavigate?: (index: number) => void;
  reviewMode?: boolean;
}

/**
 * Presentational, controlled study surface. Its parent remains responsible for
 * loading cards, recording ratings, and keeping the durable scheduler current.
 */
export function FlashcardStudySession({
  card,
  cardsLeft,
  reviewedCards,
  currentIndex,
  cardCount,
  completedIndexes = [],
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
  onNavigate,
  reviewMode = false,
}: FlashcardStudySessionProps) {
  const { t } = useTranslation();
  const completed = new Set(completedIndexes);

  if (complete) {
    return (
      <section
        aria-label={t(reviewMode ? "Review complete" : "Study complete")}
        className="space-y-4 rounded-xl border border-[var(--border)] bg-[var(--card)] p-5"
      >
        <div>
          <p className="text-sm text-[var(--muted-foreground)]">
            {t(cardsLeftLabel(cardsLeft))}
          </p>
          <h2 className="mt-1 text-xl font-semibold">
            {t(reviewMode ? "Review complete" : "Study complete")}
          </h2>
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
              {t(reviewMode ? "Keep reviewing" : "Keep studying")}
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
      className="mx-auto w-full max-w-3xl space-y-6 rounded-[28px] border border-[var(--border)] bg-[var(--background)] p-6 shadow-[0_18px_50px_rgba(0,0,0,0.14)] sm:min-h-[420px] sm:p-9"
    >
      <div className="flex items-center justify-between gap-3 text-sm text-[var(--muted-foreground)]">
        <span>
          {t("Card")} {currentIndex + 1} {t("of")} {cardCount}
        </span>
        <span aria-live="polite">{t(cardsLeftLabel(cardsLeft))}</span>
      </div>

      <nav
        aria-label={t("Flashcard navigation")}
        className="flex flex-wrap justify-center gap-2"
      >
        {Array.from({ length: cardCount }, (_, index) => {
          const isCurrent = index === currentIndex;
          const isCompleted = completed.has(index);
          return (
            <button
              key={index}
              type="button"
              aria-current={isCurrent ? "step" : undefined}
              aria-label={
                isCompleted
                  ? t("Card {{number}} completed", { number: index + 1 })
                  : t("Go to card {{number}}", { number: index + 1 })
              }
              disabled={busy || isCompleted}
              onClick={() => onNavigate?.(index)}
              className={`flex h-9 w-9 items-center justify-center rounded-full border text-sm transition ${
                isCurrent
                  ? "border-[var(--primary)] bg-[var(--primary)] text-[var(--primary-foreground)]"
                  : isCompleted
                    ? "border-transparent bg-[var(--secondary)] text-[var(--muted-foreground)] opacity-55"
                    : "border-[var(--border)] hover:border-[var(--primary)]"
              } disabled:cursor-default`}
            >
              {index + 1}
            </button>
          );
        })}
      </nav>

      <div className="flex min-h-44 flex-col justify-center space-y-3 border-y border-[var(--border)] py-8 text-center sm:min-h-56">
        <h2 className="text-sm font-medium text-[var(--muted-foreground)]">
          {t("Question")}
        </h2>
        <p className="text-xl font-medium leading-relaxed sm:text-2xl">
          {card.prompt}
        </p>
      </div>

      {!answerVisible ? (
        <div className="flex flex-wrap justify-center gap-2">
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
          <div className="space-y-2 rounded-2xl bg-[var(--secondary)] p-5 text-center">
            <h2 className="text-sm font-medium text-[var(--muted-foreground)]">
              {t("Answer")}
            </h2>
            <p>{card.answer}</p>
          </div>
          <div className="mx-auto grid w-full max-w-lg gap-2 sm:grid-cols-2">
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
