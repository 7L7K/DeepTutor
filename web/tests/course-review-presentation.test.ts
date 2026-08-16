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

test("Course Review keeps the existing engine while presenting Review/Create/History", () => {
  assert.match(workspaceSource, /FLASHCARDS_VIEW_PRESENTATION\[item\]\.label/);
  assert.match(workspaceSource, /courseShell && item === "study"[\s\S]*?"Review"/);
  assert.match(workspaceSource, /courseShell && item === "activity"[\s\S]*?"History"/);
  assert.match(workspaceSource, /t\("Your review"\)/);
  assert.match(workspaceSource, /t\("Ready to review"\)/);
  assert.match(workspaceSource, /t\("Start review"\)/);
  assert.match(workspaceSource, /t\("Create review material"\)/);
  assert.match(workspaceSource, /t\("Review history"\)/);
  assert.match(workspaceSource, /reviewMode=\{Boolean\(courseShell\)\}/);
});

test("Review completion copy is presentation-only and keeps study compatibility", () => {
  assert.match(sessionSource, /reviewMode\?: boolean/);
  assert.match(sessionSource, /reviewMode \? "Review complete" : "Study complete"/);
  assert.match(sessionSource, /reviewMode \? "Keep reviewing" : "Keep studying"/);
  assert.match(sessionSource, /onRate\(studySessionActions\.gotIt\)/);
  assert.match(sessionSource, /onRate\(studySessionActions\.studyAgain\)/);
});
