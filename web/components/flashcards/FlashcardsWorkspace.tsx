"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Archive,
  CheckCircle2,
  Eye,
  GalleryVerticalEnd,
  Loader2,
  Play,
  RotateCcw,
  Save,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { CourseBar } from "@/components/courses/CourseBar";
import { useCourses } from "@/context/CourseContext";
import { fetchAuthStatus } from "@/lib/auth";
import {
  addFlashcard,
  advanceFlashcardViewScope,
  archiveOrRestoreFlashcardDeck,
  createFlashcardDeck,
  getDueFlashcards,
  getFlashcardDeck,
  isFlashcardCourseWritable,
  isCurrentFlashcardResponse,
  listFlashcardDecks,
  readyFlashcardDeck,
  requeueAgainCard,
  reviewFlashcard,
  type Flashcard,
  type FlashcardDeck,
  type FlashcardDeckView,
  type FlashcardRating,
  type FlashcardRequestScope,
} from "@/lib/flashcards-api";

const emptyCard = { prompt: "", answer: "", objectiveIds: "" };

function idempotencyKey(): string {
  return (
    globalThis.crypto?.randomUUID?.() ??
    `flashcard-${Date.now()}-${Math.random().toString(36).slice(2)}`
  );
}

function errorText(cause: unknown): string {
  return cause instanceof Error ? cause.message : "Flashcard request failed";
}

