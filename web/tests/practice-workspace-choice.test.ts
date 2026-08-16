import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import path from "node:path";

const workspaceSource = readFileSync(
  path.join(process.cwd(), "components", "practice", "PracticeWorkspace.tsx"),
  "utf8",
);

test("Practice learner navigation defaults to Take and separates authoring from History", () => {
  assert.match(workspaceSource, /type PracticeTab = "take" \| "create" \| "history"/);
  assert.match(workspaceSource, /useState<PracticeTab>\("take"\)/);
  assert.match(workspaceSource, /\["take", "create", "history"\]/);
  assert.match(workspaceSource, /tab === "take" \? "Take"/);
  assert.match(workspaceSource, /tab === "create" \? "Create"/);
  assert.match(workspaceSource, /: "History"/);
  assert.match(workspaceSource, /activeTab === "create" && !attemptView && revision\?\.state === "draft"/);
  assert.doesNotMatch(workspaceSource, /activeTab === "take"[^\n]*New Practice title/);
  assert.match(workspaceSource, /<h2 className="text-lg font-semibold">Practice history<\/h2>/);
});

test("Practice single-choice uses native grouped radios and immediate option-ID autosave", () => {
  assert.match(workspaceSource, /<fieldset[^>]*disabled=\{interactionReadOnly\}>/);
  assert.match(workspaceSource, /if \(!currentItem \|\| interactionReadOnly\) return;/);
  assert.match(workspaceSource, /<legend[^>]*>Your answer<\/legend>/);
  assert.match(workspaceSource, /type="radio"/);
  assert.match(workspaceSource, /name=\{`answer-\$\{currentItem\.id\}`\}/);
  assert.match(workspaceSource, /onChange=\{\(\) => selectOption\(option\.option_id\)\}/);
  assert.match(workspaceSource, /saveQueue\.enqueue\(currentItem\.id, \{ option_id: optionId \}\)/);
  assert.match(workspaceSource, /void flushQueuedItem\(currentItem\.id\)/);
});

test("Practice short answers debounce and every learner transition flushes pending saves", () => {
  assert.match(workspaceSource, /changeShortAnswer\(currentItem\.id, event\.target\.value\)/);
  assert.match(workspaceSource, /setTimeout\(\(\) => \{[\s\S]*?\}, 500\)/);
  assert.match(workspaceSource, /if \(value === durable && !pending\)/);
  assert.match(workspaceSource, /if \(!value\.trim\(\) && !durable\.trim\(\) && !pending\)/);
  assert.match(workspaceSource, /if \(await flushItem\(currentItem\.id\)\) setCurrentIndex\(index\)/);
  assert.match(
    workspaceSource,
    /Promise\.all\(view\.items\.map\(\(item\) => flushItem\(item\.id\)\)\)/,
  );
  assert.match(workspaceSource, /onClick=\{\(\) => void navigateTo\(/);
  assert.match(workspaceSource, /onClick=\{\(\) => void submitAttempt\(\)\}/);
});

test("Practice exposes per-item save state without setting global busy for autosave", () => {
  assert.match(workspaceSource, /role=\{currentSaveState\.state === "error" \? "alert" : "status"\}/);
  assert.match(workspaceSource, /"Saving…"/);
  assert.match(workspaceSource, /"Saved"/);
  assert.match(workspaceSource, /`Save failed: \$\{currentSaveState\.message\}`/);
  const saveStart = workspaceSource.indexOf("const saveAnswer = useCallback");
  const saveEnd = workspaceSource.indexOf("const transitionAttempt = useCallback", saveStart);
  assert.ok(saveStart >= 0 && saveEnd > saveStart);
  assert.doesNotMatch(workspaceSource.slice(saveStart, saveEnd), /setBusy\(/);
});

test("Practice results label the learner answer, correct answer, explanation, and citations", () => {
  assert.match(workspaceSource, />Your answer:<\/span>/);
  assert.match(workspaceSource, />Correct answer:<\/span>/);
  assert.match(workspaceSource, />Why:<\/span>/);
  assert.match(workspaceSource, />Citations:<\/p>/);
});

test("Practice deep links resolve the exact attempt and never select it from the first history page", () => {
  assert.match(
    workspaceSource,
    /getPracticeAttempt\(practiceSet\.course_id, practiceSet\.id, requestedAttemptId\)/,
  );
  assert.match(workspaceSource, /requestedView\?\.attempt\.practice_set_revision_id/);
  assert.doesNotMatch(
    workspaceSource,
    /history\.find\(\(attempt\) => attempt\.id === requestedAttemptId\)/,
  );
});
