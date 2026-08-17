import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

const workspaceSource = readFileSync(
  path.join(process.cwd(), "components", "flashcards", "FlashcardsWorkspace.tsx"),
  "utf8",
);
const sessionSource = readFileSync(
  path.join(
    process.cwd(),
    "components",
    "flashcards",
    "study",
    "FlashcardStudySession.tsx",
  ),
  "utf8",
);

test("Course Flashcards defaults to the deck workspace and keeps History secondary", () => {
  assert.match(workspaceSource, /FLASHCARDS_VIEW_PRESENTATION\[item\]\.label/);
  assert.match(workspaceSource, /courseShell && item === "study"[\s\S]*?"Flashcards"/);
  assert.match(workspaceSource, /courseShell && item === "activity"[\s\S]*?"History"/);
  assert.match(workspaceSource, /setPageView\("study"\)/);
  assert.match(
    workspaceSource,
    /pageView === "create" && createMode !== "manual"/,
  );
  assert.match(workspaceSource, /t\("Choose a deck to open it\."\)/);
  assert.match(
    workspaceSource,
    /setPageView\("study"\);\s*void selectDeck\(deck\)/,
  );
  assert.doesNotMatch(
    workspaceSource,
    /if \(courseShell && item === "study"\) \{[\s\S]*?setPageView\("create"\)/,
  );
  assert.match(
    workspaceSource,
    /!studySessionActive && !courseShell \? \([\s\S]*?aria-label=\{t\("Flashcards views"\)\}/,
  );
  assert.match(workspaceSource, /filter\(\(item\) => !courseShell \|\| item !== "create"\)/);
  assert.match(workspaceSource, /t\("Flashcard decks"\)/);
  assert.match(workspaceSource, /t\("Ready to study"\)/);
  assert.match(workspaceSource, /t\("Start studying"\)/);
  assert.match(workspaceSource, /t\("New deck"\)/);
  assert.match(
    workspaceSource,
    /t\("Tell me what you want these flashcards to be about\."\)/,
  );
  assert.match(workspaceSource, /t\("What do you want these flashcards to be about\?"\)/);
  assert.match(workspaceSource, /t\("Create a flashcard deck"\)/);
  assert.match(workspaceSource, /t\("Generate \{\{count\}\} flashcards"/);
  assert.match(workspaceSource, /t\("Study flashcard: \{\{prompt\}\}"/);
  assert.match(workspaceSource, /beginReview\(card\.id\)/);
  assert.match(workspaceSource, /t\("Open"\)/);
  assert.match(workspaceSource, /t\("Add card"\)/);
  assert.match(workspaceSource, /aria-haspopup="dialog"/);
  assert.match(workspaceSource, /id="add-card-dialog"[\s\S]*?role="dialog"/);
  assert.match(workspaceSource, /aria-modal="true"/);
  assert.match(workspaceSource, /t\("Cancel"\)/);
  assert.match(workspaceSource, /t\("Save card"\)/);
  assert.match(workspaceSource, /id="edit-card-dialog"[\s\S]*?role="dialog"/);
  assert.match(workspaceSource, /aria-controls="edit-card-dialog"/);
  assert.match(workspaceSource, /t\("Save changes"\)/);
  assert.match(workspaceSource, /t\("Create flashcards"\)/);
  assert.match(workspaceSource, /t\("Card count"\)/);
  assert.match(workspaceSource, /t\("Create manually"\)/);
  assert.match(workspaceSource, /t\("More options"\)/);
  assert.match(workspaceSource, /t\("Based on \{\{count\}\} Course materials"/);
  assert.match(workspaceSource, /t\("Change"\)/);
  assert.match(
    workspaceSource,
    /t\("No flashcard study history is available yet\."\)/,
  );
  assert.match(workspaceSource, /t\("Back to flashcards"\)/);
  assert.match(workspaceSource, /onClick=\{\(\) => setPageView\("study"\)\}/);
  assert.match(workspaceSource, /dismissGenerationActivity/);
  assert.match(workspaceSource, /t\("Delete"\)/);
  assert.doesNotMatch(workspaceSource, /t\("Review decks"\)/);
  assert.doesNotMatch(workspaceSource, /t\("Create review cards"\)/);
  assert.match(workspaceSource, /reviewMode=\{Boolean\(courseShell\)\}/);
});

test("Flashcard completion copy is presentation-only and keeps study compatibility", () => {
  assert.match(sessionSource, /reviewMode\?: boolean/);
  assert.match(sessionSource, /reviewMode \? "Flashcards complete" : "Study complete"/);
  assert.match(sessionSource, /t\("Practice missed cards"\)/);
  assert.match(sessionSource, /t\("Study this deck again"\)/);
  assert.match(sessionSource, /t\("Start a new deck"\)/);
  assert.match(sessionSource, /onRate\(studySessionActions\.knewIt\)/);
  assert.match(sessionSource, /onRate\(studySessionActions\.almost\)/);
  assert.match(sessionSource, /onRate\(studySessionActions\.practiceAgain\)/);
  assert.match(sessionSource, /t\("Edit card"\)/);
  assert.match(sessionSource, /t\("Reveal answer"\)/);
  assert.match(sessionSource, /aria-label=\{t\("Reveal answer"\)\}/);
  assert.match(sessionSource, /min-h-\[calc\(100dvh-10rem\)\] w-full/);
  assert.match(sessionSource, /min-h-\[clamp\(20rem,58vh,34rem\)\] w-full/);
  assert.match(sessionSource, /!answerVisible \? navigation/);
  assert.match(sessionSource, /\{navigation\}/);
  assert.match(sessionSource, /flex flex-wrap items-center gap-2/);
  assert.doesNotMatch(sessionSource, /inset-x-0 top-0 h-1 bg-\[var\(--primary\)\]/);
  assert.doesNotMatch(sessionSource, /border-\[var\(--primary\)\]\/40/);
  assert.doesNotMatch(sessionSource, /t\("Show answer"\)/);
});
