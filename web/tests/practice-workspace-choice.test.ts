import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import path from "node:path";

const workspaceSource = readFileSync(
  path.join(process.cwd(), "components", "practice", "PracticeWorkspace.tsx"),
  "utf8",
);

test("Practice learner navigation keeps Take and History and makes creation a Take action", () => {
  assert.match(workspaceSource, /type PracticeTab = "take" \| "history"/);
  assert.match(workspaceSource, /useState<PracticeTab>\("take"\)/);
  assert.match(workspaceSource, /\["take", "history"\]/);
  assert.match(workspaceSource, /tab === "take" \? "Practice" : "History"/);
  assert.match(workspaceSource, /<h2 id="new-practice-title" className="text-2xl font-semibold sm:text-3xl">What do you want to practice\?<\/h2>/);
  assert.match(workspaceSource, /aria-label="Practice topic"/);
  assert.match(workspaceSource, /<summary className="flex cursor-pointer flex-wrap items-center gap-3 py-3 text-sm font-medium">/);
  assert.match(workspaceSource, /<span>Customize quiz<\/span>/);
  assert.match(workspaceSource, /rounded-full border border-\[var\(--border\)\] px-2 py-1/);
  assert.doesNotMatch(workspaceSource, /New practice<\/p>/);
  assert.match(workspaceSource, /Enter a topic, chapter, or lesson\./);
  assert.match(workspaceSource, /Quiz me<\/button>/);
  assert.match(workspaceSource, /<h1 className="text-2xl font-semibold">Practice<\/h1>/);
  assert.doesNotMatch(workspaceSource, /Create, take, and review private quizzes grounded in this Course/);
  assert.doesNotMatch(workspaceSource, /activeTab === "create"/);
  assert.doesNotMatch(workspaceSource, /aria-label="New Practice title"/);
  assert.doesNotMatch(workspaceSource, /Choose a ready quiz, or use New practice above/);
  assert.doesNotMatch(workspaceSource, /Your quizzes will appear here\./);
  assert.match(workspaceSource, /Recent quizzes/);
  assert.match(workspaceSource, /<h2 className="text-lg font-semibold">Practice history<\/h2>/);
  assert.match(workspaceSource, /Every attempt stays here/);
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

test("Course-scoped Practice prefers the authorized shell Course", () => {
  assert.match(
    workspaceSource,
    /const \{ activeCourse: sharedActiveCourse, refresh: refreshCourses \} = useCourses\(\)/,
  );
  assert.match(
    workspaceSource,
    /const activeCourse = courseShell\?\.course \?\? sharedActiveCourse/,
  );
});

test("provider-off Practice can create and select a first manual draft", () => {
  const creationStart = workspaceSource.indexOf(
    "const createManualPractice = useCallback",
  );
  const creationEnd = workspaceSource.indexOf(
    "const addQuestion = useCallback",
    creationStart,
  );
  assert.ok(creationStart >= 0 && creationEnd > creationStart);
  const creation = workspaceSource.slice(creationStart, creationEnd);
  assert.ok(creation.indexOf("createPracticeSet(") < creation.indexOf("createPracticeRevision("));
  assert.ok(creation.indexOf("createPracticeRevision(") < creation.indexOf("getPracticeSet("));
  assert.match(creation, /setSelectedSetId\(updatedSet\.id\)/);
  assert.match(creation, /setRevision\(createdRevision\)/);
  assert.match(creation, /setQuestions\(\[\]\)/);
  assert.match(workspaceSource, /aria-label="Manual Practice title"/);
  assert.match(workspaceSource, /Create manual quiz<\/button>/);
  assert.match(
    workspaceSource,
    /AI quiz creation is unavailable, but you can write the questions and answers yourself\. No provider call will be attempted\./,
  );
});

test("Practice reload resumes a durable draft and stranded sets can start one", () => {
  assert.match(
    workspaceSource,
    /loadSetDetail\(\s*detailScope,\s*usable,\s*practiceSetRevisionId\(usable\)/,
  );
  assert.match(
    workspaceSource,
    /loadSetDetail\(scope, practiceSet, practiceSetRevisionId\(practiceSet\)\)/,
  );
  assert.match(workspaceSource, /const startManualDraft = useCallback/);
  assert.match(workspaceSource, /Starting it is safe to retry\./);
  assert.match(workspaceSource, /Start draft<\/button>/);
});

test("ready selections and draft detail failures cannot start a blank draft", () => {
  const startDraftStart = workspaceSource.indexOf(
    "const startManualDraft = useCallback",
  );
  const startDraftEnd = workspaceSource.indexOf(
    "const addQuestion = useCallback",
    startDraftStart,
  );
  assert.ok(startDraftStart >= 0 && startDraftEnd > startDraftStart);
  assert.match(
    workspaceSource.slice(startDraftStart, startDraftEnd),
    /!canStartManualPracticeDraft\(selectedSet, detailState\)/,
  );
  assert.match(
    workspaceSource,
    /detailState === "loading"[\s\S]*Opening this quiz…/,
  );
  assert.match(
    workspaceSource,
    /detailState === "error"[\s\S]*Retry opening quiz/,
  );
  assert.match(
    workspaceSource,
    /!readOnly && canStartManualPracticeDraft\(selectedSet, detailState\)/,
  );
});
