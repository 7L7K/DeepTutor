"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  BookOpen,
  BrainCircuit,
  CheckCircle2,
  RotateCcw,
  Shuffle,
  XCircle,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  createFlashcardDeck,
  completeFlashcardPass,
  getFlashcardDeck,
  getFlashcardTopicSuggestions,
  listFlashcardDecks,
  resetFlashcardDeckReviews,
  reviewFlashcardCard,
  type FlashcardDeck,
  type FlashcardRating,
  type FlashcardReviewMode,
  type FlashcardSessionReview,
  type FlashcardSource,
} from "@/lib/flashcards-api";
import { listKnowledgeBases, type KnowledgeBaseSummary } from "@/lib/knowledge-api";

type FlashcardStage = "setup" | "overview" | "studying" | "complete";

const CARD_COUNT_OPTIONS = [10, 20, 30] as const;
const FLASHCARD_STYLES = [
  { id: "mixed", label: "Mixed" },
  { id: "definition", label: "Definition" },
  { id: "concept", label: "Concept check" },
] as const;

export default function FlashcardsWorkspace() {
  const { t } = useTranslation();
  const searchParams = useSearchParams();
  const [stage, setStage] = useState<FlashcardStage>("setup");
  const [sourceType, setSourceType] = useState<FlashcardSource>("topic");
  const [topic, setTopic] = useState("NCE ethics boundaries");
  const [cardCount, setCardCount] = useState<number>(10);
  const [styleId, setStyleId] = useState<(typeof FLASHCARD_STYLES)[number]["id"]>("mixed");
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBaseSummary[]>([]);
  const [selectedKnowledgeBases, setSelectedKnowledgeBases] = useState<string[]>([]);
  const [recentDecks, setRecentDecks] = useState<FlashcardDeck[]>([]);
  const [deck, setDeck] = useState<FlashcardDeck | null>(null);
  const [studyMode, setStudyMode] = useState<FlashcardReviewMode>("full_deck");
  const [studyCardIds, setStudyCardIds] = useState<string[]>([]);
  const [completionReview, setCompletionReview] = useState<FlashcardSessionReview | null>(null);
  const [suggestedTopics, setSuggestedTopics] = useState<string[]>([]);
  const [cardIndex, setCardIndex] = useState(0);
  const [flipped, setFlipped] = useState(false);
  const [statusText, setStatusText] = useState("");
  const [errorText, setErrorText] = useState("");
  const [isWorking, setIsWorking] = useState(false);
  const isKnowledgeAvailable = knowledgeBases.length > 0;

  useEffect(() => {
    const seededTopic = searchParams.get("topic")?.trim();
    if (!seededTopic) return;
    setTopic(seededTopic);
  }, [searchParams]);

  useEffect(() => {
    let cancelled = false;

    async function loadSidebarData() {
      try {
        const [items, decks] = await Promise.all([listKnowledgeBases({ force: true }), listFlashcardDecks(8, 0)]);
        if (cancelled) return;
        setKnowledgeBases(items);
        setRecentDecks(decks);
        const defaults = items.filter((item) => item.is_default).map((item) => item.name);
        setSelectedKnowledgeBases(defaults.length > 0 ? defaults : items.slice(0, 1).map((item) => item.name));
      } catch (error) {
        if (!cancelled) {
          console.error("Failed to load flashcard workspace data", error);
        }
      }
    }

    void loadSidebarData();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (sourceType !== "knowledge" || selectedKnowledgeBases.length === 0) {
      setSuggestedTopics([]);
      return;
    }
    let cancelled = false;
    const timeout = setTimeout(() => {
      void (async () => {
        try {
          const suggestions = await getFlashcardTopicSuggestions({
            knowledgeBaseNames: selectedKnowledgeBases,
            hint: topic,
          });
          if (!cancelled) {
            setSuggestedTopics(suggestions);
          }
        } catch (error) {
          if (!cancelled) {
            console.error("Failed to load flashcard topic suggestions", error);
            setSuggestedTopics([]);
          }
        }
      })();
    }, 250);
    return () => {
      cancelled = true;
      clearTimeout(timeout);
    };
  }, [selectedKnowledgeBases, sourceType, topic]);

  useEffect(() => {
    if (!isKnowledgeAvailable && sourceType === "knowledge") {
      setSourceType("topic");
    }
  }, [isKnowledgeAvailable, sourceType]);

  useEffect(() => {
    if (!deck || deck.generationStatus !== "partial") return;
    setStatusText(
      `Starter deck ready: ${deck.readyCardCount}/${deck.requestedCardCount} cards. Building the rest...`,
    );
    const timeout = window.setTimeout(async () => {
      try {
        const loadedDeck = await getFlashcardDeck(deck.id);
        setDeck(loadedDeck);
        setStudyCardIds((current) => {
          if (current.length === 0) return loadedDeck.cards.map((card) => card.id);
          const known = new Set(current);
          return [
            ...current,
            ...loadedDeck.cards.map((card) => card.id).filter((cardId) => !known.has(cardId)),
          ];
        });
        if (loadedDeck.generationStatus === "complete" || loadedDeck.readyCardCount >= loadedDeck.requestedCardCount) {
          setStatusText("Deck complete. More cards were added while you were here.");
          await refreshRecentDecks();
        }
      } catch (error) {
        console.error("Failed to refresh progressive flashcard deck", error);
      }
    }, 3000);
    return () => window.clearTimeout(timeout);
  }, [deck]);

  async function refreshRecentDecks() {
    const decks = await listFlashcardDecks(8, 0);
    setRecentDecks(decks);
  }

  const studyCards =
    deck && studyCardIds.length > 0
      ? deck.cards.filter((card) => studyCardIds.includes(card.id))
      : deck?.cards ?? [];
  const activeCard = studyCards[cardIndex] ?? null;
  const ratings = deck?.summary.ratings ?? {};
  const gotItCount = deck?.summary.counts.got_it ?? 0;
  const missedCount = deck?.summary.counts.missed ?? 0;
  const remainingCount = deck?.summary.remaining ?? 0;
  const latestSessionReview = completionReview ?? deck?.latestSessionReview ?? null;
  const currentMissedCount = latestSessionReview?.missedCount ?? missedCount;

  function toggleKnowledgeBase(name: string) {
    setSelectedKnowledgeBases((current) =>
      current.includes(name)
        ? current.filter((item) => item !== name)
        : [...current, name],
    );
  }

  function handleSelectSource(nextSource: FlashcardSource) {
    if (nextSource === "knowledge" && !isKnowledgeAvailable) {
      setStatusText("Add a knowledge base before generating a grounded deck.");
      return;
    }
    setSourceType(nextSource);
    setStatusText("");
  }

  async function handleGenerateDeck() {
    setErrorText("");
    setStatusText("Generating flashcards...");
    setIsWorking(true);
    try {
      const result = await createFlashcardDeck({
        sourceType,
        topic,
        knowledgeBaseNames: sourceType === "knowledge" ? selectedKnowledgeBases : [],
        cardCount,
        style: styleId,
        reuseExisting: true,
      });
      setDeck(result.deck);
      setRecentDecks((current) => [result.deck, ...current.filter((item) => item.id !== result.deck.id)].slice(0, 8));
      setCompletionReview(result.deck.latestSessionReview ?? null);
      setStudyMode("full_deck");
      setStudyCardIds(result.deck.cards.map((card) => card.id));
      setCardIndex(0);
      setFlipped(false);
      setStage("overview");
      setStatusText(
        result.reusedExisting
          ? "Loaded your existing deck."
          : result.deck.generationStatus === "partial"
            ? `Starter deck ready: ${result.deck.readyCardCount}/${result.deck.requestedCardCount} cards. Building the rest...`
            : "Flashcard deck generated.",
      );
    } catch (error) {
      console.error("Failed to generate flashcards", error);
      setErrorText(error instanceof Error ? error.message : "Failed to generate flashcards.");
      setStatusText("");
    } finally {
      setIsWorking(false);
    }
  }

  async function openDeckOverview(deckId: string) {
    setErrorText("");
    setStatusText("Loading deck...");
    try {
      const loadedDeck = await getFlashcardDeck(deckId);
      setDeck(loadedDeck);
      setCompletionReview(loadedDeck.latestSessionReview ?? null);
      setStudyMode("full_deck");
      setStudyCardIds(loadedDeck.cards.map((card) => card.id));
      setCardIndex(0);
      setFlipped(false);
      setStage("overview");
      setStatusText("");
    } catch (error) {
      console.error("Failed to load flashcard deck", error);
      setErrorText(error instanceof Error ? error.message : "Failed to load the flashcard deck.");
      setStatusText("");
    }
  }

  async function openStudy(mode: "resume" | "restart" | "missed") {
    if (!deck) return;
    setErrorText("");
    setIsWorking(true);
    try {
      let resolvedDeck = deck;
      if (mode === "restart") {
        setStatusText("Restarting deck...");
        resolvedDeck = await resetFlashcardDeckReviews(deck.id);
        setDeck(resolvedDeck);
        await refreshRecentDecks();
      }
      const allCardIds = resolvedDeck.cards.map((card) => card.id);
      const missedIds = resolvedDeck.cards
        .filter((card) => resolvedDeck.summary.ratings[card.id]?.rating === "missed")
        .map((card) => card.id);
      if (mode === "missed" && missedIds.length === 0) {
        setStatusText("No missed cards to review yet.");
        setStage("overview");
        return;
      }
      const resumeIndex = resolvedDeck.cards.findIndex(
        (card) => (resolvedDeck.summary.ratings[card.id]?.rating || "new") === "new",
      );
      setStudyMode(mode === "missed" ? "missed_only" : "full_deck");
      setStudyCardIds(mode === "missed" ? missedIds : allCardIds);
      setCompletionReview(null);
      setCardIndex(mode === "missed" ? 0 : resumeIndex >= 0 ? resumeIndex : 0);
      setFlipped(false);
      setStage("studying");
      setStatusText("");
    } catch (error) {
      console.error("Failed to open deck study mode", error);
      setErrorText(error instanceof Error ? error.message : "Failed to open the deck.");
      setStatusText("");
    } finally {
      setIsWorking(false);
    }
  }

  async function handleRateCard(nextRating: Exclude<FlashcardRating, "new">) {
    if (!activeCard || !deck) return;
    setErrorText("");
    setIsWorking(true);
    try {
      const nextDeck = await reviewFlashcardCard(deck.id, activeCard.id, nextRating);
      const activeCardIds = studyCardIds.length > 0 ? studyCardIds : nextDeck.cards.map((card) => card.id);
      const nextIndex = cardIndex + 1;
      if (nextIndex >= activeCardIds.length) {
        setStatusText("Wrapping up your flashcard session...");
        const completed = await completeFlashcardPass(nextDeck.id, {
          reviewMode: studyMode,
          cardIds: activeCardIds,
        });
        setDeck(completed.deck);
        setCompletionReview(completed.sessionReview);
        setCardIndex(0);
        setFlipped(false);
        setStage("complete");
        setStatusText("");
      } else {
        setDeck(nextDeck);
        setCardIndex(nextIndex);
        setFlipped(false);
      }
      await refreshRecentDecks();
    } catch (error) {
      console.error("Failed to save flashcard review", error);
      setErrorText(error instanceof Error ? error.message : "Failed to save your card review.");
    } finally {
      setIsWorking(false);
    }
  }

  function handleShuffleDeck() {
    if (!deck) return;
    const shuffled = [...deck.cards];
    for (let i = shuffled.length - 1; i > 0; i -= 1) {
      const j = Math.floor(Math.random() * (i + 1));
      [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
    }
    setDeck({ ...deck, cards: shuffled });
    setCardIndex(0);
    setFlipped(false);
  }

  function resetToSetup() {
    setStage("setup");
    setStudyMode("full_deck");
    setStudyCardIds(deck?.cards.map((card) => card.id) ?? []);
    setCompletionReview(null);
    setCardIndex(0);
    setFlipped(false);
    setStatusText("");
    setErrorText("");
  }

  return (
    <div className="h-full overflow-y-auto bg-[radial-gradient(circle_at_top_left,rgba(215,122,69,0.08),transparent_26%),radial-gradient(circle_at_top_right,rgba(88,123,98,0.08),transparent_24%),var(--background)]">
      <div className="mx-auto flex max-w-[1440px] gap-6 px-6 py-6">
        <section className="min-w-0 flex-1 space-y-5">
          <div className="rounded-[28px] border border-[var(--border)] bg-[var(--card)]/95 p-6 shadow-[0_20px_70px_rgba(15,23,42,0.08)]">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div className="max-w-3xl space-y-3">
                <div className="inline-flex items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--background)] px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-[var(--muted-foreground)]">
                  <BookOpen size={13} />
                  {t("Practice Mode / Flashcards")}
                </div>
                <h1 className="text-[28px] font-semibold tracking-tight text-[var(--foreground)]">
                  {t("Study one card at a time, then decide what actually stuck.")}
                </h1>
                <p className="max-w-[760px] text-[14px] leading-7 text-[var(--muted-foreground)]">
                  {t(
                    "Generate flashcards from a topic or selected knowledge bases, reopen saved decks later, and work through them in a focused reveal-and-rate loop.",
                  )}
                </p>
                <div className="flex flex-wrap gap-2">
                  <Link
                    href="/practice"
                    className="inline-flex items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-[13px] font-medium text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
                  >
                    <ArrowLeft size={14} />
                    {t("Back to quiz mode")}
                  </Link>
                  <div className="inline-flex rounded-full border border-[var(--border)] bg-[var(--background)] p-1">
                    <Link
                      href="/practice"
                      className="rounded-full px-3 py-1.5 text-[12px] font-medium text-[var(--muted-foreground)]"
                    >
                      {t("Quiz")}
                    </Link>
                    <span className="rounded-full bg-[var(--primary)] px-3 py-1.5 text-[12px] font-semibold text-white">
                      {t("Flashcards")}
                    </span>
                  </div>
                </div>
              </div>

              <div className="grid min-w-[240px] grid-cols-3 gap-3">
                <div className="rounded-2xl border border-[var(--border)] bg-[var(--background)]/70 p-4">
                  <div className="text-[11px] uppercase tracking-[0.18em] text-[var(--muted-foreground)]">
                    {t("Cards")}
                  </div>
                  <div className="mt-2 text-[26px] font-semibold text-[var(--foreground)]">
                    {deck?.cards.length ?? cardCount}
                  </div>
                </div>
                <div className="rounded-2xl border border-[var(--border)] bg-[var(--background)]/70 p-4">
                  <div className="text-[11px] uppercase tracking-[0.18em] text-[var(--muted-foreground)]">
                    {t("Got it")}
                  </div>
                  <div className="mt-2 text-[26px] font-semibold text-emerald-600 dark:text-emerald-300">
                    {gotItCount}
                  </div>
                </div>
                <div className="rounded-2xl border border-[var(--border)] bg-[var(--background)]/70 p-4">
                  <div className="text-[11px] uppercase tracking-[0.18em] text-[var(--muted-foreground)]">
                    {t("Missed")}
                  </div>
                  <div className="mt-2 text-[26px] font-semibold text-rose-600 dark:text-rose-300">
                    {missedCount}
                  </div>
                </div>
              </div>
            </div>
          </div>

          {statusText ? (
            <div className="rounded-2xl border border-[var(--border)] bg-[var(--card)] px-4 py-3 text-[13px] text-[var(--muted-foreground)]">
              {t(statusText)}
            </div>
          ) : null}

          {errorText ? (
            <div className="rounded-2xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-[13px] text-rose-300">
              {errorText}
            </div>
          ) : null}

          {stage === "setup" ? (
            <div className="rounded-[28px] border border-[var(--border)] bg-[var(--card)] p-6 shadow-[0_16px_50px_rgba(15,23,42,0.06)]">
              <div className="grid gap-4 lg:grid-cols-[1.1fr_0.9fr]">
                <div className="space-y-4">
                  <div>
                    <div className="mb-2 text-[12px] font-semibold uppercase tracking-[0.18em] text-[var(--muted-foreground)]">
                      {t("Source")}
                    </div>
                    <div className="inline-flex rounded-full border border-[var(--border)] bg-[var(--background)] p-1">
                      {([
                        { id: "topic", label: t("Topic") },
                        { id: "knowledge", label: t("Knowledge") },
                      ] as const).map((option) => (
                        <button
                          key={option.id}
                          type="button"
                          disabled={option.id === "knowledge" && !isKnowledgeAvailable}
                          onClick={() => handleSelectSource(option.id)}
                          className={`rounded-full px-3 py-1.5 text-[12px] font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
                            sourceType === option.id
                              ? "bg-[var(--primary)] text-white"
                              : "text-[var(--muted-foreground)]"
                          }`}
                        >
                          {option.label}
                        </button>
                      ))}
                    </div>
                    <div className="mt-2 text-[12px] text-[var(--muted-foreground)]">
                      {!isKnowledgeAvailable
                        ? t("Knowledge decks unlock after you add sources in Knowledge. Topic starter decks are ready now.")
                        : sourceType === "knowledge"
                          ? t("Ground this deck in selected knowledge-base excerpts.")
                          : t("Generate a focused starter deck directly from your topic prompt.")}
                    </div>
                  </div>

                  <label className="block">
                    <div className="mb-2 text-[12px] font-semibold uppercase tracking-[0.18em] text-[var(--muted-foreground)]">
                      {sourceType === "topic" ? t("Topic") : t("Focus topic")}
                    </div>
                    <textarea
                      value={topic}
                      onChange={(event) => setTopic(event.target.value)}
                      rows={4}
                      className="w-full rounded-2xl border border-[var(--border)] bg-[var(--background)] px-4 py-3 text-[14px] text-[var(--foreground)] outline-none transition-colors focus:border-[var(--primary)]/40"
                      placeholder={t("Example: NCE ethics boundaries and social-media contact")}
                    />
                  </label>

                  <div>
                    <div className="mb-2 text-[12px] font-semibold uppercase tracking-[0.18em] text-[var(--muted-foreground)]">
                      {t("Deck style")}
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {FLASHCARD_STYLES.map((option) => (
                        <button
                          key={option.id}
                          type="button"
                          onClick={() => setStyleId(option.id)}
                          className={`rounded-full border px-3 py-1.5 text-[12px] font-medium transition-colors ${
                            styleId === option.id
                              ? "border-[var(--primary)] bg-[var(--primary)]/10 text-[var(--foreground)]"
                              : "border-[var(--border)] bg-[var(--background)] text-[var(--muted-foreground)]"
                          }`}
                        >
                          {t(option.label)}
                        </button>
                      ))}
                    </div>
                  </div>

                  {sourceType === "knowledge" && suggestedTopics.length > 0 ? (
                    <div>
                      <div className="mb-2 text-[12px] font-semibold uppercase tracking-[0.18em] text-[var(--muted-foreground)]">
                        {t("Suggested topics")}
                      </div>
                      <div className="flex flex-wrap gap-2">
                        {suggestedTopics.map((suggestion) => (
                          <button
                            key={suggestion}
                            type="button"
                            onClick={() => setTopic(suggestion)}
                            className="rounded-full border border-[var(--border)] bg-[var(--background)] px-3 py-1.5 text-[12px] font-medium text-[var(--muted-foreground)] transition-colors hover:border-[var(--primary)]/40 hover:text-[var(--foreground)]"
                          >
                            {suggestion}
                          </button>
                        ))}
                      </div>
                    </div>
                  ) : null}
                </div>

                <div className="space-y-4 rounded-2xl border border-[var(--border)] bg-[var(--background)]/70 p-4">
                  <div>
                    <div className="mb-2 text-[12px] font-semibold uppercase tracking-[0.18em] text-[var(--muted-foreground)]">
                      {t("Card count")}
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {CARD_COUNT_OPTIONS.map((option) => (
                        <button
                          key={option}
                          type="button"
                          onClick={() => setCardCount(option)}
                          className={`rounded-full border px-3 py-1.5 text-[12px] font-medium transition-colors ${
                            cardCount === option
                              ? "border-[var(--primary)] bg-[var(--primary)]/10 text-[var(--foreground)]"
                              : "border-[var(--border)] bg-[var(--background)] text-[var(--muted-foreground)]"
                          }`}
                        >
                          {option} {t("cards")}
                        </button>
                      ))}
                    </div>
                  </div>

                  <div>
                    <div className="mb-2 text-[12px] font-semibold uppercase tracking-[0.18em] text-[var(--muted-foreground)]">
                      {t("Knowledge bases")}
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {knowledgeBases.length > 0 ? (
                        knowledgeBases.map((kb) => {
                          const active = selectedKnowledgeBases.includes(kb.name);
                          return (
                            <button
                              key={kb.name}
                              type="button"
                              onClick={() => toggleKnowledgeBase(kb.name)}
                              className={`rounded-full border px-3 py-1.5 text-[12px] font-medium transition-colors ${
                                active
                                  ? "border-[var(--primary)] bg-[var(--primary)]/10 text-[var(--foreground)]"
                                  : "border-[var(--border)] bg-[var(--background)] text-[var(--muted-foreground)]"
                              }`}
                            >
                              {kb.name}
                            </button>
                          );
                        })
                      ) : (
                        <div className="text-[13px] text-[var(--muted-foreground)]">{t("No knowledge bases loaded yet.")}</div>
                      )}
                    </div>
                  </div>

                  <div className="rounded-2xl border border-dashed border-[var(--border)] bg-[var(--card)] px-4 py-4 text-[13px] text-[var(--muted-foreground)]">
                    {sourceType === "knowledge"
                      ? t("Grounded decks use excerpts from the selected knowledge bases and save automatically when generated.")
                      : t("Topic decks are ungrounded AI starter decks. Add Knowledge sources when you need cards tied to uploaded material.")}
                  </div>

                  <button
                    type="button"
                    onClick={handleGenerateDeck}
                    disabled={isWorking || !topic.trim() || (sourceType === "knowledge" && selectedKnowledgeBases.length === 0)}
                    className="inline-flex w-full items-center justify-center gap-2 rounded-2xl bg-[var(--primary)] px-4 py-3 text-[14px] font-semibold text-white transition-opacity disabled:opacity-40"
                  >
                    <BrainCircuit size={16} />
                    {t("Build starter deck")}
                  </button>
                </div>
              </div>
            </div>
          ) : null}

          {stage === "overview" && deck ? (
            <div className="space-y-4">
              <div className="rounded-[28px] border border-[var(--border)] bg-[var(--card)] p-6 shadow-[0_16px_50px_rgba(15,23,42,0.06)]">
                <div className="flex flex-wrap items-start justify-between gap-4">
                  <div>
                    <div className="text-[12px] font-semibold uppercase tracking-[0.18em] text-[var(--muted-foreground)]">
                      {t("Saved deck")}
                    </div>
                    <div className="mt-1 text-[30px] font-semibold text-[var(--foreground)]">{deck.title}</div>
                    <div className="mt-3 flex flex-wrap gap-2">
                      <span className="rounded-full border border-[var(--border)] bg-[var(--background)] px-3 py-1 text-[12px] font-medium text-[var(--muted-foreground)]">
                        {deck.sourceSummary}
                      </span>
                      {deck.sourceKbNames.map((kbName) => (
                        <span
                          key={kbName}
                          className="rounded-full border border-[var(--border)] bg-[var(--background)] px-3 py-1 text-[12px] font-medium text-[var(--muted-foreground)]"
                        >
                          {kbName}
                        </span>
                      ))}
                      <span className="rounded-full border border-[var(--border)] bg-[var(--background)] px-3 py-1 text-[12px] font-medium text-[var(--muted-foreground)]">
                        {deck.cards.length} {t("cards")}
                      </span>
                    </div>
                  </div>

                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={() => openStudy("resume")}
                      className="rounded-2xl bg-[var(--primary)] px-4 py-3 text-[14px] font-semibold text-white"
                    >
                      {t("Resume deck")}
                    </button>
                    <button
                      type="button"
                      onClick={() => openStudy("missed")}
                      className="rounded-2xl bg-emerald-600/90 px-4 py-3 text-[14px] font-semibold text-white"
                    >
                      {t("Review missed")}
                    </button>
                    <button
                      type="button"
                      onClick={() => openStudy("restart")}
                      className="rounded-2xl border border-[var(--border)] px-4 py-3 text-[14px] font-semibold text-[var(--foreground)]"
                    >
                      {t("Restart all")}
                    </button>
                  </div>
                </div>
              </div>

              {latestSessionReview ? (
                <div className="rounded-[28px] border border-[var(--border)] bg-[var(--card)] p-6 shadow-[0_16px_50px_rgba(15,23,42,0.06)]">
                  <div className="mb-3 text-[12px] font-semibold uppercase tracking-[0.18em] text-[var(--muted-foreground)]">
                    {t("Latest study review")}
                  </div>
                  <div className="text-[16px] font-medium leading-7 text-[var(--foreground)]">
                    {latestSessionReview.analysisSummary}
                  </div>
                  {latestSessionReview.analysisWeakSpots.length > 0 ? (
                    <div className="mt-4 flex flex-wrap gap-2">
                      {latestSessionReview.analysisWeakSpots.map((spot) => (
                        <span
                          key={spot}
                          className="rounded-full bg-rose-500/12 px-3 py-1 text-[12px] font-medium text-rose-700 dark:text-rose-300"
                        >
                          {spot}
                        </span>
                      ))}
                    </div>
                  ) : null}
                  {latestSessionReview.analysisRecommendedNextStep ? (
                    <div className="mt-4 rounded-2xl border border-[var(--border)] bg-[var(--background)] px-4 py-3 text-[13px] text-[var(--muted-foreground)]">
                      {latestSessionReview.analysisRecommendedNextStep}
                    </div>
                  ) : null}
                </div>
              ) : null}

              <div className="rounded-[28px] border border-[var(--border)] bg-[var(--card)] p-6 shadow-[0_16px_50px_rgba(15,23,42,0.06)]">
                <div className="mb-4 text-[12px] font-semibold uppercase tracking-[0.18em] text-[var(--muted-foreground)]">
                  {t("Deck contents preview")}
                </div>
                <div className="space-y-3">
                  {deck.cards.slice(0, 6).map((card, index) => {
                    const rating = ratings[card.id]?.rating ?? "new";
                    const statusLabel =
                      rating === "got_it" ? t("Got it") : rating === "missed" ? t("Missed") : rating === "skipped" ? t("Skipped") : t("New");
                    return (
                      <div
                        key={card.id}
                        className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-[var(--border)] bg-[var(--background)] px-4 py-4"
                      >
                        <div className="min-w-0">
                          <div className="text-[11px] uppercase tracking-[0.18em] text-[var(--muted-foreground)]">
                            {t("Card")} {index + 1}
                          </div>
                          <div className="mt-1 text-[14px] font-medium text-[var(--foreground)]">{card.front}</div>
                        </div>
                        <div className="rounded-full border border-[var(--border)] px-3 py-1 text-[12px] font-medium text-[var(--muted-foreground)]">
                          {statusLabel}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          ) : null}

          {stage === "studying" && deck && activeCard ? (
            <div className="space-y-4">
              <div className="rounded-[28px] border border-[var(--border)] bg-[var(--card)] p-5 shadow-[0_16px_50px_rgba(15,23,42,0.06)]">
                <div className="flex flex-wrap items-center justify-between gap-4">
                  <div>
                    <div className="text-[12px] font-semibold uppercase tracking-[0.18em] text-[var(--muted-foreground)]">
                      {studyMode === "missed_only" ? t("Missed cards review") : t("Active flashcards")}
                    </div>
                    <div className="mt-1 text-[24px] font-semibold text-[var(--foreground)]">{deck.title}</div>
                    <div className="mt-2 text-[13px] text-[var(--muted-foreground)]">{deck.sourceSummary}</div>
                    {studyMode === "missed_only" ? (
                      <div className="mt-2 text-[12px] text-rose-600 dark:text-rose-300">
                        {studyCards.length} {t("cards in this review pass")}
                      </div>
                    ) : null}
                  </div>

                  <div className="flex flex-wrap items-center gap-2">
                    <div className="rounded-2xl border border-[var(--border)] bg-[var(--background)] px-4 py-3 text-[13px] text-[var(--muted-foreground)]">
                      {t("Card")} {cardIndex + 1}/{studyCards.length}
                    </div>
                    <button
                      type="button"
                      onClick={handleShuffleDeck}
                      className="inline-flex items-center gap-2 rounded-2xl border border-[var(--border)] bg-[var(--background)] px-4 py-3 text-[13px] text-[var(--muted-foreground)]"
                    >
                      <Shuffle size={14} />
                      {t("Shuffle")}
                    </button>
                  </div>
                </div>
              </div>

              <div className="grid gap-4 lg:grid-cols-[1.1fr_0.9fr]">
                <div className="rounded-[28px] border border-[var(--border)] bg-[var(--card)] p-6 shadow-[0_16px_50px_rgba(15,23,42,0.06)]">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="rounded-full border border-[var(--border)] bg-[var(--background)] px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-[var(--muted-foreground)]">
                      {t(activeCard.tag)}
                    </span>
                    <span className="rounded-full border border-[var(--border)] bg-[var(--background)] px-3 py-1 text-[11px] font-medium text-[var(--muted-foreground)]">
                      {deck.sourceSummary}
                    </span>
                  </div>

                  <div className="mt-6 rounded-[28px] border border-[var(--border)] bg-[var(--background)] px-6 py-8">
                    <div className="text-[13px] uppercase tracking-[0.18em] text-[var(--muted-foreground)]">
                      {flipped ? t("Back of card") : t("Front of card")}
                    </div>
                    <div className="mt-4 text-[28px] font-semibold leading-[1.3] tracking-tight text-[var(--foreground)]">
                      {flipped ? activeCard.back : activeCard.front}
                    </div>
                    {activeCard.hint && !flipped ? (
                      <div className="mt-8 rounded-2xl border border-[var(--border)] bg-[var(--card)] px-4 py-3 text-[13px] text-[var(--muted-foreground)]">
                        {activeCard.hint}
                      </div>
                    ) : null}
                  </div>

                  <div className="mt-6 flex flex-wrap items-center justify-between gap-3 border-t border-[var(--border)] pt-4">
                    <div className="text-[12px] text-[var(--muted-foreground)]">
                      {t("Default flow: flip, rate, and auto-advance. The deck map stays secondary.")}
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {!flipped ? (
                        <button
                          type="button"
                          onClick={() => setFlipped(true)}
                          className="rounded-xl bg-[var(--primary)] px-4 py-2 text-[13px] font-semibold text-white"
                        >
                          {t("Flip card")}
                        </button>
                      ) : (
                        <>
                          <button
                            type="button"
                            onClick={() => handleRateCard("missed")}
                            disabled={isWorking}
                            className="inline-flex items-center gap-2 rounded-xl bg-rose-600/90 px-4 py-2 text-[13px] font-semibold text-white disabled:opacity-40"
                          >
                            <XCircle size={14} />
                            {t("Missed")}
                          </button>
                          <button
                            type="button"
                            onClick={() => handleRateCard("got_it")}
                            disabled={isWorking}
                            className="inline-flex items-center gap-2 rounded-xl bg-emerald-600/90 px-4 py-2 text-[13px] font-semibold text-white disabled:opacity-40"
                          >
                            <CheckCircle2 size={14} />
                            {t("Got it")}
                          </button>
                          <button
                            type="button"
                            onClick={() => handleRateCard("skipped")}
                            disabled={isWorking}
                            className="rounded-xl border border-[var(--border)] px-4 py-2 text-[13px] font-semibold text-[var(--foreground)] disabled:opacity-40"
                          >
                            {t("Skip")}
                          </button>
                        </>
                      )}
                    </div>
                  </div>
                </div>

                <div className="space-y-4">
                  <div className="rounded-[28px] border border-[var(--border)] bg-[var(--card)] p-5 shadow-[0_16px_50px_rgba(15,23,42,0.06)]">
                    <div className="mb-4 text-[12px] font-semibold uppercase tracking-[0.18em] text-[var(--muted-foreground)]">
                      {t("Deck map")}
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {studyCards.map((card, index) => {
                        const rating = ratings[card.id]?.rating ?? "new";
                        const classes =
                          index === cardIndex
                            ? "bg-[var(--primary)] text-white"
                            : rating === "got_it"
                              ? "bg-emerald-500/12 text-emerald-700 dark:text-emerald-300"
                              : rating === "missed"
                                ? "bg-rose-500/12 text-rose-700 dark:text-rose-300"
                                : "bg-[var(--muted)] text-[var(--muted-foreground)]";
                        return (
                          <button
                            key={card.id}
                            type="button"
                            onClick={() => {
                              setCardIndex(index);
                              setFlipped(false);
                            }}
                            className={`h-9 min-w-9 rounded-full px-3 text-[12px] font-semibold ${classes}`}
                          >
                            {index + 1}
                          </button>
                        );
                      })}
                    </div>
                  </div>

                  <div className="rounded-[28px] border border-[var(--border)] bg-[var(--card)] p-5 shadow-[0_16px_50px_rgba(15,23,42,0.06)]">
                    <div className="mb-4 text-[12px] font-semibold uppercase tracking-[0.18em] text-[var(--muted-foreground)]">
                      {t("Session summary")}
                    </div>
                    <div className="grid grid-cols-3 gap-3">
                      <div className="rounded-2xl border border-[var(--border)] bg-[var(--background)] px-4 py-3">
                        <div className="text-[11px] uppercase tracking-[0.18em] text-[var(--muted-foreground)]">
                          {t("Got it")}
                        </div>
                        <div className="mt-2 text-[24px] font-semibold text-emerald-600 dark:text-emerald-300">
                          {gotItCount}
                        </div>
                      </div>
                      <div className="rounded-2xl border border-[var(--border)] bg-[var(--background)] px-4 py-3">
                        <div className="text-[11px] uppercase tracking-[0.18em] text-[var(--muted-foreground)]">
                          {t("Missed")}
                        </div>
                        <div className="mt-2 text-[24px] font-semibold text-rose-600 dark:text-rose-300">
                          {missedCount}
                        </div>
                      </div>
                      <div className="rounded-2xl border border-[var(--border)] bg-[var(--background)] px-4 py-3">
                        <div className="text-[11px] uppercase tracking-[0.18em] text-[var(--muted-foreground)]">
                          {t("Remaining")}
                        </div>
                        <div className="mt-2 text-[24px] font-semibold text-[var(--foreground)]">
                          {remainingCount}
                        </div>
                      </div>
                    </div>

                    <div className="mt-4 flex flex-wrap gap-2">
                      <button
                        type="button"
                        onClick={() => setStage("overview")}
                        className="rounded-xl border border-[var(--border)] px-3 py-2 text-[13px] font-medium text-[var(--foreground)]"
                      >
                        {t("Deck overview")}
                      </button>
                      <button
                        type="button"
                        onClick={resetToSetup}
                        className="inline-flex items-center gap-2 rounded-xl border border-[var(--border)] px-3 py-2 text-[13px] font-medium text-[var(--foreground)]"
                      >
                        <RotateCcw size={14} />
                        {t("New deck")}
                      </button>
                    </div>
                  </div>
                </div>
              </div>

              <div className="flex flex-wrap items-center justify-between gap-3 rounded-[28px] border border-[var(--border)] bg-[var(--card)] px-6 py-4 shadow-[0_16px_50px_rgba(15,23,42,0.06)]">
                <button
                  type="button"
                  onClick={() => {
                    setCardIndex((current) => Math.max(0, current - 1));
                    setFlipped(false);
                  }}
                  disabled={cardIndex === 0}
                  className="inline-flex items-center gap-2 rounded-xl border border-[var(--border)] px-4 py-2 text-[13px] font-medium text-[var(--foreground)] disabled:opacity-40"
                >
                  <ArrowLeft size={14} />
                  {t("Previous")}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setCardIndex((current) => Math.min(studyCards.length - 1, current + 1));
                    setFlipped(false);
                  }}
                  disabled={cardIndex === studyCards.length - 1}
                  className="inline-flex items-center gap-2 rounded-xl border border-[var(--border)] px-4 py-2 text-[13px] font-medium text-[var(--foreground)] disabled:opacity-40"
                >
                  {t("Next")}
                  <ArrowRight size={14} />
                </button>
              </div>
            </div>
          ) : null}

          {stage === "complete" && deck ? (
            <div className="space-y-4">
              <div className="rounded-[28px] border border-[var(--border)] bg-[var(--card)] p-6 shadow-[0_16px_50px_rgba(15,23,42,0.06)]">
                <div className="text-[12px] font-semibold uppercase tracking-[0.18em] text-[var(--muted-foreground)]">
                  {t("Deck complete")}
                </div>
                <div className="mt-2 text-[30px] font-semibold text-[var(--foreground)]">{deck.title}</div>
                <div className="mt-3 flex flex-wrap gap-2">
                  <span className="rounded-full border border-[var(--border)] bg-[var(--background)] px-3 py-1 text-[12px] font-medium text-[var(--muted-foreground)]">
                    {deck.sourceSummary}
                  </span>
                  <span className="rounded-full border border-[var(--border)] bg-[var(--background)] px-3 py-1 text-[12px] font-medium text-[var(--muted-foreground)]">
                    {studyMode === "missed_only" ? t("Missed cards review") : t("Full deck")}
                  </span>
                </div>
                <div className="mt-5 grid gap-3 sm:grid-cols-3">
                  <div className="rounded-2xl border border-[var(--border)] bg-[var(--background)] px-4 py-4">
                    <div className="text-[11px] uppercase tracking-[0.18em] text-[var(--muted-foreground)]">{t("Got it")}</div>
                    <div className="mt-2 text-[24px] font-semibold text-emerald-600 dark:text-emerald-300">
                      {latestSessionReview?.gotItCount ?? gotItCount}
                    </div>
                  </div>
                  <div className="rounded-2xl border border-[var(--border)] bg-[var(--background)] px-4 py-4">
                    <div className="text-[11px] uppercase tracking-[0.18em] text-[var(--muted-foreground)]">{t("Missed")}</div>
                    <div className="mt-2 text-[24px] font-semibold text-rose-600 dark:text-rose-300">
                      {latestSessionReview?.missedCount ?? missedCount}
                    </div>
                  </div>
                  <div className="rounded-2xl border border-[var(--border)] bg-[var(--background)] px-4 py-4">
                    <div className="text-[11px] uppercase tracking-[0.18em] text-[var(--muted-foreground)]">{t("Skipped")}</div>
                    <div className="mt-2 text-[24px] font-semibold text-[var(--foreground)]">
                      {latestSessionReview?.skippedCount ?? deck.summary.counts.skipped}
                    </div>
                  </div>
                </div>
              </div>

              <div className="rounded-[28px] border border-[var(--border)] bg-[var(--card)] p-6 shadow-[0_16px_50px_rgba(15,23,42,0.06)]">
                <div className="mb-3 text-[12px] font-semibold uppercase tracking-[0.18em] text-[var(--muted-foreground)]">
                  {t("Coach review")}
                </div>
                <div className="text-[16px] leading-7 text-[var(--foreground)]">
                  {latestSessionReview?.analysisSummary || t("This pass is saved. Review the missed cards next if you want a tighter second loop.")}
                </div>

                {latestSessionReview?.analysisStrengths?.length ? (
                  <div className="mt-5">
                    <div className="mb-2 text-[12px] font-semibold uppercase tracking-[0.18em] text-[var(--muted-foreground)]">
                      {t("Strengths")}
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {latestSessionReview.analysisStrengths.map((item) => (
                        <span
                          key={item}
                          className="rounded-full bg-emerald-500/12 px-3 py-1 text-[12px] font-medium text-emerald-700 dark:text-emerald-300"
                        >
                          {item}
                        </span>
                      ))}
                    </div>
                  </div>
                ) : null}

                {latestSessionReview?.analysisWeakSpots?.length ? (
                  <div className="mt-5">
                    <div className="mb-2 text-[12px] font-semibold uppercase tracking-[0.18em] text-[var(--muted-foreground)]">
                      {t("Review next")}
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {latestSessionReview.analysisWeakSpots.map((item) => (
                        <span
                          key={item}
                          className="rounded-full bg-rose-500/12 px-3 py-1 text-[12px] font-medium text-rose-700 dark:text-rose-300"
                        >
                          {item}
                        </span>
                      ))}
                    </div>
                  </div>
                ) : null}

                {latestSessionReview?.analysisFocusTopics?.length ? (
                  <div className="mt-5">
                    <div className="mb-2 text-[12px] font-semibold uppercase tracking-[0.18em] text-[var(--muted-foreground)]">
                      {t("Focus topics")}
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {latestSessionReview.analysisFocusTopics.map((item) => (
                        <span
                          key={item}
                          className="rounded-full border border-[var(--border)] bg-[var(--background)] px-3 py-1 text-[12px] font-medium text-[var(--muted-foreground)]"
                        >
                          {item}
                        </span>
                      ))}
                    </div>
                  </div>
                ) : null}

                {latestSessionReview?.analysisRecommendedNextStep ? (
                  <div className="mt-5 rounded-2xl border border-[var(--border)] bg-[var(--background)] px-4 py-4 text-[13px] leading-6 text-[var(--muted-foreground)]">
                    {latestSessionReview.analysisRecommendedNextStep}
                  </div>
                ) : null}

                {currentMissedCount === 0 ? (
                  <div className="mt-5 rounded-2xl border border-emerald-500/20 bg-emerald-500/8 px-4 py-4 text-[13px] leading-6 text-emerald-700 dark:text-emerald-300">
                    {t("No missed cards left in this pass. Restart the full deck if you want another run.")}
                  </div>
                ) : null}

                <div className="mt-5 flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => openStudy("missed")}
                    disabled={currentMissedCount === 0}
                    className="rounded-2xl bg-emerald-600/90 px-4 py-3 text-[14px] font-semibold text-white disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    {t("Review missed only")}
                  </button>
                  <button
                    type="button"
                    onClick={() => openStudy("restart")}
                    className="rounded-2xl border border-[var(--border)] px-4 py-3 text-[14px] font-semibold text-[var(--foreground)]"
                  >
                    {t("Restart full deck")}
                  </button>
                  <button
                    type="button"
                    onClick={() => setStage("overview")}
                    className="rounded-2xl border border-[var(--border)] px-4 py-3 text-[14px] font-semibold text-[var(--foreground)]"
                  >
                    {t("Back to overview")}
                  </button>
                </div>
              </div>
            </div>
          ) : null}
        </section>

        <aside className="hidden w-[320px] shrink-0 space-y-4 xl:block">
          <div className="rounded-[28px] border border-[var(--border)] bg-[var(--card)] p-5 shadow-[0_16px_50px_rgba(15,23,42,0.06)]">
            <div className="mb-4 text-[12px] font-semibold uppercase tracking-[0.18em] text-[var(--muted-foreground)]">
              {t("Recent decks")}
            </div>
            <div className="space-y-3">
              {recentDecks.length > 0 ? (
                recentDecks.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => openDeckOverview(item.id)}
                    className="block w-full rounded-2xl border border-[var(--border)] bg-[var(--background)] px-4 py-4 text-left transition-colors hover:border-[var(--primary)]/30"
                  >
                    <div className="text-[13px] font-semibold text-[var(--foreground)]">{item.title}</div>
                    <div className="mt-1 flex flex-wrap gap-2">
                      <span className="rounded-full border border-[var(--border)] bg-[var(--card)] px-2.5 py-1 text-[11px] font-medium text-[var(--muted-foreground)]">
                        {item.sourceSummary}
                      </span>
                      <span className="rounded-full border border-[var(--border)] bg-[var(--card)] px-2.5 py-1 text-[11px] font-medium text-[var(--muted-foreground)]">
                        {item.cardCount} {t("cards")}
                      </span>
                    </div>
                    <div className="mt-2 text-[12px] text-[var(--muted-foreground)]">
                      {item.summary.counts.got_it} {t("got it")} {" • "} {item.summary.counts.missed} {t("missed")}
                    </div>
                    {item.latestSessionReview?.analysisSummary ? (
                      <div className="mt-2 line-clamp-2 text-[12px] leading-5 text-[var(--muted-foreground)]">
                        {item.latestSessionReview.analysisSummary}
                      </div>
                    ) : null}
                  </button>
                ))
              ) : (
                <div className="rounded-2xl border border-dashed border-[var(--border)] bg-[var(--background)] px-4 py-5 text-[13px] leading-6 text-[var(--muted-foreground)]">
                  {t("No flashcard decks yet. Build a 10-card starter deck from a topic, or add Knowledge sources for grounded cards.")}
                </div>
              )}
            </div>
          </div>

          <div className="rounded-[28px] border border-[var(--border)] bg-[var(--card)] p-5 shadow-[0_16px_50px_rgba(15,23,42,0.06)]">
            <div className="mb-4 text-[12px] font-semibold uppercase tracking-[0.18em] text-[var(--muted-foreground)]">
              {t("Why this page exists")}
            </div>
            <div className="space-y-3 text-[13px] leading-6 text-[var(--muted-foreground)]">
              <p>{t("Flashcards live inside Practice, but they need a calmer page than quiz mode.")}</p>
              <p>{t("Saved decks reopen into a deck overview first so learners know what they are resuming.")}</p>
              <p>{t("Decks save as structured practice assets instead of getting lost inside chat or notebook output.")}</p>
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}
