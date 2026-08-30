import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

import {
  practiceAttemptHistoryLabel,
  practiceRevisionAvailability,
  practiceResultsPresentation,
  withdrawInvalidatedPracticeResults,
  type PracticeQuestion,
  type QuizAttemptItem,
  type QuizResult,
} from "../lib/practice-api";

function resultFixture(invalidatedQuestionIds: string[]): QuizResult {
  const questions: PracticeQuestion[] = [
    {
      id: "qst_withdrawn",
      practice_set_revision_id: "prv_1",
      question_type: "short_answer",
      prompt: "Withdrawn question",
      options: [],
      answer_contract: {
        kind: "bounded_short_answer_v1",
        canonical_answer: "secret withdrawn key",
        accepted_normalized_answers: ["secret withdrawn key"],
        normalization_version: "bounded-text-normalization-v1",
      },
      explanation: "secret withdrawn explanation",
      objective_ids: ["obj_1"],
      citations: [{ evidence_quote: "secret withdrawn citation" }],
      content_quality: invalidatedQuestionIds.includes("qst_withdrawn")
        ? "invalidated"
        : "valid",
      ordinal: 1,
      created_at: 1,
    },
    {
      id: "qst_valid",
      practice_set_revision_id: "prv_1",
      question_type: "short_answer",
      prompt: "Valid question",
      options: [],
      answer_contract: {
        kind: "bounded_short_answer_v1",
        canonical_answer: "ordinary key",
        accepted_normalized_answers: ["ordinary key"],
        normalization_version: "bounded-text-normalization-v1",
      },
      explanation: "ordinary explanation",
      objective_ids: ["obj_2"],
      citations: [{ evidence_quote: "ordinary citation" }],
      content_quality: invalidatedQuestionIds.includes("qst_valid")
        ? "invalidated"
        : "valid",
      ordinal: 2,
      created_at: 1,
    },
  ];
  const items: QuizAttemptItem[] = questions.map((question, index) => ({
    id: `ati_${index + 1}`,
    attempt_id: "att_1",
    question_id: question.id,
    display_ordinal: index + 1,
    option_order: null,
    randomized_values: null,
    grading: { is_correct: index === 0 },
    error_type: index === 0 ? null : "application",
    graded_at: 2,
    content_quality: question.content_quality,
  }));
  return {
    attempt: {
      id: "att_1",
      owner_user_id: "usr_1",
      course_id: "crs_1",
      practice_set_id: "prc_1",
      practice_set_revision_id: "prv_1",
      timing_mode: "untimed",
      state: "graded",
      score: { correct: 1, total: 2, fraction: 0.5 },
      revision: 4,
      course_write_epoch: 1,
      practice_set_write_epoch: 2,
      started_at: 1,
      submitted_at: 2,
      graded_at: 2,
      archived_at: null,
      updated_at: 2,
    },
    items,
    answers: items.map((item) => ({
      attempt_item_id: item.id,
      response: { answer: "learner response" },
      revision: 2,
      answered_at: 2,
    })),
    questions,
    effective_score: invalidatedQuestionIds.length === 2
      ? { correct: 0, total: 0, fraction: 0 }
      : { correct: 0, total: 1, fraction: 0 },
    content_quality: { invalidated_question_ids: invalidatedQuestionIds },
  };
}

test("partial invalidation withdraws only the invalid Results disclosure", () => {
  const projected = withdrawInvalidatedPracticeResults(
    resultFixture(["qst_withdrawn"]),
  );
  const withdrawn = projected.questions.find((item) => item.id === "qst_withdrawn")!;
  const ordinary = projected.questions.find((item) => item.id === "qst_valid")!;
  const withdrawnItem = projected.items.find((item) => item.question_id === withdrawn.id)!;
  const ordinaryItem = projected.items.find((item) => item.question_id === ordinary.id)!;

  assert.equal(withdrawn.answer_contract, undefined);
  assert.equal(withdrawn.explanation, undefined);
  assert.equal(withdrawn.citations, undefined);
  assert.equal(withdrawnItem.grading, null);
  assert.equal(withdrawnItem.error_type, null);
  assert.equal(withdrawnItem.content_quality, "invalidated");
  assert.equal(ordinary.answer_contract?.kind, "bounded_short_answer_v1");
  assert.equal(ordinary.explanation, "ordinary explanation");
  assert.deepEqual(ordinary.citations, [{ evidence_quote: "ordinary citation" }]);
  assert.deepEqual(ordinaryItem.grading, { is_correct: false });
  assert.equal(projected.attempt.score, null);
  assert.equal(
    practiceAttemptHistoryLabel(projected.attempt),
    "Adjusted after review",
  );

  const presentation = practiceResultsPresentation(projected.effective_score, 2);
  assert.equal(presentation.headline, "0 correct out of 1");
  assert.equal(presentation.hasMisses, true);
  assert.equal(presentation.guidance, "Review the missed answers and explanations below.");
});

