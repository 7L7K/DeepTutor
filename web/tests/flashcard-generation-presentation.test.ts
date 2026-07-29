import assert from "node:assert/strict";
import test from "node:test";

import { flashcardGenerationUnavailableCopy } from "../lib/flashcard-generation-presentation";

test("Flashcard provider-unavailable copy keeps manual fallback visible", () => {
  assert.equal(
    flashcardGenerationUnavailableCopy(
      "Grounded generation is not enabled on this server",
    ),
    "Grounded generation is not enabled on this server. Manual Flashcards remain available.",
  );
  assert.equal(
    flashcardGenerationUnavailableCopy(null),
    "Grounded generation is not enabled on this server. Manual Flashcards remain available.",
  );
});

test("Flashcard provider-unavailable copy does not duplicate fallback", () => {
  assert.equal(
    flashcardGenerationUnavailableCopy(
      "Provider disabled. Manual Flashcards remain available.",
    ),
    "Provider disabled. Manual Flashcards remain available.",
  );
});
