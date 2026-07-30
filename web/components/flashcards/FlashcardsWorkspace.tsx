"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Archive,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Loader2,
  Play,
  RotateCcw,
  Save,
  Sparkles,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { CourseBar } from "@/components/courses/CourseBar";
import { useCourses } from "@/context/CourseContext";
import { fetchAuthStatus } from "@/lib/auth";
import {
  getCourseCapabilities,
  listCourseSources,
  type CourseSource,
} from "@/lib/course-api";
import {
  addFlashcard,
  advanceFlashcardViewScope,
  archiveOrRestoreFlashcardDeck,
  cancelFlashcardGeneration,
  clearFlashcardProposal,
  consumeFlashcardProposal,
  createFlashcardDeck,
  createGeneratedFlashcardDeck,
  createGeneratedFlashcardSuccessor,
  getDueFlashcards,
  getFlashcardDeck,
  isFlashcardCourseWritable,
  isCurrentFlashcardResponse,
  listFlashcardDecks,
  listFlashcardGenerationOperations,
  prepareFlashcardGenerationBrief,
  publishFlashcardCandidates,
  readyFlashcardDeck,
  requeueAgainCard,
  reviewFlashcard,
  type Flashcard,
  type FlashcardDeck,
  type FlashcardDeckView,
  type FlashcardGenerationOperation,
  type FlashcardGenerationBriefReceipt,
  type FlashcardGenerationOptions,
  type FlashcardRating,
  type FlashcardRequestScope,
} from "@/lib/flashcards-api";
import {
  FLASHCARDS_VIEW_PRESENTATION,
  flashcardGenerationFailurePresentation,
  flashcardGenerationStatePresentation,
  flashcardGenerationUnavailableCopy,
  type FlashcardCreateMode,
  type FlashcardsView,
} from "@/lib/flashcard-generation-presentation";
import { FlashcardStudySession } from "@/components/flashcards/study/FlashcardStudySession";

const emptyCard = { prompt: "", answer: "", objectiveIds: "" };

function idempotencyKey(): string {
  return (
    globalThis.crypto?.randomUUID?.() ??
    `flashcard-${Date.now()}-${Math.random().toString(36).slice(2)}`
  );
}

function errorText(cause: unknown): string {
  const message = cause instanceof Error ? cause.message.toLowerCase() : "";
  if (message.includes("stale") || message.includes("revision")) {
    return "This Course changed while you were working. Refresh and try again.";
  }
  if (message.includes("archived")) {
    return "This Course or deck is archived. Restore it before making changes.";
  }
  if (message.includes("not found") || message.includes("404")) {
    return "This Flashcard item is no longer available.";
  }
  return "We could not finish that Flashcard action. Please try again.";
}

