"use client";

import { useCallback, useMemo, useState } from "react";
import { ChevronLeft, ChevronRight, Send } from "lucide-react";
import { useTranslation } from "react-i18next";
import MarkdownRenderer from "@/components/common/MarkdownRenderer";
import { useUnifiedChat } from "@/context/UnifiedChatContext";
import type { QuizQuestion } from "@/lib/quiz-types";
import { buildInteractiveQuizSubmission } from "@/lib/quiz-submission";

interface ChatQuizViewerProps {
  intro?: string;
  questions: QuizQuestion[];
}

export default function ChatQuizViewer({
  intro,
  questions,
}: ChatQuizViewerProps) {
  const { t } = useTranslation();
  const { sendMessage, state } = useUnifiedChat();
  const [idx, setIdx] = useState(0);
  const [answers, setAnswers] = useState<Record<number, string>>({});

  const total = questions.length;
  const currentQuestion = questions[idx];
  const selectedAnswer = answers[idx] ?? "";
  const completedCount = useMemo(
    () => Object.values(answers).filter(Boolean).length,
    [answers],
  );
  const allAnswered = total > 0 && completedCount === total;
  const progress = total > 0 ? ((idx + 1) / total) * 100 : 0;

  const handleSelectAnswer = useCallback((optionKey: string) => {
    setAnswers((prev) => ({ ...prev, [idx]: optionKey }));
  }, [idx]);

  const handleSubmitAnswers = useCallback(() => {
    if (!allAnswered || state.isStreaming) return;
    const submission = buildInteractiveQuizSubmission(questions, answers, {
      intro,
      enabledTools: state.enabledTools,
      knowledgeBases: state.knowledgeBases,
      language: state.language,
    });

    sendMessage(
      submission.content,
      [],
      submission.config,
      undefined,
      undefined,
      {
        requestSnapshotOverride: submission.requestSnapshotOverride,
      },
    );
  }, [
    allAnswered,
    answers,
    intro,
    questions,
    sendMessage,
    state.enabledTools,
    state.isStreaming,
    state.knowledgeBases,
    state.language,
  ]);

  if (!currentQuestion) return null;

  return (
    <div className="overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--card)]">
      <div className="border-b border-[var(--border)] px-4 py-3">
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[var(--muted-foreground)]">
              {t("Interactive quiz")}
            </div>
            <div className="mt-1 text-[13px] text-[var(--muted-foreground)]">
              {t("Choose answers here instead of replying in chat.")}
            </div>
          </div>
          <div className="rounded-full bg-[var(--muted)] px-2.5 py-1 text-[11px] font-semibold text-[var(--muted-foreground)]">
            {completedCount}/{total}
          </div>
        </div>

        {intro ? (
          <div className="mt-3 rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-[13px] text-[var(--muted-foreground)]">
            <MarkdownRenderer content={intro} variant="compact" />
          </div>
        ) : null}

        <div className="mt-3 flex flex-wrap gap-1.5">
          {questions.map((question, questionIndex) => {
            const isCurrent = questionIndex === idx;
            const isAnswered = Boolean(answers[questionIndex]);
            return (
              <button
                key={question.question_id || questionIndex}
                type="button"
                onClick={() => setIdx(questionIndex)}
                className={`flex h-7 min-w-7 items-center justify-center rounded-full px-2 text-[11px] font-semibold transition-all ${
                  isCurrent
                    ? "bg-[var(--primary)] text-white shadow-sm"
                    : isAnswered
                      ? "bg-[var(--primary)]/15 text-[var(--primary)]"
                      : "bg-[var(--muted)] text-[var(--muted-foreground)] hover:bg-[var(--border)]"
                }`}
              >
                {questionIndex + 1}
              </button>
            );
          })}
        </div>
      </div>

      <div className="px-4 py-4">
        <div className="mb-3 flex items-center gap-2">
          <span className="rounded-md bg-[var(--muted)] px-2 py-1 text-[10px] font-semibold uppercase text-[var(--muted-foreground)]">
            Q{idx + 1}
          </span>
          <span className="rounded-md bg-[var(--muted)] px-2 py-1 text-[10px] font-medium text-[var(--muted-foreground)]">
            {t("Multiple choice")}
          </span>
        </div>

        <div className="mb-4 text-[14px] leading-relaxed text-[var(--foreground)]">
          <MarkdownRenderer content={currentQuestion.question} variant="prose" />
        </div>

        <div className="space-y-2">
          {Object.entries(currentQuestion.options ?? {}).map(([key, text]) => {
            const isSelected = selectedAnswer === key;
            return (
              <button
                key={key}
                type="button"
                onClick={() => handleSelectAnswer(key)}
                className={`flex w-full items-start gap-3 rounded-lg border px-3 py-2.5 text-left text-[13px] transition-all ${
                  isSelected
                    ? "border-[var(--primary)] bg-[var(--primary)]/[0.06] text-[var(--foreground)] ring-1 ring-[var(--primary)]/20"
                    : "border-[var(--border)] bg-[var(--background)] text-[var(--foreground)] hover:border-[var(--primary)]/30 hover:bg-[var(--primary)]/[0.02]"
                }`}
              >
                <span
                  className={`mt-[1px] flex h-5 w-5 shrink-0 items-center justify-center rounded-full border text-[11px] font-bold ${
                    isSelected
                      ? "border-[var(--primary)] bg-[var(--primary)] text-white"
                      : "border-[var(--border)] text-[var(--muted-foreground)]"
                  }`}
                >
                  {key}
                </span>
                <span className="leading-relaxed">{text}</span>
              </button>
            );
          })}
        </div>
      </div>

      <div className="border-t border-[var(--border)] px-4 py-3">
        <div className="flex items-center justify-between gap-3">
          <button
            type="button"
            onClick={() => setIdx((value) => Math.max(0, value - 1))}
            disabled={idx === 0}
            className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-[12px] font-medium text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)] disabled:opacity-30"
          >
            <ChevronLeft size={13} />
            {t("Previous")}
          </button>

          <div className="mx-2 h-1 flex-1 overflow-hidden rounded-full bg-[var(--muted)]">
            <div
              className="h-full rounded-full bg-[var(--primary)] transition-all duration-300"
              style={{ width: `${progress}%` }}
            />
          </div>

          <button
            type="button"
            onClick={() => setIdx((value) => Math.min(total - 1, value + 1))}
            disabled={idx === total - 1}
            className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-[12px] font-medium text-[var(--muted-foreground)] transition-colors hover:bg-[var(--muted)] hover:text-[var(--foreground)] disabled:opacity-30"
          >
            {t("Next")}
            <ChevronRight size={13} />
          </button>
        </div>

        <div className="mt-3 flex items-center justify-between gap-3">
          <div className="text-[12px] text-[var(--muted-foreground)]">
            {allAnswered
              ? t("Ready to send your answers back to the tutor.")
              : t("Answer all questions to submit in one line.")}
          </div>
          <button
            type="button"
            onClick={handleSubmitAnswers}
            disabled={!allAnswered || state.isStreaming}
            className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--primary)] px-3 py-1.5 text-[12px] font-medium text-white transition-opacity disabled:opacity-30"
          >
            <Send size={13} />
            {state.isStreaming ? t("Sending...") : t("Send answers")}
          </button>
        </div>
      </div>
    </div>
  );
}
