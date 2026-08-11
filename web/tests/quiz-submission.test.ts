import test from "node:test";
import assert from "node:assert/strict";
import { buildInteractiveQuizSubmission } from "../lib/quiz-submission";

test("buildInteractiveQuizSubmission routes answers through deep_question", () => {
  const submission = buildInteractiveQuizSubmission(
    [
      {
        question_id: "chat_q_1",
        question: "What is empathy?",
        question_type: "choice",
        options: { A: "Pity", B: "Reflection" },
        correct_answer: "",
        explanation: "",
      },
      {
        question_id: "chat_q_2",
        question: "What is rapport?",
        question_type: "choice",
        options: { A: "Distance", B: "Trust" },
        correct_answer: "",
        explanation: "",
      },
    ],
    { 0: "B", 1: "B" },
    {
      intro: "Answer all items.",
      enabledTools: ["rag"],
      knowledgeBases: ["nbcc"],
      language: "en",
    },
  );

  assert.equal(submission.content, "1B 2B");
  assert.equal(submission.requestSnapshotOverride.capability, "deep_question");
  assert.deepEqual(submission.requestSnapshotOverride.enabledTools, ["rag"]);
  assert.deepEqual(submission.config.quiz_submission_context.questions[0].options, {
    A: "Pity",
    B: "Reflection",
  });
  assert.deepEqual(submission.config.quiz_submission_context.answer_map, [
    { index: 1, question_id: "chat_q_1", answer: "B" },
    { index: 2, question_id: "chat_q_2", answer: "B" },
  ]);
});
