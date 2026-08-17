"use client";

import { useEffect, useState } from "react";
import {
  BookOpen,
  BrainCircuit,
  ClipboardCheck,
  Layers3,
  RotateCcw,
} from "lucide-react";
import {
  getCourseChatReadiness,
  getCourseLearning,
  type CourseChatReadiness,
} from "@/lib/course-api";
import type { MasteryMap, NextStep } from "@/lib/learning-api";
import {
  getFlashcardDeck,
  listFlashcardDecks,
  type FlashcardDeckView,
} from "@/lib/flashcards-api";
import {
  formatPracticeScore,
  listPracticeAttempts,
  listPracticeSets,
  type QuizAttempt,
} from "@/lib/practice-api";
import { useCourseShell } from "@/components/courses/CourseShell";

interface PracticeSummary {
  setCount: number;
  completedCount: number;
  latestScore: string | null;
  bestScore: string | null;
  latestAt: number | null;
}

interface MasterySummary {
  averageMasteryPct: number;
  mastered: number;
  learning: number;
  newObjectives: number;
  total: number;
  dueReviews: number;
  next: NextStep | null;
}

interface ReviewSummary {
  readyDeckCount: number;
  totalActiveCards: number;
  dueCards: number;
  reviewCount: number;
}

interface OverviewData {
  readiness: CourseChatReadiness | null;
  practice: PracticeSummary | null;
  mastery: MasterySummary | null;
  review: ReviewSummary | null;
}

const EMPTY_OVERVIEW: OverviewData = {
  readiness: null,
  practice: null,
  mastery: null,
  review: null,
};

async function tryLoad<T>(load: () => Promise<T>): Promise<T | null> {
  try {
    return await load();
  } catch {
    return null;
  }
}

function scoreFraction(attempt: QuizAttempt): number | null {
  const score = attempt.score;
  if (!score) return null;
  if (typeof score.fraction === "number" && Number.isFinite(score.fraction)) {
    return score.fraction;
  }
  if (
    typeof score.correct === "number" &&
    typeof score.total === "number" &&
    score.total > 0
  ) {
    return score.correct / score.total;
  }
  return null;
}

async function loadPracticeSummary(courseId: string): Promise<PracticeSummary> {
  const sets = await listPracticeSets(courseId);
  const activeSets = sets.filter((practiceSet) => practiceSet.state !== "archived");
  const attempts = (
    await Promise.all(
      activeSets.map((practiceSet) =>
        listPracticeAttempts(courseId, practiceSet.id).catch(() => []),
      ),
    )
  ).flat();
  const completed = attempts.filter((attempt) => attempt.state === "graded");
  const scored = completed
    .map((attempt) => ({ attempt, fraction: scoreFraction(attempt) }))
    .filter(
      (item): item is { attempt: QuizAttempt; fraction: number } =>
        item.fraction !== null,
    );
  const latest =
    [...completed].sort((left, right) => right.updated_at - left.updated_at)[0] ??
    null;
  const best =
    [...scored].sort((left, right) => right.fraction - left.fraction)[0]?.attempt ??
    null;

  return {
    setCount: activeSets.length,
    completedCount: completed.length,
    latestScore: latest ? formatPracticeScore(latest.score) : null,
    bestScore: best ? formatPracticeScore(best.score) : null,
    latestAt: latest?.updated_at ?? null,
  };
}

function masterySummaryFromMap(
  map: MasteryMap,
  next: NextStep | null,
): MasterySummary | null {
  const knowledgePoints = map.modules.flatMap((module) => module.knowledge_points);
  const total = map.counts.total;
  if (!total || !knowledgePoints.length) return null;
  const averageMasteryPct = Math.round(
    (knowledgePoints.reduce((sum, point) => sum + point.mastery, 0) /
      knowledgePoints.length) *
      100,
  );
  return {
    averageMasteryPct,
    mastered: map.counts.mastered,
    learning: map.counts.learning,
    newObjectives: map.counts.new,
    total,
    dueReviews: map.due_reviews,
    next,
  };
}

