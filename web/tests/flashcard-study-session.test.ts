import assert from "node:assert/strict";
import test from "node:test";
import {
  cardsLeftLabel,
  completedCardsLabel,
  nextIncompleteStudyIndex,
  studySessionActions,
} from "../components/flashcards/study/study-session-presentation";

test("study-session actions preserve the existing scheduler ratings behind learner copy", () => {
  assert.deepEqual(studySessionActions, {
    gotIt: "good",
    studyAgain: "again",
  });
});

test("numbered navigation advances to every unfinished card after arbitrary jumps", () => {
  assert.equal(nextIncompleteStudyIndex(4, new Set([2]), 2), 3);
  assert.equal(nextIncompleteStudyIndex(4, new Set([2, 3]), 3), 0);
  assert.equal(nextIncompleteStudyIndex(4, new Set([0, 1, 2, 3]), 3), 4);
});

test("study-session progress is count-only and does not reveal scheduling dates", () => {
  assert.equal(cardsLeftLabel(1), "1 card left");
  assert.equal(cardsLeftLabel(3), "3 cards left");
  assert.equal(cardsLeftLabel(-4), "0 cards left");
});

test("study completion reports reviewed cards without next-review timing", () => {
  assert.equal(completedCardsLabel(1), "You reviewed 1 card.");
  assert.equal(completedCardsLabel(4), "You reviewed 4 cards.");
  assert.equal(completedCardsLabel(-4), "You reviewed 0 cards.");
});
