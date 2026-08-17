"use client";

import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import type { Flashcard } from "@/lib/flashcards-api";
import {
  cardsLeftLabel,
  studySessionActions,
  type StudySessionRating,
} from "./study-session-presentation";

type StudyCard = Pick<
  Flashcard,
  "id" | "prompt" | "answer" | "hint" | "edited_by_user"
>;

export interface FlashcardStudySessionProps {
  /** The current due card, or null once the parent has completed the pass. */
  card: StudyCard | null;
  /** Includes the current card while it is being studied. */
  cardsLeft: number;
  reviewedCards: number;
  rememberedCards?: number;
  missedCards?: number;
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
  onStudyDeckAgain?: () => void;
  onPracticeMissed?: () => void;
  onNewDeck?: () => void;
  onEdit?: () => void;
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
  rememberedCards,
  missedCards = 0,
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
  onStudyDeckAgain,
  onPracticeMissed,
  onNewDeck,
  onEdit,
  onNavigate,
  reviewMode = false,
}: FlashcardStudySessionProps) {
  const { t } = useTranslation();
  const completed = new Set(completedIndexes);
  const navigation = (
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
  );

  if (complete) {
    return (
      <section
        aria-label={t(reviewMode ? "Flashcards complete" : "Study complete")}
        className="space-y-4 rounded-xl border border-[var(--border)] bg-[var(--card)] p-5"
      >
        <div>
          <p className="text-sm text-[var(--muted-foreground)]">
            {t(cardsLeftLabel(cardsLeft))}
          </p>
          <h2 className="mt-1 text-xl font-semibold">
            {t(reviewMode ? "Flashcards complete" : "Study complete")}
          </h2>
          <p className="mt-2 text-sm text-[var(--muted-foreground)]">
            {t(
              "You remembered {{count}} cards.",
              { count: rememberedCards ?? reviewedCards },
            )}
          </p>
          {missedCards > 0 ? (
            <p className="mt-1 text-sm text-[var(--muted-foreground)]">
              {t("{{count}} cards need practice.", { count: missedCards })}
            </p>
          ) : null}
        </div>
        <div className="flex flex-wrap gap-2">
          {onPracticeMissed && missedCards > 0 ? (
            <button
              type="button"
              disabled={busy}
              onClick={onPracticeMissed}
              className="rounded-lg bg-[var(--primary)] px-3 py-2 text-sm text-[var(--primary-foreground)] disabled:opacity-50"
            >
              {t("Practice missed cards")}
            </button>
          ) : null}
          {onStudyDeckAgain || onKeepStudying ? (
            <button
              type="button"
              disabled={busy}
              onClick={onStudyDeckAgain ?? onKeepStudying}
              className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm disabled:opacity-50"
            >
              {t("Study this deck again")}
            </button>
          ) : null}
          {onNewDeck ? (
            <button
              type="button"
              disabled={busy}
              onClick={onNewDeck}
              className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm disabled:opacity-50"
            >
              {t("Start a new deck")}
            </button>
          ) : null}
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
        </div>
      </section>
    );
  }

  if (!card) return null;

  return (
    <section
      aria-label={t("Flashcard study session")}
      className="flex min-h-[calc(100dvh-10rem)] w-full flex-col gap-6 border-0 bg-transparent p-0 sm:gap-8"
    >
      {!answerVisible ? (
        <>
          <button
            type="button"
            disabled={busy}
            aria-label={t("Reveal answer")}
            onClick={onReveal}
            className="group flex min-h-[clamp(20rem,58vh,34rem)] w-full flex-col justify-between rounded-2xl border border-[var(--border)] bg-[var(--card)] p-6 text-left transition hover:border-[var(--primary)] hover:shadow-[0_12px_28px_rgba(0,0,0,0.1)] disabled:cursor-default disabled:opacity-50 sm:p-10 lg:p-14"
          >
            <span className="text-xs font-semibold uppercase tracking-[0.16em] text-[var(--muted-foreground)]">
              {t("Question")}
            </span>
            <span className="max-w-5xl text-2xl font-medium leading-tight sm:text-4xl lg:text-5xl">
              {card.prompt}
            </span>
            <span className="inline-flex self-start rounded-lg bg-[var(--primary)] px-4 py-2.5 text-sm font-medium text-[var(--primary-foreground)] transition group-hover:brightness-105">
              {t("Reveal answer")}
            </span>
          </button>
          <div className="flex flex-wrap items-center gap-2">
            {card.hint && onHintVisibilityChange ? (
              <button
                type="button"
                disabled={busy}
                aria-expanded={hintVisible}
                onClick={() => onHintVisibilityChange(!hintVisible)}
                className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm text-[var(--muted-foreground)] hover:border-[var(--primary)] disabled:opacity-50"
              >
                {hintVisible ? t("Hide hint") : t("Give me a hint")}
              </button>
            ) : null}
            {onEdit ? (
              <button
                type="button"
                disabled={busy}
                onClick={onEdit}
                className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm text-[var(--muted-foreground)] hover:border-[var(--primary)] disabled:opacity-50"
              >
                {t("Edit card")}
              </button>
            ) : null}
          </div>
          {!answerVisible ? navigation : null}
        </>
      ) : null}

      {!answerVisible && hintVisible && card.hint ? (
        <aside className="rounded-lg bg-[var(--secondary)] p-3 text-sm">
          <span className="font-medium">{t("Hint:")} </span>
          {card.hint}
        </aside>
      ) : null}

      {answerVisible ? (
        <>
          <div
            aria-live="polite"
            className="flex min-h-[clamp(16rem,42vh,28rem)] w-full flex-col items-center justify-center gap-4 rounded-2xl border border-[var(--border)] bg-[var(--secondary)] p-6 text-center sm:p-10 lg:p-14"
          >
            <h2 className="text-xs font-semibold uppercase tracking-[0.16em] text-[var(--muted-foreground)]">
              {t("Answer")}
            </h2>
            <p className="max-w-5xl text-xl leading-relaxed sm:text-3xl">
              {card.answer}
            </p>
          </div>
          {navigation}
          {card.edited_by_user ? (
            <p className="text-center text-xs font-medium text-[var(--muted-foreground)]">
              {t("Edited by you")}
            </p>
          ) : null}
          {onEdit ? (
            <button
              type="button"
              disabled={busy}
              onClick={onEdit}
              className="mx-auto rounded-lg border border-[var(--border)] px-3 py-2 text-sm text-[var(--muted-foreground)] hover:border-[var(--primary)] disabled:opacity-50"
            >
              {t("Edit card")}
            </button>
          ) : null}
          <div className="mx-auto grid w-full max-w-3xl gap-2 sm:grid-cols-3">
            <button
              type="button"
              disabled={busy}
              onClick={() => onRate(studySessionActions.knewIt)}
              className="rounded-lg bg-[var(--primary)] px-3 py-2 text-sm text-[var(--primary-foreground)] disabled:opacity-50"
            >
              {t("I knew it")}
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => onRate(studySessionActions.almost)}
              className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm disabled:opacity-50"
            >
              {t("Almost")}
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => onRate(studySessionActions.practiceAgain)}
              className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm disabled:opacity-50"
            >
              {t("Practice again")}
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
