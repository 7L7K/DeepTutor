import test from "node:test";
import assert from "node:assert/strict";
import {
  getCompletionNudge,
  getCompletionTitle,
  getDeckSourceBadges,
  getSourceTrustBadge,
} from "../lib/flashcards-display";

test("source trust badges distinguish grounded decks from topic starters", () => {
  assert.deepEqual(getSourceTrustBadge("knowledge"), {
    label: "Grounded source",
    detail: "Built from selected Knowledge excerpts",
    tone: "grounded",
  });
  assert.deepEqual(getSourceTrustBadge("topic"), {
    label: "Topic starter",
    detail: "AI-generated from the topic prompt",
    tone: "starter",
  });
});

test("deck source badges include the trust label and selected knowledge bases", () => {
  assert.deepEqual(
    getDeckSourceBadges({
      sourceType: "knowledge",
      sourceSummary: "Grounded in kb-one",
      sourceKbNames: ["kb-one"],
    }),
    ["Grounded source: Grounded in kb-one", "KB: kb-one"],
  );
});

test("missed-only completion has distinct coach-first framing", () => {
  assert.equal(getCompletionTitle("missed_only"), "Missed review complete");
  assert.match(getCompletionNudge("missed_only", 0), /cleared the missed-card pass/);
  assert.match(getCompletionNudge("full_deck", 2), /Review missed only/);
});