async function loadMasterySummary(courseId: string): Promise<MasterySummary | null> {
  const learning = await getCourseLearning(courseId);
  const rawMap: unknown = learning.map;
  if (!rawMap || Array.isArray(rawMap)) return null;
  return masterySummaryFromMap(rawMap as MasteryMap, learning.next ?? null);
}

async function loadReviewSummary(courseId: string): Promise<ReviewSummary> {
  const decks = await listFlashcardDecks(courseId);
  const readyDecks = decks.filter((deck) => deck.state === "ready");
  const views = (
    await Promise.all(
      readyDecks.map((deck) =>
        getFlashcardDeck(courseId, deck.id).catch(() => null),
      ),
    )
  ).filter((view): view is FlashcardDeckView => view !== null);
  return {
    readyDeckCount: readyDecks.length,
    totalActiveCards: views.reduce(
      (total, view) => total + view.review_summary.total_active_cards,
      0,
    ),
    dueCards: views.reduce((total, view) => total + view.review_summary.due_cards, 0),
    reviewCount: views.reduce((total, view) => total + view.review_summary.review_count, 0),
  };
}

export default function CourseOverview() {
  const courseShell = useCourseShell();
  const course = courseShell?.course;
  const [loading, setLoading] = useState(true);
  const [overview, setOverview] = useState<OverviewData>(EMPTY_OVERVIEW);
  const disabled = course ? course.state !== "active" : true;

  useEffect(() => {
    let cancelled = false;
    if (!course || disabled) {
      setLoading(false);
      setOverview(EMPTY_OVERVIEW);
      return () => {
        cancelled = true;
      };
    }

    setLoading(true);
    void Promise.all([
      tryLoad(() => getCourseChatReadiness(course.id)),
      tryLoad(() => loadPracticeSummary(course.id)),
      tryLoad(() => loadMasterySummary(course.id)),
      tryLoad(() => loadReviewSummary(course.id)),
    ]).then(([readiness, practice, mastery, review]) => {
      if (cancelled) return;
      setOverview({ readiness, practice, mastery, review });
      setLoading(false);
    });

    return () => {
      cancelled = true;
    };
  }, [course?.id, disabled]);

  if (!course) return null;

  const readyMaterials = overview.readiness?.counts.ready ?? null;
  const totalMaterials = overview.readiness?.counts.total ?? null;

  return (
    <main
      data-testid="course-overview-dashboard"
      className="min-h-full px-5 py-7 sm:px-8 sm:py-9"
    >
      <div className="mx-auto w-full max-w-6xl">
        <header>
          <h2 className="mt-0 text-2xl font-semibold tracking-tight text-[var(--foreground)] sm:text-3xl">
            Course Overview
          </h2>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-[var(--muted-foreground)]">
            Your current materials, learning progress, practice results, and flashcard status.
          </p>
        </header>

        {disabled ? (
          <div className="mt-7 flex items-start gap-3 rounded-xl border border-[var(--border)] bg-[var(--card)] px-4 py-3 text-sm text-[var(--muted-foreground)]">
            <RotateCcw size={16} className="mt-0.5 shrink-0" />
            Restore this Course from Classes before opening its learning tools.
          </div>
        ) : null}

        <section aria-labelledby="course-status-heading" className="mt-9">
          <h3 id="course-status-heading" className="sr-only">
            Course status
          </h3>
          <div className="grid grid-cols-2 border-y border-[var(--border)] [&>*:nth-child(even)]:border-l [&>*:nth-child(even)]:border-[var(--border)] [&>*:nth-child(n+3)]:border-t [&>*:nth-child(n+3)]:border-[var(--border)] sm:grid-cols-4 sm:[&>*:nth-child(n+3)]:border-t-0 sm:divide-x sm:divide-[var(--border)] sm:[&>*:nth-child(even)]:border-l-0">
            <SummaryMetric
              label="Materials"
              value={
                loading
                  ? "—"
                  : readyMaterials === null
                    ? "—"
                    : `${readyMaterials}/${totalMaterials}`
              }
              detail="ready sources"
            />
            <SummaryMetric
              label="Practice"
              value={
                loading ? "—" : overview.practice?.completedCount.toString() ?? "—"
              }
              detail="completed tests"
            />
            <SummaryMetric
              label="Mastery"
              value={
                loading
                  ? "—"
                  : overview.mastery
                    ? `${overview.mastery.averageMasteryPct}%`
                    : "—"
              }
              detail={overview.mastery ? "average mastery" : "not started"}
            />
            <SummaryMetric
              label="Flashcards"
              value={loading ? "—" : overview.review?.dueCards.toString() ?? "—"}
              detail="cards due"
            />
          </div>
        </section>

        <div className="mt-10 grid gap-x-12 gap-y-10 lg:grid-cols-2">
          <OverviewSection
            icon={<BookOpen size={18} />}
            title="Materials"
            testId="course-overview-materials"
          >
            {overview.readiness ? (
              <>
                <div className="grid grid-cols-3 gap-4">
                  <InlineStat label="Ready" value={overview.readiness.counts.ready} />
                  <InlineStat
                    label="Processing"
                    value={overview.readiness.counts.processing}
                  />
                  <InlineStat
                    label="Unavailable"
                    value={overview.readiness.counts.unavailable}
                  />
                </div>
                <p className="mt-5 text-sm leading-6 text-[var(--muted-foreground)]">
                  {overview.readiness.state === "no_materials"
                    ? "No Course materials have been added yet."
                    : `${readyMaterials} of ${totalMaterials} Course materials are ready for learning tools.`}
                </p>
              </>
            ) : (
              <EmptyState>Material status is unavailable right now.</EmptyState>
            )}
          </OverviewSection>

          <OverviewSection
            icon={<ClipboardCheck size={18} />}
            title="Practice performance"
            testId="course-overview-practice"
          >
            {overview.practice ? (
              <>
                <div className="grid grid-cols-2 gap-x-6 gap-y-5 sm:grid-cols-4">
                  <InlineStat label="Sets" value={overview.practice.setCount} />
                  <InlineStat
                    label="Completed"
                    value={overview.practice.completedCount}
                  />
                  <InlineStat
                    label="Latest"
                    value={overview.practice.latestScore ?? "—"}
                  />
                  <InlineStat label="Best" value={overview.practice.bestScore ?? "—"} />
                </div>
                <p className="mt-5 text-sm leading-6 text-[var(--muted-foreground)]">
                  {overview.practice.completedCount
                    ? `Last completed ${formatDate(overview.practice.latestAt)}.`
                    : "No practice tests completed yet."}
                </p>
              </>
            ) : (
              <EmptyState>Practice status is unavailable right now.</EmptyState>
            )}
          </OverviewSection>

          <OverviewSection
            icon={<BrainCircuit size={18} />}
            title="Mastery progress"
            testId="course-overview-mastery"
          >
            {overview.mastery ? (
              <>
                <div className="flex items-end justify-between gap-4">
                  <div>
                    <p className="text-3xl font-semibold tracking-tight text-[var(--foreground)]">
                      {overview.mastery.averageMasteryPct}%
                    </p>
                    <p className="mt-1 text-sm text-[var(--muted-foreground)]">
                      average mastery
                    </p>
                  </div>
                  <p className="text-right text-sm text-[var(--muted-foreground)]">
                    {overview.mastery.mastered} of {overview.mastery.total} mastered
                  </p>
                </div>
                <div
                  className="mt-5 h-2 overflow-hidden rounded-full bg-[var(--muted)]"
                  aria-label={`${overview.mastery.averageMasteryPct}% average mastery`}
                >
                  <div
                    className="h-full rounded-full bg-[var(--foreground)]"
                    style={{
                      width: `${Math.min(100, Math.max(0, overview.mastery.averageMasteryPct))}%`,
                    }}
                  />
                </div>
                <div className="mt-5 grid grid-cols-3 gap-4">
                  <InlineStat label="Mastered" value={overview.mastery.mastered} />
                  <InlineStat label="Learning" value={overview.mastery.learning} />
                  <InlineStat label="New" value={overview.mastery.newObjectives} />
                </div>
                <p className="mt-5 text-sm leading-6 text-[var(--muted-foreground)]">
                    {overview.mastery.next?.action === "complete"
                      ? "All objectives are mastered and nothing is due."
                    : overview.mastery.next
                      ? `Next focus: ${overview.mastery.next.knowledge_point_name}.`
                      : `${overview.mastery.dueReviews} mastery check${overview.mastery.dueReviews === 1 ? "" : "s"} due.`}
                </p>
              </>
            ) : (
              <EmptyState>Mastery tracking has not started for this Course yet.</EmptyState>
            )}
          </OverviewSection>

          <OverviewSection
            icon={<Layers3 size={18} />}
            title="Flashcards"
            testId="course-overview-review"
          >
            {overview.review?.readyDeckCount ? (
              <>
                <div className="grid grid-cols-3 gap-4">
                  <InlineStat label="Cards" value={overview.review.totalActiveCards} />
                  <InlineStat label="Due" value={overview.review.dueCards} />
                  <InlineStat label="Sessions" value={overview.review.reviewCount} />
                </div>
                <p className="mt-5 text-sm leading-6 text-[var(--muted-foreground)]">
                  {overview.review.dueCards
                    ? `${overview.review.dueCards} card${overview.review.dueCards === 1 ? "" : "s"} ready to study.`
                    : "You are caught up on flashcards."}
                </p>
              </>
            ) : (
              <EmptyState>No flashcards are ready for this Course yet.</EmptyState>
            )}
          </OverviewSection>
        </div>

        <p className="mt-10 border-t border-[var(--border)] pt-5 text-xs text-[var(--muted-foreground)]">
          Use the Course tabs above when you want to open a specific learning area.
        </p>
      </div>
    </main>
  );
}