export default function FlashcardsWorkspace() {
  const { t } = useTranslation();
  const { activeCourse, refresh: refreshCourses } = useCourses();
  const [identity, setIdentity] = useState<string | null>(null);
  const [decks, setDecks] = useState<FlashcardDeck[]>([]);
  const [decksHaveMore, setDecksHaveMore] = useState(false);
  const [selectedDeckId, setSelectedDeckId] = useState<string | null>(null);
  const [view, setView] = useState<FlashcardDeckView | null>(null);
  const [deckTitle, setDeckTitle] = useState("");
  const [generatedTitle, setGeneratedTitle] = useState("");
  const [generationFocus, setGenerationFocus] = useState("");
  const [generationCount, setGenerationCount] = useState(8);
  const [generationDifficulty, setGenerationDifficulty] =
    useState<FlashcardGenerationOptions["difficulty"]>("mixed");
  const [generationAnswerLength, setGenerationAnswerLength] =
    useState<FlashcardGenerationOptions["answer_length"]>("short");
  const [generationHints, setGenerationHints] = useState(true);
  const [generationCardTypes, setGenerationCardTypes] = useState<
    FlashcardGenerationOptions["card_type_mix"]
  >(["definition", "concept", "application"]);
  const [preparedBrief, setPreparedBrief] =
    useState<FlashcardGenerationBriefReceipt | null>(null);
  const [preparedSuccessor, setPreparedSuccessor] = useState(false);
  const [candidateOrder, setCandidateOrder] = useState<
    Record<string, string[]>
  >({});
  const [candidateReviewIndex, setCandidateReviewIndex] = useState<
    Record<string, number>
  >({});
  const [generationObjectives, setGenerationObjectives] = useState("");
  const [readySources, setReadySources] = useState<CourseSource[]>([]);
  const [selectedSourceIds, setSelectedSourceIds] = useState<string[]>([]);
  const [generationOperations, setGenerationOperations] = useState<
    FlashcardGenerationOperation[]
  >([]);
  const [generationAvailable, setGenerationAvailable] = useState(false);
  const [generationUnavailableReason, setGenerationUnavailableReason] =
    useState<string | null>(null);
  const [cardDraft, setCardDraft] = useState(emptyCard);
  const [reviewCards, setReviewCards] = useState<Flashcard[]>([]);
  const [reviewIndex, setReviewIndex] = useState(0);
  const [answerVisible, setAnswerVisible] = useState(false);
  const [hintVisible, setHintVisible] = useState(false);
  const [sourceVisible, setSourceVisible] = useState(false);
  const [reviewedCards, setReviewedCards] = useState(0);
  const [pageView, setPageView] = useState<FlashcardsView>("study");
  const [createMode, setCreateMode] = useState<FlashcardCreateMode>("choose");
  const [showCustomize, setShowCustomize] = useState(false);
  const [showArchived, setShowArchived] = useState(false);
  const [showPreviousActivity, setShowPreviousActivity] = useState(false);
  const [proposalOrigin, setProposalOrigin] = useState<
    "chat" | "practice_remediation" | null
  >(null);
  const [courseLoaded, setCourseLoaded] = useState(false);
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
  const scopeReady = Boolean(
    identity &&
      courseId &&
      scopeRef.current.identity === identity &&
      scopeRef.current.courseId === courseId,
  );
  const courseWritable =
    isFlashcardCourseWritable(activeCourse?.state) && scopeReady;
  const currentCard = reviewCards[reviewIndex] ?? null;
  const generationDeckTitle =
    generatedTitle.trim() ||
    `${activeCourse?.title?.trim() || t("Course")} ${t("flashcards")}`;
  const activeDecks = useMemo(
    () => decks.filter((deck) => deck.state !== "archived"),
    [decks],
  );
  const archivedDecks = useMemo(
    () => decks.filter((deck) => deck.state === "archived"),
    [decks],
  );
  const currentSourceDisclosure = useMemo(() => {
    if (!currentCard?.citations.length) return null;
    const names = currentCard.citations
      .map((citation) =>
        readySources.find(
          (source) => source.id === String(citation.source_id ?? ""),
        ),
      )
      .filter((source): source is CourseSource => Boolean(source))
      .map((source) => source.display_name);
    if (!names.length) return null;
    return (
      <p>
        {t("Grounded in {{sources}}.", {
          sources: Array.from(new Set(names)).join(", "),
        })}
      </p>
    );
  }, [currentCard, readySources, t]);

  const invalidate = useCallback(
    (nextIdentity: string | null, nextCourseId: string | null) => {
      if (
        scopeRef.current.identity !== nextIdentity ||
        scopeRef.current.courseId !== nextCourseId
      ) {
        clearFlashcardProposal(
          scopeRef.current.identity,
          scopeRef.current.courseId,
        );
      }
      const scope = {
        identity: nextIdentity,
        courseId: nextCourseId,
        epoch: ++epochRef.current,
        viewEpoch: 0,
      };
      scopeRef.current = scope;
      setDecks([]);
      setDecksHaveMore(false);
      setSelectedDeckId(null);
      setView(null);
      setDeckTitle("");
      setGeneratedTitle("");
      setGenerationFocus("");
      setGenerationCount(8);
      setGenerationDifficulty("mixed");
      setGenerationAnswerLength("short");
      setGenerationHints(true);
      setGenerationCardTypes(["definition", "concept", "application"]);
      setPreparedBrief(null);
      setPreparedSuccessor(false);
      setCandidateOrder({});
      setCandidateReviewIndex({});
      setGenerationObjectives("");
      setReadySources([]);
      setSelectedSourceIds([]);
      setGenerationOperations([]);
      setGenerationAvailable(false);
      setGenerationUnavailableReason(null);
      setCardDraft(emptyCard);
      setReviewCards([]);
      setReviewIndex(0);
      setAnswerVisible(false);
      setHintVisible(false);
      setSourceVisible(false);
      setReviewedCards(0);
      setPageView("study");
      setCreateMode("choose");
      setShowCustomize(false);
      setShowArchived(false);
      setShowPreviousActivity(false);
      setProposalOrigin(null);
      setCourseLoaded(false);
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
      const [listed, sources, operations, capabilities] = await Promise.all([
        listFlashcardDecks(scope.courseId),
        listCourseSources(scope.courseId),
        listFlashcardGenerationOperations(scope.courseId),
        getCourseCapabilities(),
      ]);
      if (!current(scope)) return;
      setDecks(listed);
      setDecksHaveMore(listed.length === 50);
      const ready = sources.filter((source) => source.state === "ready");
      setReadySources(ready);
      setSelectedSourceIds((selected) =>
        selected.filter((id) => ready.some((source) => source.id === id)),
      );
      setGenerationOperations(operations);
      setCandidateOrder(
        Object.fromEntries(
          operations
            .filter((operation) => operation.candidates?.length)
            .map((operation) => [
              operation.id,
              operation.candidates?.map((candidate) => candidate.candidate_id) ??
                [],
            ]),
        ),
      );
      setCandidateReviewIndex(
        Object.fromEntries(
          operations
            .filter((operation) => operation.candidates?.length)
            .map((operation) => [operation.id, 0]),
        ),
      );
      setGenerationAvailable(capabilities.flashcard_generation);
      setGenerationUnavailableReason(
        capabilities.grounded_generation_reason,
      );
      if (scope.identity) {
        const proposal = consumeFlashcardProposal(
          scope.identity,
          scope.courseId,
        );
        if (proposal) {
          setGeneratedTitle("Course flashcards");
          setGenerationFocus(proposal.brief.focus);
          setGenerationCount(proposal.brief.desired_count);
          setGenerationDifficulty(proposal.brief.difficulty);
          setGenerationAnswerLength(proposal.brief.answer_length);
          setGenerationHints(proposal.brief.include_hints);
          setGenerationCardTypes(proposal.brief.card_type_mix);
          setGenerationObjectives(proposal.objective_ids.join(", "));
          setSelectedSourceIds(
            proposal.source_snapshot
              .map((receipt) => receipt.source_id)
              .filter((id) => ready.some((source) => source.id === id)),
          );
          setPreparedBrief(proposal);
          setPreparedSuccessor(false);
          setProposalOrigin(
            proposal.origin.kind === "practice_remediation"
              ? "practice_remediation"
              : "chat",
          );
          setPageView("create");
          setCreateMode("grounded");
          setStatus("Your flashcard request is ready to review.");
        }
      }
      const first = listed.find((deck) => deck.state !== "archived") ?? null;
      setSelectedDeckId(first?.id ?? null);
      if (first) await loadDeck(scope, first);
      if (current(scope)) setCourseLoaded(true);
    },
    [current, loadDeck],
  );

  useEffect(() => {
    let alive = true;
    void fetchAuthStatus().then((auth) => {
      if (!alive) return;
      const nextIdentity = auth?.authenticated ? auth.user_id ?? null : null;
      setIdentity(nextIdentity);
      if (!nextIdentity) invalidate(null, null);
    });
    return () => {
      alive = false;
    };
  }, [invalidate]);

  useEffect(() => {
    const scope = invalidate(identity, courseId);
    if (!identity || !courseId) return;
    void loadCourse(scope).catch((cause) => {
      if (current(scope)) setError(errorText(cause));
    });
  }, [courseId, current, identity, invalidate, loadCourse]);

  useEffect(() => {
    const onAuthChanged = () => {
      invalidate(null, null);
      setIdentity(null);
      void fetchAuthStatus().then((auth) => {
        const nextIdentity = auth?.authenticated ? auth.user_id ?? null : null;
        setIdentity(nextIdentity);
      });
    };
    window.addEventListener("dt:auth-changed", onAuthChanged);
    return () => window.removeEventListener("dt:auth-changed", onAuthChanged);
  }, [invalidate]);

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
      setHintVisible(false);
      setSourceVisible(false);
      setReviewedCards(0);
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

  const openManualCreation = useCallback(() => {
    setCreateMode("manual");
    const manualDeck = activeDecks.find((deck) => deck.mode === "manual");
    if (manualDeck) {
      void selectDeck(manualDeck);
      return;
    }
    advanceView();
    setSelectedDeckId(null);
    setView(null);
  }, [activeDecks, advanceView, selectDeck]);

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

  const loadMoreDecks = useCallback(async () => {
    if (!activeCourse || !decksHaveMore || busy) return;
    const scope = scopeRef.current;
    setBusy(true);
    setError(null);
    try {
      const next = await listFlashcardDecks(activeCourse.id, decks.length);
      if (!current(scope)) return;
      setDecks((items) => [...items, ...next]);
      setDecksHaveMore(next.length === 50);
    } catch (cause) {
      if (current(scope)) setError(errorText(cause));
    } finally {
      if (current(scope)) setBusy(false);
    }
  }, [activeCourse, busy, current, decks.length, decksHaveMore]);

  const generationOptions = useCallback(
    (): FlashcardGenerationOptions => ({
      focus: generationFocus.trim() || generatedTitle.trim(),
      desired_count: generationCount,
      card_type_mix: generationCardTypes,
      difficulty: generationDifficulty,
      answer_length: generationAnswerLength,
      include_hints: generationHints,
      context_char_limit: 12_000,
    }),
    [
      generatedTitle,
      generationAnswerLength,
      generationCardTypes,
      generationCount,
      generationDifficulty,
      generationFocus,
      generationHints,
    ],
  );

  const prepareGeneration = useCallback(
    async (successor: boolean) => {
      if (
        !activeCourse ||
        !courseWritable ||
        !generationAvailable ||
        !selectedSourceIds.length ||
        (successor &&
          (!selectedDeck ||
            selectedDeck.mode !== "generated" ||
            selectedDeck.state !== "ready"))
      )
        return;
      const scope = scopeRef.current;
      setBusy(true);
      setError(null);
      try {
        const objectiveIds = generationObjectives
          .split(",")
          .map((value) => value.trim())
          .filter(Boolean);
        const brief = await prepareFlashcardGenerationBrief(
          activeCourse.id,
          generationDeckTitle,
          selectedSourceIds,
          objectiveIds,
          activeCourse.write_epoch,
          generationOptions(),
        );
        if (!current(scope)) return;
        setPreparedBrief(brief);
        setPreparedSuccessor(successor);
        setStatus("Review the generation brief before confirming provider use.");
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
      generationDeckTitle,
      generationObjectives,
      generationAvailable,
      generationOptions,
      selectedDeck,
      selectedSourceIds,
    ],
  );

  const confirmGeneration = useCallback(async () => {
    if (!activeCourse || !preparedBrief || !courseWritable) return;
    const scope = advanceView();
    setBusy(true);
    setError(null);
    try {
      const requested =
        preparedSuccessor && selectedDeck
          ? await createGeneratedFlashcardSuccessor(
              activeCourse.id,
              selectedDeck.id,
              generationDeckTitle,
              preparedBrief.source_snapshot.map((item) => item.source_id),
              preparedBrief.objective_ids,
              preparedBrief.course_write_epoch,
              idempotencyKey(),
              { ...preparedBrief.brief, origin: preparedBrief.origin },
            )
          : await createGeneratedFlashcardDeck(
              activeCourse.id,
              generationDeckTitle,
              preparedBrief.source_snapshot.map((item) => item.source_id),
              preparedBrief.objective_ids,
              preparedBrief.course_write_epoch,
              idempotencyKey(),
              { ...preparedBrief.brief, origin: preparedBrief.origin },
            );
      if (!current(scope)) return;
        setGenerationOperations((operations) => [
          requested.operation,
          ...operations.filter((item) => item.id !== requested.operation.id),
        ]);
        setGeneratedTitle("");
        setGenerationFocus("");
        setGenerationObjectives("");
        setPreparedBrief(null);
        setPageView("activity");
        setStatus(
          preparedSuccessor
            ? "Grounded successor generation queued."
            : "Grounded Flashcard generation queued.",
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
    generationDeckTitle,
    preparedBrief,
    preparedSuccessor,
    selectedDeck,
  ]);

  const publishCandidates = useCallback(
    async (operation: FlashcardGenerationOperation) => {
      if (!activeCourse || operation.state !== "awaiting_review") return;
      const selected = candidateOrder[operation.id] ?? [];
      if (!selected.length) return;
      const scope = scopeRef.current;
      setBusy(true);
      setError(null);
      try {
        const completed = await publishFlashcardCandidates(
          activeCourse.id,
          operation.id,
          selected,
          operation.candidate_revision,
        );
        if (!current(scope)) return;
        setGenerationOperations((operations) =>
          operations.map((item) => (item.id === completed.id ? completed : item)),
        );
        const listed = await listFlashcardDecks(activeCourse.id);
        if (!current(scope)) return;
        setDecks(listed);
        setDecksHaveMore(listed.length === 50);
        const published = listed.find((deck) => deck.id === completed.deck_id);
        if (published) {
          setSelectedDeckId(published.id);
          await loadDeck(scope, published);
        }
        if (current(scope)) {
          setPageView("study");
          setStatus(`${selected.length} cards published and ready to study.`);
        }
      } catch (cause) {
        if (current(scope)) setError(errorText(cause));
      } finally {
        if (current(scope)) setBusy(false);
      }
    },
    [activeCourse, candidateOrder, current, loadDeck],
  );

  const cancelGeneration = useCallback(
    async (operation: FlashcardGenerationOperation) => {
      if (!activeCourse) return;
      const scope = scopeRef.current;
      setBusy(true);
      setError(null);
      try {
        const cancelled = await cancelFlashcardGeneration(
          activeCourse.id,
          operation.id,
        );
        if (!current(scope)) return;
        setGenerationOperations((operations) =>
          operations.map((item) => (item.id === cancelled.id ? cancelled : item)),
        );
        setStatus(
          cancelled.state === "cancelling"
            ? "Cancellation requested. Provider work may still be finishing; its output cannot publish."
            : "Generation cancelled. The retained record cannot publish.",
        );
      } catch (cause) {
        if (current(scope)) setError(errorText(cause));
      } finally {
        if (current(scope)) setBusy(false);
      }
    },
    [activeCourse, current],
  );

  const refreshGeneration = useCallback(async () => {
    if (!activeCourse) return;
    const scope = scopeRef.current;
    setBusy(true);
    setError(null);
    try {
      const [operations, listed] = await Promise.all([
        listFlashcardGenerationOperations(activeCourse.id),
        listFlashcardDecks(activeCourse.id),
      ]);
      if (!current(scope)) return;
      setGenerationOperations(operations);
      setCandidateOrder(
        Object.fromEntries(
          operations
            .filter((operation) => operation.candidates?.length)
            .map((operation) => [
              operation.id,
              operation.candidates?.map(
                (candidate) => candidate.candidate_id,
              ) ?? [],
            ]),
        ),
      );
      setCandidateReviewIndex((indexes) =>
        Object.fromEntries(
          operations
            .filter((operation) => operation.candidates?.length)
            .map((operation) => [operation.id, indexes[operation.id] ?? 0]),
        ),
      );
      setDecks(listed);
      setDecksHaveMore(listed.length === 50);
      if (selectedDeckId) {
        const deck = listed.find((item) => item.id === selectedDeckId);
        if (deck) await loadDeck(scope, deck);
      }
      if (current(scope)) setStatus("Generation status refreshed.");
    } catch (cause) {
      if (current(scope)) setError(errorText(cause));
    } finally {
      if (current(scope)) setBusy(false);
    }
  }, [activeCourse, current, loadDeck, selectedDeckId]);

  useEffect(() => {
    if (
      !activeCourse ||
      !generationOperations.some((operation) =>
        ["queued", "running", "cancelling"].includes(operation.state),
      )
    ) {
      return;
    }
    const timer = window.setInterval(() => {
      if (!busy) void refreshGeneration();
    }, 3_000);
    return () => window.clearInterval(timer);
  }, [activeCourse, busy, generationOperations, refreshGeneration]);

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
      setHintVisible(false);
      setSourceVisible(false);
      setReviewedCards(0);
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
        setHintVisible(false);
        setSourceVisible(false);
        setReviewedCards((count) => count + 1);
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
    <main
      data-testid="flashcards-scroll-container"
      className="h-full overflow-y-auto bg-[var(--background)] text-[var(--foreground)] [scrollbar-gutter:stable]"
    >
      <CourseBar />
      <div className="mx-auto max-w-6xl space-y-5 px-5 py-6">
        <div>
          <div>
            <h1 className="text-2xl font-semibold">{t("Flashcards")}</h1>
            <p className="text-sm text-[var(--muted-foreground)]">
              {t("Study and create private Flashcards for this Course.")}
            </p>
          </div>
        </div>

        {!identity ? (
          <Notice>{t("Sign in to use private Course Flashcards.")}</Notice>
        ) : null}
        {identity && !activeCourse ? (
          <Notice>{t("Select or create a Course above to use Flashcards.")}</Notice>
        ) : null}

        {activeCourse && scopeReady && courseLoaded ? (
          <>
            <nav
              aria-label={t("Flashcards views")}
              className="flex gap-1 rounded-xl border border-[var(--border)] bg-[var(--card)] p-1"
            >
              {(Object.keys(FLASHCARDS_VIEW_PRESENTATION) as FlashcardsView[]).map(
                (item) => (
                  <button
                    key={item}
                    type="button"
                    aria-current={pageView === item ? "page" : undefined}
                    disabled={!scopeReady || !courseLoaded}
                    onClick={() => setPageView(item)}
                    className={`flex-1 rounded-lg px-4 py-2 text-sm font-medium ${
                      pageView === item
                        ? "bg-[var(--primary)] text-[var(--primary-foreground)]"
                        : "text-[var(--muted-foreground)] hover:bg-[var(--secondary)]"
                    } disabled:opacity-50`}
                  >
                    {t(FLASHCARDS_VIEW_PRESENTATION[item].label)}
                  </button>
                ),
              )}
            </nav>

            {pageView === "create" && createMode === "choose" ? (
              <section className="space-y-4 rounded-xl border border-[var(--border)] bg-[var(--card)] p-5">
                <div>
                  <h2 className="text-xl font-semibold">{t("Create flashcards")}</h2>
                  <p className="mt-1 text-sm text-[var(--muted-foreground)]">
                    {t("Choose how you want to build this deck.")}
                  </p>
                </div>
                <div className="grid gap-3 md:grid-cols-2">
                  {generationAvailable ? (
                    <button
                      type="button"
                      onClick={() => {
                        setCreateMode("grounded");
                        setSelectedSourceIds(readySources.map((source) => source.id));
                      }}
                      className="rounded-xl border border-[var(--border)] p-5 text-left hover:bg-[var(--secondary)]/50"
                    >
                      <span className="flex items-center gap-2 font-medium">
                        <Sparkles size={18} /> {t("Generate from Course materials")}
                      </span>
                      <span className="mt-2 block text-sm text-[var(--muted-foreground)]">
                        {readySources.length
                          ? t("Create cited cards from the ready material in this Course.")
                          : t("Attach a ready Course source before generating cards.")}
                      </span>
                    </button>
                  ) : (
                    <div className="rounded-xl border border-[var(--border)] p-5">
                      <p className="font-medium">{t("Card generation is unavailable right now")}</p>
                      <p className="mt-2 text-sm text-[var(--muted-foreground)]">
                        {t(flashcardGenerationUnavailableCopy(generationUnavailableReason))}
                      </p>
                    </div>
                  )}
                  <button
                    type="button"
                    onClick={openManualCreation}
                    className="rounded-xl border border-[var(--border)] p-5 text-left hover:bg-[var(--secondary)]/50"
                  >
                    <span className="font-medium">{t("Create manually")}</span>
                    <span className="mt-2 block text-sm text-[var(--muted-foreground)]">
                      {t("Write your own questions and answers without using a provider.")}
                    </span>
                  </button>
                </div>
              </section>
            ) : null}

            {pageView === "create" && createMode === "grounded" ? (
            <section className="space-y-4 rounded-xl border border-[var(--border)] bg-[var(--card)] p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h2 className="flex items-center gap-2 font-medium">
                    <Sparkles size={16} /> {t("Generate from Course materials")}
                  </h2>
                  <p className="text-sm text-[var(--muted-foreground)]">
                    {t("Tell TEEECHR what these cards should help you understand.")}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => {
                    setCreateMode("choose");
                    setPreparedBrief(null);
                  }}
                  className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm disabled:opacity-50"
                >
                  {t("Back")}
                </button>
              </div>
              {proposalOrigin ? (
                <Notice>
                  {proposalOrigin === "practice_remediation"
                    ? t("Prepared from your Practice results. Review it before generating cards.")
                    : t("Prepared from Course Chat. Review it before generating cards.")}
                </Notice>
              ) : null}
              {showCustomize ? (
              <input
                aria-label={t("Generated deck title")}
                value={generatedTitle}
                onChange={(event) => {
                  setGeneratedTitle(event.target.value);
                  setPreparedBrief(null);
                }}
                placeholder={t("Deck name")}
                disabled={!generationAvailable || !courseWritable || busy}
                className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm"
              />
              ) : null}
              <textarea
                aria-label={t("Flashcard generation focus")}
                value={generationFocus}
                onChange={(event) => {
                  setGenerationFocus(event.target.value);
                  setPreparedBrief(null);
                }}
                placeholder={t(
                  "What should these cards help you learn or compare?",
                )}
                disabled={!generationAvailable || !courseWritable || busy}
                className="min-h-20 w-full rounded-lg border border-[var(--border)] bg-[var(--background)] p-3 text-sm"
              />
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="grid gap-1 text-sm">
                  <span>{t("Card count")}</span>
                  <input
                    aria-label={t("Generated card count")}
                    type="number"
                    min={3}
                    max={48}
                    value={generationCount}
                    onChange={(event) => {
                      setGenerationCount(
                        Math.max(3, Math.min(48, Number(event.target.value) || 3)),
                      );
                      setPreparedBrief(null);
                    }}
                    disabled={!generationAvailable || !courseWritable || busy}
                    className="rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2"
                  />
                </label>
                <div className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm">
                  <span className="text-[var(--muted-foreground)]">{t("Course materials")}</span>
                  <p className="font-medium">
                    {selectedSourceIds.length} {t("selected")}
                  </p>
                </div>
              </div>
              <button
                type="button"
                aria-expanded={showCustomize}
                onClick={() => setShowCustomize((shown) => !shown)}
                className="inline-flex items-center gap-2 text-sm font-medium"
              >
                {showCustomize ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                {showCustomize ? t("Hide customization") : t("Customize")}
              </button>
              {showCustomize ? (
              <>
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="grid gap-1 text-sm">
                  <span>{t("Difficulty")}</span>
                  <select
                    aria-label={t("Flashcard difficulty")}
                    value={generationDifficulty}
                    onChange={(event) => {
                      setGenerationDifficulty(
                        event.target
                          .value as FlashcardGenerationOptions["difficulty"],
                      );
                      setPreparedBrief(null);
                    }}
                    disabled={!generationAvailable || !courseWritable || busy}
                    className="rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2"
                  >
                    {["introductory", "intermediate", "advanced", "mixed"].map(
                      (value) => (
                        <option key={value} value={value}>
                          {t(value)}
                        </option>
                      ),
                    )}
                  </select>
                </label>
                <label className="grid gap-1 text-sm">
                  <span>{t("Answer length")}</span>
                  <select
                    aria-label={t("Flashcard answer length")}
                    value={generationAnswerLength}
                    onChange={(event) => {
                      setGenerationAnswerLength(
                        event.target
                          .value as FlashcardGenerationOptions["answer_length"],
                      );
                      setPreparedBrief(null);
                    }}
                    disabled={!generationAvailable || !courseWritable || busy}
                    className="rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2"
                  >
                    <option value="short">{t("short")}</option>
                    <option value="medium">{t("medium")}</option>
                  </select>
                </label>
              </div>
              <fieldset className="space-y-2">
                <legend className="text-sm font-medium">{t("Card mix")}</legend>
                <div className="flex flex-wrap gap-2">
                  {(
                    [
                      "definition",
                      "concept",
                      "comparison",
                      "application",
                      "process",
                      "recall",
                    ] as const
                  ).map((cardType) => {
                    const checked = generationCardTypes.includes(cardType);
                    return (
                      <label
                        key={cardType}
                        className="flex items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-2 text-sm"
                      >
                        <input
                          type="checkbox"
                          checked={checked}
                          disabled={
                            !generationAvailable ||
                            !courseWritable ||
                            busy ||
                            (checked && generationCardTypes.length === 1)
                          }
                          onChange={() => {
                            setGenerationCardTypes((types) =>
                              checked
                                ? types.filter((item) => item !== cardType)
                                : [...types, cardType],
                            );
                            setPreparedBrief(null);
                          }}
                        />
                        {t(cardType)}
                      </label>
                    );
                  })}
                  <label className="flex items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-2 text-sm">
                    <input
                      type="checkbox"
                      checked={generationHints}
                      onChange={(event) => {
                        setGenerationHints(event.target.checked);
                        setPreparedBrief(null);
                      }}
                      disabled={!generationAvailable || !courseWritable || busy}
                    />
                    {t("Include hints")}
                  </label>
                </div>
              </fieldset>
              <p className="text-xs text-[var(--muted-foreground)]">
                {generationObjectives.trim()
                  ? t("Learning objectives from the prepared Course request will be applied automatically.")
                  : t("Course learning objectives are applied automatically when available.")}
              </p>
              </>
              ) : null}
              <div className="flex flex-wrap gap-2">
                {readySources.map((source) => {
                  const checked = selectedSourceIds.includes(source.id);
                  return (
                    <label
                      key={source.id}
                      className="flex items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-2 text-sm"
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        disabled={!generationAvailable || !courseWritable || busy}
                        onChange={() =>
                          {
                            setSelectedSourceIds((ids) =>
                              checked
                                ? ids.filter((id) => id !== source.id)
                                : [...ids, source.id],
                            );
                            setPreparedBrief(null);
                          }
                        }
                      />
                      {source.display_name}
                    </label>
                  );
                })}
                {!readySources.length ? (
                  <p className="text-sm text-[var(--muted-foreground)]">
                    {t("Attach and finish processing a Course source before generation.")}
                  </p>
                ) : null}
              </div>
              <div className="flex flex-wrap gap-2">
                <button
                  onClick={() => void prepareGeneration(false)}
                  disabled={
                    !courseWritable ||
                    !generationAvailable ||
                    busy ||
                    !generationFocus.trim() ||
                    !selectedSourceIds.length
                  }
                  className="rounded-lg bg-[var(--primary)] px-3 py-2 text-sm text-[var(--primary-foreground)] disabled:opacity-50"
                >
                  {t("Review request")}
                </button>
                <button
                  onClick={() => void prepareGeneration(true)}
                  disabled={
                    !courseWritable ||
                    !generationAvailable ||
                    busy ||
                    !generationFocus.trim() ||
                    !selectedSourceIds.length ||
                    selectedDeck?.mode !== "generated" ||
                    selectedDeck?.state !== "ready"
                  }
                  className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm disabled:opacity-50"
                >
                  {t("Create updated version")}
                </button>
              </div>
              {preparedBrief ? (
                <div className="space-y-3 rounded-xl border border-amber-500/50 bg-amber-500/5 p-4">
                  <div>
                    <h3 className="font-medium">{t("Confirm provider use")}</h3>
                    <p className="text-sm text-[var(--muted-foreground)]">
                      {t(
                        "This sends only the bounded brief and selected Course source excerpts to the configured provider. Nothing publishes until you review the candidates.",
                      )}
                    </p>
                  </div>
                  <dl className="grid gap-2 text-sm sm:grid-cols-2">
                    <div>
                      <dt className="text-[var(--muted-foreground)]">{t("Focus")}</dt>
                      <dd>{preparedBrief.brief.focus}</dd>
                    </div>
                    <div>
                      <dt className="text-[var(--muted-foreground)]">{t("Plan")}</dt>
                      <dd>
                        {preparedBrief.brief.desired_count} {t("cards")} ·{" "}
                        {preparedBrief.brief.difficulty} ·{" "}
                        {preparedBrief.brief.card_type_mix.join(", ")}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-[var(--muted-foreground)]">{t("Sources")}</dt>
                      <dd>{preparedBrief.source_snapshot.length}</dd>
                    </div>
                    <div>
                      <dt className="text-[var(--muted-foreground)]">{t("Provider")}</dt>
                      <dd>
                        {preparedBrief.provider_available
                          ? t("Available")
                          : t("Unavailable")}
                      </dd>
                    </div>
                  </dl>
                  <div className="flex flex-wrap gap-2">
                    <button
                      onClick={() => void confirmGeneration()}
                      disabled={busy || !preparedBrief.provider_available}
                      className="rounded-lg bg-[var(--primary)] px-3 py-2 text-sm text-[var(--primary-foreground)] disabled:opacity-50"
                    >
                      {t("Generate cards")}
                    </button>
                    <button
                      onClick={() => setPreparedBrief(null)}
                      disabled={busy}
                      className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm"
                    >
                      {t("Change request")}
                    </button>
                  </div>
                </div>
              ) : null}
              {false && generationOperations.length ? (
                <div className="grid gap-2 md:grid-cols-2">
                  {generationOperations.slice(0, 6).map((operation) => (
                    <div
                      key={operation.id}
                      className="space-y-3 rounded-lg border border-[var(--border)] px-3 py-3 text-sm"
                    >
                      <span className="font-medium">{operation.state}</span>
                      <span className="ml-2 text-[var(--muted-foreground)]">
                        {operation.source_snapshot.length} {t("sources")}
                      </span>
                      {operation.error_code ? (
                        <p className="text-xs text-red-600">{operation.error_code}</p>
                      ) : null}
                      {operation.state === "awaiting_review" &&
                      operation.candidates ? (
                        <div className="space-y-2">
                          <p className="text-xs text-[var(--muted-foreground)]">
                            {t(
                              "Choose and order candidates. Generated facts cannot be edited here.",
                            )}
                          </p>
                          {(candidateOrder[operation.id] ?? []).map(
                            (candidateId, index) => {
                              const candidate = operation.candidates?.find(
                                (item) => item.candidate_id === candidateId,
                              );
                              if (!candidate) return null;
                              return (
                                <article
                                  key={candidateId}
                                  className="rounded-lg bg-[var(--secondary)]/50 p-3"
                                >
                                  <div className="flex items-start justify-between gap-2">
                                    <div>
                                      <p className="font-medium">
                                        {candidate.prompt}
                                      </p>
                                      <p className="mt-1 text-xs">
                                        {candidate.answer}
                                      </p>
                                      <p className="mt-1 text-xs text-[var(--muted-foreground)]">
                                        {candidate.card_type} ·{" "}
                                        {candidate.citations.length} {t("citations")}
                                      </p>
                                      <ul className="mt-2 space-y-1 text-xs text-[var(--muted-foreground)]">
                                        {candidate.citations.map(
                                          (citation, citationIndex) => {
                                            const locator =
                                              typeof citation.locator ===
                                                "object" &&
                                              citation.locator !== null
                                                ? (citation.locator as Record<
                                                    string,
                                                    unknown
                                                  >)
                                                : {};
                                            const evidence =
                                              typeof locator.evidence_quote ===
                                              "string"
                                                ? locator.evidence_quote
                                                : null;
                                            return (
                                              <li
                                                key={`${String(citation.source_id ?? "source")}-${citationIndex}`}
                                              >
                                                {t("Source")}{" "}
                                                {String(
                                                  citation.source_id ??
                                                    citationIndex + 1,
                                                )}
                                                {evidence
                                                  ? ` — “${evidence}”`
                                                  : ""}
                                              </li>
                                            );
                                          },
                                        )}
                                      </ul>
                                    </div>
                                    <button
                                      aria-label={t("Exclude candidate")}
                                      onClick={() =>
                                        setCandidateOrder((orders) => ({
                                          ...orders,
                                          [operation.id]: (
                                            orders[operation.id] ?? []
                                          ).filter((id) => id !== candidateId),
                                        }))
                                      }
                                      className="rounded border border-[var(--border)] px-2 py-1 text-xs"
                                    >
                                      {t("Exclude")}
                                    </button>
                                  </div>
                                  <div className="mt-2 flex gap-2">
                                    <button
                                      disabled={index === 0}
                                      onClick={() =>
                                        setCandidateOrder((orders) => {
                                          const next = [
                                            ...(orders[operation.id] ?? []),
                                          ];
                                          [next[index - 1], next[index]] = [
                                            next[index],
                                            next[index - 1],
                                          ];
                                          return {
                                            ...orders,
                                            [operation.id]: next,
                                          };
                                        })
                                      }
                                      className="text-xs disabled:opacity-40"
                                    >
                                      {t("Move up")}
                                    </button>
                                    <button
                                      disabled={
                                        index ===
                                        (candidateOrder[operation.id]?.length ?? 0) -
                                          1
                                      }
                                      onClick={() =>
                                        setCandidateOrder((orders) => {
                                          const next = [
                                            ...(orders[operation.id] ?? []),
                                          ];
                                          [next[index], next[index + 1]] = [
                                            next[index + 1],
                                            next[index],
                                          ];
                                          return {
                                            ...orders,
                                            [operation.id]: next,
                                          };
                                        })
                                      }
                                      className="text-xs disabled:opacity-40"
                                    >
                                      {t("Move down")}
                                    </button>
                                  </div>
                                </article>
                              );
                            },
                          )}
                          {operation.candidates
                            .filter(
                              (candidate) =>
                                !(candidateOrder[operation.id] ?? []).includes(
                                  candidate.candidate_id,
                                ),
                            )
                            .map((candidate) => (
                              <button
                                key={candidate.candidate_id}
                                onClick={() =>
                                  setCandidateOrder((orders) => ({
                                    ...orders,
                                    [operation.id]: [
                                      ...(orders[operation.id] ?? []),
                                      candidate.candidate_id,
                                    ],
                                  }))
                                }
                                className="w-full rounded-lg border border-dashed border-[var(--border)] px-3 py-2 text-left text-xs text-[var(--muted-foreground)]"
                              >
                                {t("Include again")}: {candidate.prompt}
                              </button>
                            ))}
                          <div className="flex gap-2">
                            <button
                              onClick={() => void publishCandidates(operation)}
                              disabled={
                                busy ||
                                !(candidateOrder[operation.id] ?? []).length
                              }
                              className="rounded-lg bg-[var(--primary)] px-3 py-2 text-xs text-[var(--primary-foreground)] disabled:opacity-50"
                            >
                              {t("Publish selected cards")}
                            </button>
                            <button
                              onClick={() => void cancelGeneration(operation)}
                              disabled={busy}
                              className="rounded-lg border border-[var(--border)] px-3 py-2 text-xs"
                            >
                              {t("Cancel draft")}
                            </button>
                          </div>
                        </div>
                      ) : null}
                      {["queued", "running", "cancelling"].includes(
                        operation.state,
                      ) ? (
                        <button
                          onClick={() => void cancelGeneration(operation)}
                          disabled={busy}
                          className="rounded-lg border border-[var(--border)] px-3 py-1 text-xs"
                        >
                          {t("Cancel generation")}
                        </button>
                      ) : null}
                    </div>
                  ))}
                </div>
              ) : null}
            </section>
            ) : null}

            {pageView === "study" ||
            (pageView === "create" && createMode === "manual") ? (
            <div className="grid gap-5 lg:grid-cols-[280px_minmax(0,1fr)]">
            <section className="rounded-xl border border-[var(--border)] bg-[var(--card)] p-4">
              <h2 className="mb-3 font-medium">
                {pageView === "study" ? t("Your decks") : t("Manual decks")}
              </h2>
              {pageView === "create" ? (
                <button
                  type="button"
                  onClick={() => setCreateMode("choose")}
                  className="mb-3 text-sm text-[var(--muted-foreground)] underline underline-offset-4"
                >
                  {t("Back to creation choices")}
                </button>
              ) : null}
              {pageView === "create" ? (
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
              ) : null}
              <div className="space-y-1">
                {(pageView === "study"
                  ? activeDecks
                  : activeDecks.filter((deck) => deck.mode === "manual")
                ).map((deck) => (
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
                      {deck.state === "ready"
                        ? t("Ready to study")
                        : t("Still being built")}
                    </span>
                  </button>
                ))}
                {!activeDecks.length ? (
                  <p className="px-2 py-3 text-sm text-[var(--muted-foreground)]">
                    {t("No Flashcard decks yet.")}
                  </p>
                ) : null}
                {decksHaveMore ? (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void loadMoreDecks()}
                    className="w-full rounded-lg border border-[var(--border)] px-3 py-2 text-sm disabled:opacity-50"
                  >
                    {t("Load more decks")}
                  </button>
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
                        {view.review_summary.due_cards > 0
                          ? `${view.review_summary.due_cards} ${t("cards ready")}`
                          : selectedDeck.state === "ready"
                            ? t("You are caught up")
                            : `${view.cards.length} ${t("cards")}`}
                      </p>
                      <p className="mt-1 text-xs font-medium text-[var(--muted-foreground)]">
                        {selectedDeck.mode === "generated"
                          ? t("Grounded in the cited Course sources")
                          : t("Manual deck — not source-grounded")}
                      </p>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {selectedDeck.state === "draft" &&
                      selectedDeck.mode === "manual" ? (
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
                          <Play size={15} />{" "}
                          {view.review_summary.due_cards > 0
                            ? t("Start studying")
                            : t("Check for cards")}
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

                  {selectedDeck.state === "draft" &&
                  selectedDeck.mode === "manual" ? (
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

                  {selectedDeck.state === "draft" &&
                  selectedDeck.mode === "generated" ? (
                    <Notice>
                      {t(
                        "Grounded generation is still processing. Refresh status to load the immutable deck when it is ready.",
                      )}
                    </Notice>
                  ) : null}

                  <FlashcardStudySession
                    card={currentCard}
                    cardsLeft={Math.max(reviewCards.length - reviewIndex, 0)}
                    reviewedCards={reviewedCards}
                    answerVisible={answerVisible}
                    hintVisible={hintVisible}
                    sourceVisible={sourceVisible}
                    sourceDisclosure={currentSourceDisclosure}
                    busy={busy || !courseWritable}
                    complete={!currentCard && reviewCards.length > 0}
                    onReveal={() => setAnswerVisible(true)}
                    onRate={(rating) => void rate(rating)}
                    onHintVisibilityChange={setHintVisible}
                    onSourceVisibilityChange={setSourceVisible}
                    onDone={() => {
                      setReviewCards([]);
                      setReviewIndex(0);
                      setReviewedCards(0);
                    }}
                    onKeepStudying={() => void beginReview()}
                  />

                  <div className="space-y-2">
                    {view.cards.map((card) => (
                      <div
                        key={card.id}
                        className="rounded-lg border border-[var(--border)] px-3 py-2"
                      >
                        <p className="text-sm font-medium">{card.prompt}</p>
                        {card.hint ? (
                          <p className="mt-1 text-xs text-[var(--muted-foreground)]">
                            {t("Includes a hint")}
                          </p>
                        ) : null}
                      </div>
                    ))}
                  </div>
                </div>
              ) : (
                <div className="space-y-3">
                  <p className="text-sm text-[var(--muted-foreground)]">
                    {archivedDecks.length
                      ? t("No active decks. Restore an archived deck or create a new one.")
                      : t("Create your first deck to start studying.")}
                  </p>
                  <button
                    type="button"
                    onClick={() => {
                      setCreateMode("choose");
                      setPageView("create");
                    }}
                    className="rounded-lg bg-[var(--primary)] px-3 py-2 text-sm text-[var(--primary-foreground)]"
                  >
                    {t("Create flashcards")}
                  </button>
                </div>
              )}
            </section>
            </div>
            ) : null}

            {pageView === "study" && archivedDecks.length ? (
              <section className="rounded-xl border border-[var(--border)] bg-[var(--card)] p-4">
                <button
                  type="button"
                  aria-expanded={showArchived}
                  onClick={() => setShowArchived((shown) => !shown)}
                  className="flex w-full items-center justify-between text-left font-medium"
                >
                  <span>{t("Archived decks")} ({archivedDecks.length})</span>
                  {showArchived ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                </button>
                {showArchived ? (
                  <div className="mt-3 grid gap-2 sm:grid-cols-2">
                    {archivedDecks.map((deck) => (
                      <button
                        key={deck.id}
                        type="button"
                        onClick={() => void selectDeck(deck)}
                        className="rounded-lg border border-[var(--border)] px-3 py-2 text-left text-sm"
                      >
                        <span className="block font-medium">{deck.title}</span>
                        <span className="text-xs text-[var(--muted-foreground)]">
                          {t("Select to restore")}
                        </span>
                      </button>
                    ))}
                  </div>
                ) : null}
              </section>
            ) : null}

            {pageView === "activity" ? (
              <section className="space-y-4 rounded-xl border border-[var(--border)] bg-[var(--card)] p-5">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <h2 className="text-xl font-semibold">{t("Card creation activity")}</h2>
                    <p className="mt-1 text-sm text-[var(--muted-foreground)]">
                      {t("Track active requests and review card drafts before publishing.")}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => void refreshGeneration()}
                    disabled={busy}
                    className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm disabled:opacity-50"
                  >
                    {t("Refresh")}
                  </button>
                </div>
                {generationOperations
                  .filter(
                    (operation) =>
                      operation.state !== "completed" &&
                      operation.state !== "cancelled",
                  )
                  .map((operation) => {
                    const presentation = flashcardGenerationStatePresentation(
                      operation.state,
                    );
                    const selected = candidateOrder[operation.id] ?? [];
                    const reviewIndexForOperation = Math.min(
                      candidateReviewIndex[operation.id] ?? 0,
                      Math.max((operation.candidates?.length ?? 1) - 1, 0),
                    );
                    const failure =
                      operation.state === "failed"
                        ? flashcardGenerationFailurePresentation(
                            operation.error_code,
                            false,
                          )
                        : null;
                    return (
                      <article
                        key={operation.id}
                        className="space-y-4 rounded-xl border border-[var(--border)] p-4"
                      >
                        <div>
                          <h3 className="font-medium">
                            {failure?.title ?? t(presentation.label)}
                          </h3>
                          <p className="text-sm text-[var(--muted-foreground)]">
                            {failure?.detail ?? t(presentation.description)}
                          </p>
                          <p className="mt-1 text-xs text-[var(--muted-foreground)]">
                            {operation.source_snapshot.length} {t("Course materials")}
                          </p>
                        </div>
                        {operation.state === "failed" ? (
                          <div className="flex flex-wrap gap-2">
                            <button
                              type="button"
                              onClick={() => {
                                setGeneratedTitle("Course flashcards");
                                setGenerationFocus(operation.generation_brief.focus);
                                setGenerationCount(
                                  operation.generation_brief.desired_count,
                                );
                                setGenerationDifficulty(
                                  operation.generation_brief.difficulty,
                                );
                                setGenerationAnswerLength(
                                  operation.generation_brief.answer_length,
                                );
                                setGenerationHints(
                                  operation.generation_brief.include_hints,
                                );
                                setGenerationCardTypes(
                                  operation.generation_brief.card_type_mix,
                                );
                                setGenerationObjectives(
                                  operation.objective_ids.join(", "),
                                );
                                setSelectedSourceIds(
                                  operation.source_snapshot.map(
                                    (source) => source.source_id,
                                  ),
                                );
                                setPreparedBrief(null);
                                setCreateMode("grounded");
                                setPageView("create");
                              }}
                              className="rounded-lg bg-[var(--primary)] px-3 py-2 text-sm text-[var(--primary-foreground)]"
                            >
                              {t("Change request")}
                            </button>
                            <button
                              type="button"
                              onClick={() => {
                                openManualCreation();
                                setPageView("create");
                              }}
                              className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm"
                            >
                              {t("Create manually")}
                            </button>
                          </div>
                        ) : null}
                        {operation.state === "awaiting_review" &&
                        operation.candidates ? (
                          <div className="space-y-3">
                            <p className="text-sm font-medium">
                              {selected.length} {t("cards selected")}
                            </p>
                            <p className="text-xs text-[var(--muted-foreground)]">
                              {t("Candidate")} {reviewIndexForOperation + 1}{" "}
                              {t("of")} {operation.candidates.length}
                            </p>
                            {operation.candidates.map((candidate, candidateIndex) => {
                              if (candidateIndex !== reviewIndexForOperation) {
                                return null;
                              }
                              const included = selected.includes(
                                candidate.candidate_id,
                              );
                              const index = selected.indexOf(
                                candidate.candidate_id,
                              );
                              const sourceNames = candidate.citations
                                .map((citation) =>
                                  readySources.find(
                                    (source) =>
                                      source.id ===
                                      String(citation.source_id ?? ""),
                                  ),
                                )
                                .filter(
                                  (source): source is CourseSource =>
                                    Boolean(source),
                                )
                                .map((source) => source.display_name);
                              return (
                                <div
                                  key={candidate.candidate_id}
                                  className={`space-y-3 rounded-lg border p-4 ${
                                    included
                                      ? "border-[var(--border)]"
                                      : "border-dashed border-[var(--border)] opacity-70"
                                  }`}
                                >
                                  <div>
                                    <p className="font-medium">{candidate.prompt}</p>
                                    <p className="mt-2 text-sm">{candidate.answer}</p>
                                  </div>
                                  {sourceNames.length ? (
                                    <details className="text-xs text-[var(--muted-foreground)]">
                                      <summary className="cursor-pointer">
                                        {t("Show sources")}
                                      </summary>
                                      <p className="mt-1">
                                        {Array.from(new Set(sourceNames)).join(", ")}
                                      </p>
                                    </details>
                                  ) : null}
                                  <div className="flex flex-wrap gap-2">
                                    <button
                                      type="button"
                                      onClick={() =>
                                        setCandidateOrder((orders) => ({
                                          ...orders,
                                          [operation.id]: included
                                            ? selected.filter(
                                                (id) =>
                                                  id !== candidate.candidate_id,
                                              )
                                            : [
                                                ...selected,
                                                candidate.candidate_id,
                                              ],
                                        }))
                                      }
                                      aria-label={`${
                                        included ? t("Remove") : t("Keep")
                                      }: ${candidate.prompt}`}
                                      className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs"
                                    >
                                      {included ? t("Remove") : t("Keep")}
                                    </button>
                                    {included ? (
                                      <>
                                        <button
                                          type="button"
                                          disabled={index === 0}
                                          onClick={() =>
                                            setCandidateOrder((orders) => {
                                              const next = [...selected];
                                              [next[index - 1], next[index]] = [
                                                next[index],
                                                next[index - 1],
                                              ];
                                              return {
                                                ...orders,
                                                [operation.id]: next,
                                              };
                                            })
                                          }
                                          className="text-xs disabled:opacity-40"
                                        >
                                          {t("Move up")}
                                        </button>
                                        <button
                                          type="button"
                                          disabled={index === selected.length - 1}
                                          onClick={() =>
                                            setCandidateOrder((orders) => {
                                              const next = [...selected];
                                              [next[index], next[index + 1]] = [
                                                next[index + 1],
                                                next[index],
                                              ];
                                              return {
                                                ...orders,
                                                [operation.id]: next,
                                              };
                                            })
                                          }
                                          className="text-xs disabled:opacity-40"
                                        >
                                          {t("Move down")}
                                        </button>
                                      </>
                                    ) : null}
                                  </div>
                                </div>
                              );
                            })}
                            <div className="flex items-center justify-between gap-2">
                              <button
                                type="button"
                                disabled={reviewIndexForOperation === 0}
                                onClick={() =>
                                  setCandidateReviewIndex((indexes) => ({
                                    ...indexes,
                                    [operation.id]: Math.max(
                                      reviewIndexForOperation - 1,
                                      0,
                                    ),
                                  }))
                                }
                                className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm disabled:opacity-40"
                              >
                                {t("Previous candidate")}
                              </button>
                              <button
                                type="button"
                                disabled={
                                  reviewIndexForOperation ===
                                  operation.candidates.length - 1
                                }
                                onClick={() =>
                                  setCandidateReviewIndex((indexes) => ({
                                    ...indexes,
                                    [operation.id]: Math.min(
                                      reviewIndexForOperation + 1,
                                      operation.candidates!.length - 1,
                                    ),
                                  }))
                                }
                                className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm disabled:opacity-40"
                              >
                                {t("Next candidate")}
                              </button>
                            </div>
                            <details className="rounded-lg border border-[var(--border)] p-3">
                              <summary className="cursor-pointer text-sm font-medium">
                                {t("Review selected order")} ({selected.length})
                              </summary>
                              <ol className="mt-2 space-y-1 text-sm">
                                {selected.map((candidateId, index) => (
                                  <li key={candidateId}>
                                    {index + 1}.{" "}
                                    {operation.candidates?.find(
                                      (candidate) =>
                                        candidate.candidate_id === candidateId,
                                    )?.prompt ?? t("Selected card")}
                                  </li>
                                ))}
                              </ol>
                            </details>
                            <div className="flex flex-wrap gap-2">
                              <button
                                type="button"
                                onClick={() => void publishCandidates(operation)}
                                disabled={busy || selected.length === 0}
                                className="rounded-lg bg-[var(--primary)] px-3 py-2 text-sm text-[var(--primary-foreground)] disabled:opacity-50"
                              >
                                {t("Publish")} {selected.length}{" "}
                                {selected.length === 1 ? t("card") : t("cards")}
                              </button>
                              <button
                                type="button"
                                onClick={() => void cancelGeneration(operation)}
                                disabled={busy}
                                className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm"
                              >
                                {t("Cancel draft")}
                              </button>
                            </div>
                          </div>
                        ) : null}
                        {["queued", "running", "cancelling"].includes(
                          operation.state,
                        ) ? (
                          <button
                            type="button"
                            onClick={() => void cancelGeneration(operation)}
                            disabled={busy}
                            className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm disabled:opacity-50"
                          >
                            {t("Cancel")}
                          </button>
                        ) : null}
                      </article>
                    );
                  })}
                {!generationOperations.some(
                  (operation) =>
                    operation.state !== "completed" &&
                    operation.state !== "cancelled",
                ) ? (
                  <Notice>{t("No card creation needs your attention.")}</Notice>
                ) : null}
                {generationOperations.some((operation) =>
                  ["completed", "cancelled"].includes(operation.state),
                ) ? (
                  <div>
                    <button
                      type="button"
                      aria-expanded={showPreviousActivity}
                      onClick={() =>
                        setShowPreviousActivity((shown) => !shown)
                      }
                      className="inline-flex items-center gap-2 text-sm font-medium"
                    >
                      {showPreviousActivity ? (
                        <ChevronUp size={16} />
                      ) : (
                        <ChevronDown size={16} />
                      )}
                      {t("Previous activity")}
                    </button>
                    {showPreviousActivity ? (
                      <ul className="mt-3 space-y-2">
                        {generationOperations
                          .filter((operation) =>
                            ["completed", "cancelled"].includes(operation.state),
                          )
                          .map((operation) => {
                            const presentation =
                              flashcardGenerationStatePresentation(
                                operation.state,
                              );
                            return (
                              <li
                                key={operation.id}
                                className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm"
                              >
                                {t(presentation.label)}
                              </li>
                            );
                          })}
                      </ul>
                    ) : null}
                  </div>
                ) : null}
              </section>
            ) : null}
          </>
        ) : activeCourse && identity ? (
          <Notice>{t("Loading this Course's Flashcards…")}</Notice>
        ) : null}

        {busy ? (
          <p role="status" className="flex items-center gap-2 text-sm text-[var(--muted-foreground)]">
            <Loader2 size={15} className="animate-spin" /> {t("Saving…")}
          </p>
        ) : null}
        {status ? <p role="status" className="text-sm text-emerald-600">{status}</p> : null}
        {error ? <p role="alert" className="text-sm text-red-600">{error}</p> : null}
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
