import test from "node:test";
import assert from "node:assert/strict";
import { extractQuizQuestionsFromContent } from "../lib/quiz-types";

test("extractQuizQuestionsFromContent parses wrapped multiline options", () => {
  const parsed = extractQuizQuestionsFromContent(`Practice quiz

1. First question stem
A) Option one
continued detail
B) Option two

2. Second question stem
A) Alpha
B) Beta`);

  assert.ok(parsed);
  assert.equal(parsed.questions.length, 2);
  assert.equal(parsed.questions[0].options?.A, "Option one continued detail");
});

test("extractQuizQuestionsFromContent accepts colon option labels", () => {
  const parsed = extractQuizQuestionsFromContent(`1. Choose one
A: First
B: Second

2. Choose two
A: Left
B: Right`);

  assert.ok(parsed);
  assert.equal(parsed.questions[0].options?.A, "First");
  assert.equal(parsed.questions[1].options?.B, "Right");
});

test("extractQuizQuestionsFromContent rejects malformed quiz blocks", () => {
  const parsed = extractQuizQuestionsFromContent(`1. Only one question
A) one
B) two`);
  assert.equal(parsed, null);
});
