"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  BookOpen,
  BrainCircuit,
  CheckCircle2,
  RefreshCcw,
  RotateCcw,
  Shuffle,
  XCircle,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { listKnowledgeBases, type KnowledgeBaseSummary } from "@/lib/knowledge-api";

type FlashcardSource = "topic" | "knowledge";
type FlashcardStage = "setup" | "overview" | "studying";
type CardRating = "new" | "got_it" | "missed" | "skipped";

interface FlashcardItem {
  id: string;
  front: string;
  back: string;
  hint?: string;
  tag: string;
}

interface FlashcardDeck {
  id: string;
  title: string;
  sourceType: FlashcardSource;
  sourceSummary: string;
  cards: FlashcardItem[];
  createdAt: number;
}

const CARD_COUNT_OPTIONS = [10, 20, 30] as const;
const FLASHCARD_STYLES = [
  { id: "mixed", label: "Mixed" },
  { id: "definition", label: "Definition" },
  { id: "concept", label: "Concept check" },
] as const;

function slugify(value: string) {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 40);
}

function buildPreviewDeck(topic: string, count: number, sourceType: FlashcardSource, kbNames: string[]): FlashcardDeck {
  const cleanTopic = topic.trim() || "Study topic";
  const safeTopic = cleanTopic.replace(/\s+/g, " ").trim();
  const fronts = [
    `What is the clearest working definition of ${safeTopic}?`,
    `Why does ${safeTopic} matter in practice?`,
    `What is a common mistake learners make with ${safeTopic}?`,
    `What is the first question to ask when evaluating ${safeTopic}?`,
    `What signal tells you someone understands ${safeTopic} instead of memorizing it?`,
    `How would you explain ${safeTopic} to a beginner in one short paragraph?`,
    `What related concept is easiest to confuse with ${safeTopic}?`,
    `What should be documented or tracked when applying ${safeTopic}?`,
    `What scenario best tests whether someone can use ${safeTopic} correctly?`,
    `What is the safest rule of thumb for ${safeTopic}?`,
  ];

  const cards = Array.from({ length: count }, (_, index) => {
    const front = fronts[index % fronts.length];
    return {
      id: `${slugify(safeTopic) || "flashcard"}-${index + 1}`,
      front,
      back:
        sourceType === "knowledge"
          ? `Ground this answer in ${kbNames.join(", ")}. Focus on the most defensible takeaway, one practical example, and one warning sign that shows the concept is being misapplied.`
          : `Answer in a compact coaching style: define the idea clearly, give one practical example, and end with the single thing a learner should remember about ${safeTopic}.`,
      hint: index % 2 === 0 ? `Card ${index + 1} is meant to test recall, not just recognition.` : undefined,
      tag: index % 3 === 0 ? "Concept card" : index % 3 === 1 ? "Scenario card" : "Recall card",
    };
  });

  return {
    id: `deck-${slugify(safeTopic) || "flashcards"}`,
    title: safeTopic,
    sourceType,
    sourceSummary:
      sourceType === "knowledge"
        ? `Grounded in ${kbNames.join(", ")}`
        : "AI-generated from topic",
    cards,
    createdAt: Date.now(),
  };
}