function SummaryMetric({
  label,
  value,
  detail,
}: {
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <div className="px-4 py-4 sm:px-5 sm:py-5 first:sm:pl-0 last:sm:pr-0">
      <p className="text-xs font-medium uppercase tracking-[0.12em] text-[var(--muted-foreground)]">
        {label}
      </p>
      <p className="mt-1 text-xl font-semibold tracking-tight text-[var(--foreground)] sm:mt-2 sm:text-2xl">
        {value}
      </p>
      <p className="mt-1 text-xs text-[var(--muted-foreground)]">{detail}</p>
    </div>
  );
}

function OverviewSection({
  icon,
  title,
  testId,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  testId: string;
  children: React.ReactNode;
}) {
  return (
    <section data-testid={testId} className="border-t border-[var(--border)] pt-5">
      <div className="flex items-center gap-2 text-[var(--foreground)]">
        <span className="text-[var(--muted-foreground)]">{icon}</span>
        <h3 className="font-semibold">{title}</h3>
      </div>
      <div className="mt-5">{children}</div>
    </section>
  );
}

function InlineStat({ label, value }: { label: string; value: number | string }) {
  return (
    <div>
      <p className="text-xl font-semibold tracking-tight text-[var(--foreground)]">{value}</p>
      <p className="mt-1 text-xs text-[var(--muted-foreground)]">{label}</p>
    </div>
  );
}

function EmptyState({ children }: { children: React.ReactNode }) {
  return <p className="text-sm leading-6 text-[var(--muted-foreground)]">{children}</p>;
}

function formatDate(timestamp: number | null): string {
  if (!timestamp) return "recently";
  return new Date(timestamp * 1000).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}