export default function FlashcardsWorkspace() {
  const { t } = useTranslation();
  const { activeCourse, refresh: refreshCourses } = useCourses();
  const [identity, setIdentity] = useState<string | null>(null);
  const [decks, setDecks] = useState<FlashcardDeck[]>([]);
  const [selectedDeckId, setSelectedDeckId] = useState<string | null>(null);
  const [view, setView] = useState<FlashcardDeckView | null>(null);
  const [deckTitle, setDeckTitle] = useState("");
  const [cardDraft, setCardDraft] = useState(emptyCard);
  const [reviewCards, setReviewCards] = useState<Flashcard[]>([]);
  const [reviewIndex, setReviewIndex] = useState(0);
  const [answerVisible, setAnswerVisible] = useState(false);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const epochRef = useRef(0);
  const scopeRef = useRef<FlashcardRequestScope>({
    identity: null,
    courseId: null,
    epoch: 0,
    viewEpoch: 0,
  });

  const selectedDeck = useMemo(
    () => decks.find((deck) => deck.id === selectedDeckId) ?? view?.deck ?? null,
    [decks, selectedDeckId, view?.deck],
  );
  const courseId = activeCourse?.id ?? null;
  const courseWritable = isFlashcardCourseWritable(activeCourse?.state);
  const currentCard = reviewCards[reviewIndex] ?? null;

  const invalidate = useCallback(
    (nextIdentity: string | null, nextCourseId: string | null) => {
      const scope = {
        identity: nextIdentity,
        courseId: nextCourseId,
        epoch: ++epochRef.current,
        viewEpoch: 0,
      };
      scopeRef.current = scope;
      setDecks([]);
      setSelectedDeckId(null);
      setView(null);
      setDeckTitle("");
      setCardDraft(emptyCard);
      setReviewCards([]);
      setReviewIndex(0);
      setAnswerVisible(false);
      setBusy(false);
      setStatus(null);
      setError(null);
      return scope;
    },
    [],
  );

  const current = useCallback(
    (scope: FlashcardRequestScope) =>
      isCurrentFlashcardResponse(scope, scopeRef.current),
    [],
  );

  const advanceView = useCallback(() => {
    const next = advanceFlashcardViewScope(scopeRef.current);
    scopeRef.current = next;
    setBusy(false);
    return next;
  }, []);

  const loadDeck = useCallback(
    async (scope: FlashcardRequestScope, deck: FlashcardDeck) => {
      const loaded = await getFlashcardDeck(deck.course_id, deck.id);
      if (!current(scope)) return;
      setView(loaded);
    },
    [current],
  );

  const loadCourse = useCallback(
    async (scope: FlashcardRequestScope) => {
      if (!scope.courseId) return;
      const listed = await listFlashcardDecks(scope.courseId);
      if (!current(scope)) return;
      setDecks(listed);
      const first = listed.find((deck) => deck.state !== "archived") ?? null;
      setSelectedDeckId(first?.id ?? null);
      if (first) await loadDeck(scope, first);
    },
    [current, loadDeck],
  );

  useEffect(() => {
    let alive = true;
    void fetchAuthStatus().then(async (auth) => {
      if (!alive) return;
      const nextIdentity = auth?.authenticated ? auth.user_id ?? null : null;
      setIdentity(nextIdentity);
      const scope = invalidate(nextIdentity, courseId);
      if (nextIdentity && courseId) {
        try {
          await loadCourse(scope);
        } catch (cause) {
          if (current(scope)) setError(errorText(cause));
        }
      }
    });
    return () => {
      alive = false;
    };
  }, [courseId, current, invalidate, loadCourse]);

  useEffect(() => {
    const onAuthChanged = () => {
      invalidate(null, null);
      setIdentity(null);
      void fetchAuthStatus().then(async (auth) => {
        const nextIdentity = auth?.authenticated ? auth.user_id ?? null : null;
        setIdentity(nextIdentity);
        const scope = invalidate(nextIdentity, activeCourse?.id ?? null);
        if (nextIdentity && scope.courseId) {
          try {
            await loadCourse(scope);
          } catch (cause) {
            if (current(scope)) setError(errorText(cause));
          }
        }
      });
    };
    window.addEventListener("dt:auth-changed", onAuthChanged);
    return () => window.removeEventListener("dt:auth-changed", onAuthChanged);
  }, [activeCourse?.id, current, invalidate, loadCourse]);

  useEffect(() => {
    if (courseWritable) return;
    setReviewCards([]);
    setReviewIndex(0);
    setAnswerVisible(false);
  }, [courseWritable]);

  const selectDeck = useCallback(
    async (deck: FlashcardDeck) => {
      const scope = advanceView();
      setSelectedDeckId(deck.id);
      setView(null);
      setReviewCards([]);
      setReviewIndex(0);
      setAnswerVisible(false);
      setStatus(null);
      setError(null);
      try {
        await loadDeck(scope, deck);
      } catch (cause) {
        if (current(scope)) setError(errorText(cause));
      }
    },
    [advanceView, current, loadDeck],
  );

  const createDeck = useCallback(async () => {
    if (!activeCourse || !courseWritable || !deckTitle.trim()) return;
    const scope = advanceView();
    setBusy(true);
    setError(null);
    try {
      const created = await createFlashcardDeck(
        activeCourse.id,
        deckTitle.trim(),
        activeCourse.write_epoch,
      );
      if (!current(scope)) return;
      setDecks((items) => [created, ...items]);
      setSelectedDeckId(created.id);
      setDeckTitle("");
      await loadDeck(scope, created);
      if (current(scope)) setStatus("Manual Flashcard deck created.");
    } catch (cause) {
      if (current(scope)) setError(errorText(cause));
    } finally {
      if (current(scope)) setBusy(false);
    }
  }, [activeCourse, advanceView, courseWritable, current, deckTitle, loadDeck]);

  const addCard = useCallback(async () => {
    if (
      !activeCourse ||
      !courseWritable ||
      !selectedDeck ||
      selectedDeck.state !== "draft" ||
      !cardDraft.prompt.trim() ||
      !cardDraft.answer.trim()
    )
      return;
    const scope = scopeRef.current;
    setBusy(true);
    setError(null);
    try {
      await addFlashcard(
        activeCourse.id,
        selectedDeck,
        activeCourse.write_epoch,
        {
          prompt: cardDraft.prompt.trim(),
          answer: cardDraft.answer.trim(),
          objective_ids: cardDraft.objectiveIds
            .split(",")
            .map((value) => value.trim())
            .filter(Boolean),
        },
      );
      const loaded = await getFlashcardDeck(activeCourse.id, selectedDeck.id);
      if (!current(scope)) return;
      setView(loaded);
      setDecks((items) =>
        items.map((item) => (item.id === loaded.deck.id ? loaded.deck : item)),
      );
      setCardDraft(emptyCard);
      setStatus("Card saved.");
    } catch (cause) {
      if (current(scope)) setError(errorText(cause));
    } finally {
      if (current(scope)) setBusy(false);
    }
  }, [activeCourse, cardDraft, courseWritable, current, selectedDeck]);

  const publishDeck = useCallback(async () => {
    if (
      !activeCourse ||
      !courseWritable ||
      !selectedDeck ||
      selectedDeck.state !== "draft"
    )
      return;
    const scope = scopeRef.current;
    setBusy(true);
    setError(null);
    try {
      const ready = await readyFlashcardDeck(
        activeCourse.id,
        selectedDeck,
        activeCourse.write_epoch,
      );
      if (!current(scope)) return;
      setDecks((items) =>
        items.map((item) => (item.id === ready.id ? ready : item)),
      );
      await loadDeck(scope, ready);
      if (current(scope)) setStatus("Deck is ready to study.");
    } catch (cause) {
      if (current(scope)) setError(errorText(cause));
    } finally {
      if (current(scope)) setBusy(false);
    }
  }, [activeCourse, courseWritable, current, loadDeck, selectedDeck]);

  const beginReview = useCallback(async () => {
    if (
      !activeCourse ||
      !courseWritable ||
      !selectedDeck ||
      selectedDeck.state !== "ready"
    )
      return;
    const scope = advanceView();
    setBusy(true);
    setError(null);
    try {
      const due = await getDueFlashcards(activeCourse.id, selectedDeck.id);
      if (!current(scope)) return;
      setView(due);
      setReviewCards(due.cards);
      setReviewIndex(0);
      setAnswerVisible(false);
      setStatus(due.cards.length ? "Review started." : "Nothing is due right now.");
    } catch (cause) {
      if (current(scope)) setError(errorText(cause));
    } finally {
      if (current(scope)) setBusy(false);
    }
  }, [activeCourse, advanceView, courseWritable, current, selectedDeck]);

  const rate = useCallback(
    async (rating: FlashcardRating) => {
      if (!activeCourse || !courseWritable || !selectedDeck || !currentCard) return;
      const scope = scopeRef.current;
      setBusy(true);
      setError(null);
      try {
        const result = await reviewFlashcard(
          activeCourse.id,
          selectedDeck,
          currentCard,
          rating,
          activeCourse.write_epoch,
          idempotencyKey(),
        );
        if (!current(scope)) return;
        setView((existing) =>
          existing
            ? {
                ...existing,
                schedules: [
                  ...existing.schedules.filter(
                    (item) => item.card_id !== result.schedule.card_id,
                  ),
                  result.schedule,
                ],
                review_summary: result.review_summary,
              }
            : existing,
        );
        if (rating === "again") {
          // Keep the missed-card loop inside the current pass while the durable
          // server schedule remains the authority across reloads.
          setReviewCards((cards) => requeueAgainCard(cards, currentCard, rating));
        }
        setAnswerVisible(false);
        setReviewIndex((index) => index + 1);
        setStatus(
          rating !== "again" && reviewIndex + 1 >= reviewCards.length
            ? "Review complete. Your schedule is saved."
            : "Rating saved.",
        );
      } catch (cause) {
        if (current(scope)) setError(errorText(cause));
      } finally {
        if (current(scope)) setBusy(false);
      }
    },
    [
      activeCourse,
      courseWritable,
      current,
      currentCard,
      reviewCards.length,
      reviewIndex,
      selectedDeck,
    ],
  );

  const archiveOrRestore = useCallback(async () => {
    if (!activeCourse || !courseWritable || !selectedDeck) return;
    const scope = advanceView();
    setBusy(true);
    setError(null);
    try {
      const changed = await archiveOrRestoreFlashcardDeck(
        activeCourse.id,
        selectedDeck,
        activeCourse.write_epoch,
      );
      if (!current(scope)) return;
      setDecks((items) =>
        items.map((item) => (item.id === changed.id ? changed : item)),
      );
      await loadDeck(scope, changed);
      await refreshCourses();
      if (current(scope))
        setStatus(
          changed.state === "archived"
            ? "Deck archived. Review history is retained."
            : "Deck restored.",
        );
    } catch (cause) {
      if (current(scope)) setError(errorText(cause));
    } finally {
      if (current(scope)) setBusy(false);
    }
  }, [
    activeCourse,
    advanceView,
    courseWritable,
    current,
    loadDeck,
    refreshCourses,
    selectedDeck,
  ]);

  return (
    <main className="min-h-full bg-[var(--background)] text-[var(--foreground)]">
      <CourseBar />
      <div className="mx-auto max-w-6xl space-y-5 px-5 py-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold">{t("Flashcards")}</h1>
            <p className="text-sm text-[var(--muted-foreground)]">
              {t("Private, Course-owned cards with a durable review schedule.")}
            </p>
          </div>
          {activeCourse ? (
            <div className="rounded-lg border border-[var(--border)] bg-[var(--card)] px-3 py-2 text-sm">
              <span className="text-[var(--muted-foreground)]">{t("Active Course:")} </span>
              <strong>{activeCourse.title}</strong>
            </div>
          ) : null}
        </div>

        {!identity ? (
          <Notice>{t("Sign in to use private Course Flashcards.")}</Notice>
        ) : null}
        {identity && !activeCourse ? (
          <Notice>{t("Select or create a Course above to use Flashcards.")}</Notice>
        ) : null}

        {activeCourse ? (
          <div className="grid gap-5 lg:grid-cols-[280px_minmax(0,1fr)]">
            <section className="rounded-xl border border-[var(--border)] bg-[var(--card)] p-4">
              <h2 className="mb-3 font-medium">{t("Decks")}</h2>
              <div className="mb-3 flex gap-2">
                <input
                  aria-label={t("New Flashcard deck title")}
                  value={deckTitle}
                  onChange={(event) => setDeckTitle(event.target.value)}
                  placeholder={t("New deck title")}
                  disabled={!courseWritable || busy}
                  className="min-w-0 flex-1 rounded-lg border border-[var(--border)] bg-[var(--background)] px-2 py-1.5 text-sm"
                />
                <button
                  onClick={() => void createDeck()}
                  disabled={!courseWritable || busy || !deckTitle.trim()}
                  className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-sm disabled:opacity-50"
                >
                  {t("Create")}
                </button>
              </div>
              <div className="space-y-1">
                {decks.map((deck) => (
                  <button
                    key={deck.id}
                    onClick={() => void selectDeck(deck)}
                    className={`w-full rounded-lg px-3 py-2 text-left text-sm ${
                      selectedDeckId === deck.id
                        ? "bg-[var(--secondary)]"
                        : "hover:bg-[var(--secondary)]/60"
                    }`}
                  >
                    <span className="block font-medium">{deck.title}</span>
                    <span className="text-xs text-[var(--muted-foreground)]">
                      {deck.state} · {deck.mode}
                    </span>
                  </button>
                ))}
                {!decks.length ? (
                  <p className="px-2 py-3 text-sm text-[var(--muted-foreground)]">
                    {t("No Flashcard decks yet.")}
                  </p>
                ) : null}
              </div>
            </section>

            <section className="rounded-xl border border-[var(--border)] bg-[var(--card)] p-5">
              {selectedDeck && view ? (
                <div className="space-y-5">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <h2 className="text-xl font-semibold">{selectedDeck.title}</h2>
                      <p className="text-sm text-[var(--muted-foreground)]">
                        {view.cards.length} {t("cards")} · {view.review_summary.due_cards} {t("due")}
                      </p>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {selectedDeck.state === "draft" ? (
                        <button
                          onClick={() => void publishDeck()}
                          disabled={!courseWritable || busy || !view.cards.length}
                          className="inline-flex items-center gap-1 rounded-lg border border-[var(--border)] px-3 py-2 text-sm disabled:opacity-50"
                        >
                          <CheckCircle2 size={15} /> {t("Ready")}
                        </button>
                      ) : null}
                      {selectedDeck.state === "ready" ? (
                        <button
                          onClick={() => void beginReview()}
                          disabled={!courseWritable || busy}
                          className="inline-flex items-center gap-1 rounded-lg bg-[var(--primary)] px-3 py-2 text-sm text-[var(--primary-foreground)] disabled:opacity-50"
                        >
                          <Play size={15} /> {t("Review due")}
                        </button>
                      ) : null}
                      <button
                        onClick={() => void archiveOrRestore()}
                        disabled={!courseWritable || busy}
                        className="inline-flex items-center gap-1 rounded-lg border border-[var(--border)] px-3 py-2 text-sm disabled:opacity-50"
                      >
                        {selectedDeck.state === "archived" ? (
                          <RotateCcw size={15} />
                        ) : (
                          <Archive size={15} />
                        )}
                        {selectedDeck.state === "archived" ? t("Restore") : t("Archive")}
                      </button>
                    </div>
                  </div>

                  {selectedDeck.state === "draft" ? (
                    <div className="space-y-3 rounded-lg border border-[var(--border)] p-4">
                      <h3 className="font-medium">{t("Add a card")}</h3>
                      <textarea
                        aria-label={t("Flashcard prompt")}
                        value={cardDraft.prompt}
                        onChange={(event) =>
                          setCardDraft((value) => ({ ...value, prompt: event.target.value }))
                        }
                        placeholder={t("Prompt")}
                        disabled={!courseWritable || busy}
                        className="min-h-20 w-full rounded-lg border border-[var(--border)] bg-[var(--background)] p-2 text-sm"
                      />
                      <textarea
                        aria-label={t("Flashcard answer")}
                        value={cardDraft.answer}
                        onChange={(event) =>
                          setCardDraft((value) => ({ ...value, answer: event.target.value }))
                        }
                        placeholder={t("Answer")}
                        disabled={!courseWritable || busy}
                        className="min-h-20 w-full rounded-lg border border-[var(--border)] bg-[var(--background)] p-2 text-sm"
                      />
                      <input
                        aria-label={t("Flashcard objective IDs")}
                        value={cardDraft.objectiveIds}
                        onChange={(event) =>
                          setCardDraft((value) => ({
                            ...value,
                            objectiveIds: event.target.value,
                          }))
                        }
                        placeholder={t("Objective IDs, comma-separated (optional)")}
                        disabled={!courseWritable || busy}
                        className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-2 py-1.5 text-sm"
                      />
                      <button
                        onClick={() => void addCard()}
                        disabled={
                          busy ||
                          !courseWritable ||
                          !cardDraft.prompt.trim() ||
                          !cardDraft.answer.trim()
                        }
                        className="inline-flex items-center gap-1 rounded-lg border border-[var(--border)] px-3 py-2 text-sm disabled:opacity-50"
                      >
                        <Save size={15} /> {t("Save card")}
                      </button>
                    </div>
                  ) : null}

                  {currentCard ? (
                    <div className="space-y-4 rounded-xl border border-[var(--border)] p-5">
                      <div className="flex items-center gap-2 text-sm text-[var(--muted-foreground)]">
                        <GalleryVerticalEnd size={16} />
                        {t("Card")} {reviewIndex + 1} {t("of")} {reviewCards.length}
                      </div>
                      <p className="text-lg font-medium">{currentCard.prompt}</p>
                      {answerVisible ? (
                        <div className="rounded-lg bg-[var(--secondary)] p-4">
                          {currentCard.answer}
                        </div>
                      ) : (
                        <button
                          onClick={() => setAnswerVisible(true)}
                          disabled={!courseWritable}
                          className="inline-flex items-center gap-1 rounded-lg border border-[var(--border)] px-3 py-2 text-sm"
                        >
                          <Eye size={15} /> {t("Reveal answer")}
                        </button>
                      )}
                      {answerVisible ? (
                        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                          {(["again", "hard", "good", "easy"] as const).map(
                            (rating) => (
                              <button
                                key={rating}
                                disabled={!courseWritable || busy}
                                onClick={() => void rate(rating)}
                                className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm capitalize disabled:opacity-50"
                              >
                                {t(rating)}
                              </button>
                            ),
                          )}
                        </div>
                      ) : null}
                    </div>
                  ) : null}

                  {!currentCard && reviewCards.length > 0 ? (
                    <Notice>{t("Review complete. The next due times are saved.")}</Notice>
                  ) : null}

                  <div className="space-y-2">
                    {view.cards.map((card) => (
                      <div
                        key={card.id}
                        className="rounded-lg border border-[var(--border)] px-3 py-2"
                      >
                        <p className="text-sm font-medium">{card.prompt}</p>
                        <p className="mt-1 text-xs text-[var(--muted-foreground)]">
                          {card.state} · {t("revision")} {card.revision}
                        </p>
                      </div>
                    ))}
                  </div>
                </div>
              ) : (
                <p className="text-sm text-[var(--muted-foreground)]">
                  {t("Choose a deck or create one.")}
                </p>
              )}
            </section>
          </div>
        ) : null}

        {busy ? (
          <p className="flex items-center gap-2 text-sm text-[var(--muted-foreground)]">
            <Loader2 size={15} className="animate-spin" /> {t("Saving…")}
          </p>
        ) : null}
        {status ? <p className="text-sm text-emerald-600">{status}</p> : null}
        {error ? <p className="text-sm text-red-600">{error}</p> : null}
      </div>
    </main>
  );
}

function Notice({ children }: { children: React.ReactNode }) {
  return (
    <p className="rounded-lg border border-[var(--border)] p-4 text-sm text-[var(--muted-foreground)]">
      {children}
    </p>
  );
}