export default function FlashcardsWorkspace() {
  const { t } = useTranslation();
  const [stage, setStage] = useState<FlashcardStage>("setup");
  const [sourceType, setSourceType] = useState<FlashcardSource>("topic");
  const [topic, setTopic] = useState("NCE ethics boundaries");
  const [cardCount, setCardCount] = useState<number>(20);
  const [styleId, setStyleId] = useState<(typeof FLASHCARD_STYLES)[number]["id"]>("mixed");
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBaseSummary[]>([]);
  const [selectedKnowledgeBases, setSelectedKnowledgeBases] = useState<string[]>([]);
  const [deck, setDeck] = useState<FlashcardDeck | null>(null);
  const [cardIndex, setCardIndex] = useState(0);
  const [flipped, setFlipped] = useState(false);
  const [ratings, setRatings] = useState<Record<string, CardRating>>({});

  useEffect(() => {
    let cancelled = false;

    async function loadKnowledgeBases() {
      try {
        const items = await listKnowledgeBases({ force: true });
        if (cancelled) return;
        setKnowledgeBases(items);
        const defaults = items.filter((item) => item.is_default).map((item) => item.name);
        setSelectedKnowledgeBases(defaults.length > 0 ? defaults : items.slice(0, 1).map((item) => item.name));
      } catch (error) {
        if (!cancelled) {
          console.error("Failed to load flashcard knowledge bases", error);
        }
      }
    }

    void loadKnowledgeBases();
    return () => {
      cancelled = true;
    };
  }, []);

  const activeCard = deck?.cards[cardIndex] ?? null;
  const gotItCount = useMemo(
    () => Object.values(ratings).filter((rating) => rating === "got_it").length,
    [ratings],
  );
  const missedCount = useMemo(
    () => Object.values(ratings).filter((rating) => rating === "missed").length,
    [ratings],
  );
  const remainingCount = useMemo(
    () => (deck ? deck.cards.filter((card) => !ratings[card.id] || ratings[card.id] === "new").length : 0),
    [deck, ratings],
  );

  function toggleKnowledgeBase(name: string) {
    setSelectedKnowledgeBases((current) =>
      current.includes(name)
        ? current.filter((item) => item !== name)
        : [...current, name],
    );
  }

  function handleGenerateDeck() {
    const nextDeck = buildPreviewDeck(topic, cardCount, sourceType, selectedKnowledgeBases);
    setDeck(nextDeck);
    setRatings({});
    setCardIndex(0);
    setFlipped(false);
    setStage("overview");
  }

  function openStudy(mode: "resume" | "restart" | "missed") {
    if (!deck) return;
    if (mode === "restart") {
      setRatings({});
      setCardIndex(0);
    } else if (mode === "missed") {
      const firstMissedIndex = deck.cards.findIndex((card) => ratings[card.id] === "missed");
      setCardIndex(firstMissedIndex >= 0 ? firstMissedIndex : 0);
    }
    setFlipped(false);
    setStage("studying");
  }

  function handleRateCard(nextRating: Exclude<CardRating, "new">) {
    if (!activeCard || !deck) return;
    setRatings((current) => ({ ...current, [activeCard.id]: nextRating }));
    setFlipped(false);
    setCardIndex((current) => Math.min(current + 1, deck.cards.length - 1));
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
    setCardIndex(0);
    setFlipped(false);
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
                    "This first page slice keeps flashcards inside Practice, with a calmer setup, a saved-deck overview, and a one-card study player instead of a chat thread.",
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
                          onClick={() => setSourceType(option.id)}
                          className={`rounded-full px-3 py-1.5 text-[12px] font-medium transition-colors ${
                            sourceType === option.id
                              ? "bg-[var(--primary)] text-white"
                              : "text-[var(--muted-foreground)]"
                          }`}
                        >
                          {option.label}
                        </button>
                      ))}
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
                        <div className="text-[13px] text-[var(--muted-foreground)]">
                          {t("No knowledge bases loaded yet.")}
                        </div>
                      )}
                    </div>
                  </div>

                  <div className="rounded-2xl border border-dashed border-[var(--border)] bg-[var(--card)] px-4 py-4 text-[13px] text-[var(--muted-foreground)]">
                    {t(
                      "This first implementation slice uses a deterministic preview deck so we can build and test the page shell before wiring real GPT-backed generation.",
                    )}
                  </div>

                  <button
                    type="button"
                    onClick={handleGenerateDeck}
                    disabled={!topic.trim()}
                    className="inline-flex w-full items-center justify-center gap-2 rounded-2xl bg-[var(--primary)] px-4 py-3 text-[14px] font-semibold text-white transition-opacity disabled:opacity-40"
                  >
                    <BrainCircuit size={16} />
                    {t("Generate flashcard page preview")}
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
                    <div className="mt-2 text-[14px] text-[var(--muted-foreground)]">
                      {deck.sourceSummary} {" • "} {deck.cards.length} {t("cards")}
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

              <div className="rounded-[28px] border border-[var(--border)] bg-[var(--card)] p-6 shadow-[0_16px_50px_rgba(15,23,42,0.06)]">
                <div className="mb-4 text-[12px] font-semibold uppercase tracking-[0.18em] text-[var(--muted-foreground)]">
                  {t("Deck contents preview")}
                </div>
                <div className="space-y-3">
                  {deck.cards.slice(0, 6).map((card, index) => {
                    const rating = ratings[card.id] ?? "new";
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
                      {t("Active flashcards")}
                    </div>
                    <div className="mt-1 text-[24px] font-semibold text-[var(--foreground)]">{deck.title}</div>
                    <div className="mt-2 text-[13px] text-[var(--muted-foreground)]">
                      {deck.sourceSummary}
                    </div>
                  </div>

                  <div className="flex flex-wrap items-center gap-2">
                    <div className="rounded-2xl border border-[var(--border)] bg-[var(--background)] px-4 py-3 text-[13px] text-[var(--muted-foreground)]">
                      {t("Card")} {cardIndex + 1}/{deck.cards.length}
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
                            className="inline-flex items-center gap-2 rounded-xl bg-rose-600/90 px-4 py-2 text-[13px] font-semibold text-white"
                          >
                            <XCircle size={14} />
                            {t("Missed")}
                          </button>
                          <button
                            type="button"
                            onClick={() => handleRateCard("got_it")}
                            className="inline-flex items-center gap-2 rounded-xl bg-emerald-600/90 px-4 py-2 text-[13px] font-semibold text-white"
                          >
                            <CheckCircle2 size={14} />
                            {t("Got it")}
                          </button>
                          <button
                            type="button"
                            onClick={() => handleRateCard("skipped")}
                            className="rounded-xl border border-[var(--border)] px-4 py-2 text-[13px] font-semibold text-[var(--foreground)]"
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
                      {deck.cards.map((card, index) => {
                        const rating = ratings[card.id] ?? "new";
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
                    setCardIndex((current) => Math.min(deck.cards.length - 1, current + 1));
                    setFlipped(false);
                  }}
                  disabled={cardIndex === deck.cards.length - 1}
                  className="inline-flex items-center gap-2 rounded-xl border border-[var(--border)] px-4 py-2 text-[13px] font-medium text-[var(--foreground)] disabled:opacity-40"
                >
                  {t("Next")}
                  <ArrowRight size={14} />
                </button>
              </div>
            </div>
          ) : null}
        </section>

        <aside className="hidden w-[320px] shrink-0 space-y-4 xl:block">
          <div className="rounded-[28px] border border-[var(--border)] bg-[var(--card)] p-5 shadow-[0_16px_50px_rgba(15,23,42,0.06)]">
            <div className="mb-4 text-[12px] font-semibold uppercase tracking-[0.18em] text-[var(--muted-foreground)]">
              {t("Why this page exists")}
            </div>
            <div className="space-y-3 text-[13px] leading-6 text-[var(--muted-foreground)]">
              <p>{t("Flashcards live inside Practice, but they need a calmer page than quiz mode.")}</p>
              <p>{t("Saved decks should reopen into a deck overview first, not drop the user into card 1 without context.")}</p>
              <p>{t("Notebook stays optional later. The deck itself should remain a structured practice asset.")}</p>
            </div>
          </div>

          <div className="rounded-[28px] border border-[var(--border)] bg-[var(--card)] p-5 shadow-[0_16px_50px_rgba(15,23,42,0.06)]">
            <div className="mb-4 text-[12px] font-semibold uppercase tracking-[0.18em] text-[var(--muted-foreground)]">
              {t("Implementation note")}
            </div>
            <div className="rounded-2xl border border-dashed border-[var(--border)] bg-[var(--background)] px-4 py-5 text-[13px] leading-6 text-[var(--muted-foreground)]">
              {t("This page is the first frontend slice. Real deck persistence and GPT-backed generation can now be wired into a shape we already know works visually.")}
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}
