import test from "node:test";
import assert from "node:assert/strict";
import {
  applyPracticeQuizIntent,
  buildFlashcardSeedTopic,
  buildPracticeQuizPreference,
  buildRetryTopic,
  resolvePracticeAttemptSessionId,
} from "../lib/practice-quiz";
import { DEFAULT_QUIZ_CONFIG } from "../lib/quiz-types";

test("resolvePracticeAttemptSessionId prefers the quiz turn session", () => {
  const resolved = resolvePracticeAttemptSessionId({
    turnSessionId: "turn-session",
    selectedSessionId: "selected-session",
    chatSessionId: "chat-session",
  });

  assert.equal(resolved, "turn-session");
});

test("applyPracticeQuizIntent seeds exam simulation settings", () => {
  const next = applyPracticeQuizIntent(
    {
      ...DEFAULT_QUIZ_CONFIG,
      topic: "NCE helping relationships",
      num_questions: 5,
      difficulty: "easy",
      question_type: "written",
    },
    "exam_simulation",
  );

  assert.equal(next.quizConfig.num_questions, 25);
  assert.equal(next.quizConfig.difficulty, "medium");
  assert.equal(next.quizConfig.question_type, "choice");
  assert.equal(next.examMode, true);
  assert.equal(next.timerMinutes, 30);
});

test("buildPracticeQuizPreference keeps custom notes and quality guidance", () => {
  const preference = buildPracticeQuizPreference(
    {
      ...DEFAULT_QUIZ_CONFIG,
      topic: "Ethics",
      preference: "Favor counselor-client boundary scenarios.",
    },
    "ethics_drill",
  );

  assert.match(preference, /User preference: Favor counselor-client boundary scenarios\./);
  assert.match(preference, /Assessment intent: Ethics drill\./);
  assert.match(preference, /Avoid duplicates or near-duplicate questions\./);
});

test("retry and flashcard remediation topics focus on weak domains", () => {
  const structuredResult = {
    submission_state: "graded" as const,
    overall_summary: "Needs review.",
    strongest_areas: ["Helping Relationships"],
    weakest_areas: ["Assessment and Testing", "Group Work"],
    recommended_next_step: "Review weak domains.",
    missing_question_numbers: [],
    score: { correct: 4, total: 8, percent: 50 },
    domain_breakdown: [
      {
        domain: "Helping Relationships",
        correct: 3,
        total: 4,
        percent: 75,
        question_numbers: [1, 2, 3, 4],
      },
      {
        domain: "Assessment and Testing",
        correct: 1,
        total: 4,
        percent: 25,
        question_numbers: [5, 6, 7, 8],
      },
    ],
    question_results: [],
  };

  assert.match(
    buildRetryTopic("NCE review", structuredResult),
    /focus on Assessment and Testing, Helping Relationships/,
  );
  assert.match(
    buildFlashcardSeedTopic("NCE review", structuredResult),
    /flashcards focused on Assessment and Testing and Helping Relationships/,
  );
});