test("full invalidation renders no scored questions and disables misses remediation", () => {
  const projected = withdrawInvalidatedPracticeResults(
    resultFixture(["qst_withdrawn", "qst_valid"]),
  );
  assert.equal(
    JSON.stringify(projected.questions).includes("secret withdrawn key"),
    false,
  );
  assert.equal(projected.questions.every((item) => item.answer_contract === undefined), true);
  assert.equal(projected.items.every((item) => item.grading === null), true);

  const presentation = practiceResultsPresentation(projected.effective_score, 2);
  assert.equal(presentation.headline, "No scored questions remain after review");
  assert.equal(presentation.hasMisses, false);
  assert.equal(
    presentation.guidance,
    "Withdrawn questions are excluded from your score and learning evidence.",
  );
});

test("Practice admission stays available for partial invalidation and closes for full invalidation", () => {
  const partial = practiceRevisionAvailability(
    resultFixture(["qst_withdrawn"]).questions,
  );
  assert.deepEqual(partial, {
    totalQuestionCount: 2,
    validQuestionCount: 1,
    canStart: true,
    status: "Ready for quiz attempts",
  });

  const full = practiceRevisionAvailability(
    resultFixture(["qst_withdrawn", "qst_valid"]).questions,
  );
  assert.deepEqual(full, {
    totalQuestionCount: 2,
    validQuestionCount: 0,
    canStart: false,
    status: "No trustworthy questions remain",
  });
});

test("Results UI keeps ordinary disclosures but gates them behind withdrawn state", () => {
  const source = readFileSync(
    path.join(process.cwd(), "components", "practice", "PracticeWorkspace.tsx"),
    "utf8",
  );
  assert.match(source, />Your answer:<\/span>/);
  assert.match(source, />Correct answer:<\/span>/);
  assert.match(source, />Why:<\/span>/);
  assert.match(source, />Citations:<\/p>/);
  assert.match(source, /Question withdrawn after review/);
  assert.match(source, /The answer key, explanation, and citations were withdrawn\./);
  assert.match(source, /resultsPresentation\.hasMisses \? <button/);
  assert.match(source, /revisionAvailability\.status/);
  assert.match(source, /revisionAvailability\.canStart/);
  assert.match(source, /Reported and withdrawn/);
  assert.match(source, /practiceAttemptHistoryLabel\(attempt\)/);
});

test("initial Practice loading failures show a current-Course retry instead of a permanent spinner", () => {
  const source = readFileSync(
    path.join(process.cwd(), "components", "practice", "PracticeWorkspace.tsx"),
    "utf8",
  );
  assert.match(source, /const \[courseLoadError, setCourseLoadError\]/);
  assert.match(source, /const retryCourseLoad = useCallback/);
  assert.match(source, /invalidate\(identity, courseId\)/);
  assert.match(source, /Could not load \{activeCourse\.title\} Practice/);
  assert.match(source, /Retry loading Practice/);
  assert.match(source, /!courseLoadError && \(courseLoading \|\| !courseReady\)/);
});

test("Practice flushes a debounced answer during route cleanup", () => {
  const source = readFileSync(
    path.join(process.cwd(), "components", "practice", "PracticeWorkspace.tsx"),
    "utf8",
  );
  assert.match(source, /for \(const item of attemptItemsRef\.current\)/);
  assert.match(source, /interactionReadOnlyRef\.current/);
  assert.match(source, /!attemptActiveRef\.current/);
  assert.match(source, /void saveQueue\.flush\(item\.id, saveAnswerRef\.current\)/);
});
