import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import {
  isCurrentMaterialRefresh,
  reduceMaterialErrors,
  runSerializedMaterialPollCycle,
  type MaterialErrorState,
} from "../components/courses/CourseMaterials";

const source = readFileSync(
  path.join(process.cwd(), "components", "courses", "CourseMaterials.tsx"),
  "utf8",
);
const courseBarSource = readFileSync(
  path.join(process.cwd(), "components", "courses", "CourseBar.tsx"),
  "utf8",
);

test("Course Materials presents source lifecycle with owner-managed uploads", () => {
  assert.match(source, /function materialStateLabel/);
  assert.match(source, /return "Preparing"/);
  assert.match(source, /return "Ready"/);
  assert.match(source, /return "Could not process"/);
  assert.match(source, /return "Archived"/);
  assert.match(source, /<FilePlus2 size=\{15\} \/> Add material/);
  assert.match(source, /<h2 className="mb-3 text-lg font-semibold">Ready<\/h2>/);
  assert.match(source, /<h2 className="mb-3 text-lg font-semibold">Preparing<\/h2>/);
  assert.match(source, /<h2 className="mb-3 text-lg font-semibold">Needs attention<\/h2>/);
  assert.match(source, /Archived \(\{archivedSources\.length\}\)/);
  assert.match(source, /Available to Course Chat and Practice/);
  assert.match(source, /const canManageSources = useAuthStatus\(\)\.canUploadCourseSources/);
  assert.match(source, /Ask your TEEECHR owner to enable Course uploads for this account/);
  assert.match(source, /canManageSources && source\.state !== "archived"/);
});

test("Failed material replacement uses the existing supersession contract", () => {
  assert.match(source, /const \[replacementSourceId, setReplacementSourceId\]/);
  assert.match(source, /attachCourseSource\(course\.id, file, supersedesSourceId\)/);
  assert.match(source, /Replace material/);
  assert.match(source, /openFilePicker\(source\.id\)/);
  assert.match(source, /canManageSources && source\.state === "failed"/);
  assert.doesNotMatch(source, /Delete material/);
});

test("legacy CourseBar hides add and replacement controls from learners", () => {
  assert.match(courseBarSource, /const canManageSources = useAuthStatus\(\)\.canUploadCourseSources/);
  assert.match(courseBarSource, /\{canManageSources \? \(/);
  assert.match(courseBarSource, /canManageSources && source\.state === "failed"/);
  assert.match(courseBarSource, /canManageSources && source\.state !== "archived"/);
  assert.match(courseBarSource, /No Course sources are assigned yet/);
});

test("Processing material polls silently and serially without replacing loaded controls", () => {
  assert.match(source, /\{ silent = false \}: \{ silent\?: boolean \} = \{\}/);
  assert.match(source, /if \(!silent\) \{/);
  assert.match(source, /refresh\(\{ silent: true \}\)/);
  assert.match(source, /window\.setTimeout/);
  assert.doesNotMatch(source, /window\.setInterval/);
});

test("Background refresh events preserve an actionable material failure", () => {
  const initial: MaterialErrorState = { load: null, action: null };
  const afterActionFailure = reduceMaterialErrors(initial, {
    type: "action-failed",
    message: "Could not replace the failed material",
  });
  const afterPollFailure = reduceMaterialErrors(afterActionFailure, {
    type: "load-failed",
    message: "Could not refresh materials",
  });
  const afterPollRecovery = reduceMaterialErrors(afterPollFailure, {
    type: "load-succeeded",
  });

  assert.deepEqual(afterPollFailure, {
    load: "Could not refresh materials",
    action: "Could not replace the failed material",
  });
  assert.deepEqual(afterPollRecovery, {
    load: null,
    action: "Could not replace the failed material",
  });
});

test("Only the newest material refresh response may update the view", () => {
  const firstRequestEpoch = 1;
  const secondRequestEpoch = 2;

  assert.equal(isCurrentMaterialRefresh(secondRequestEpoch, secondRequestEpoch), true);
  assert.equal(isCurrentMaterialRefresh(firstRequestEpoch, secondRequestEpoch), false);
});

test("a material load failure is retryable and never presented as an empty Course", () => {
  assert.match(source, /Retry loading materials/);
  assert.match(source, /errors\.load \? null : sources\.length/);
  assert.match(source, /Could not load Course materials/);
});

test("A poll slower than the nominal interval applies before the next poll starts", async () => {
  const nominalIntervalMs = 5;
  const slowRequestMs = nominalIntervalMs + 10;
  const events: string[] = [];
  let requestCount = 0;
  let appliedCount = 0;
  let activeRequests = 0;
  let maximumActiveRequests = 0;
  let rearmCount = 0;

  const refresh = async () => {
    const requestNumber = ++requestCount;
    activeRequests += 1;
    maximumActiveRequests = Math.max(maximumActiveRequests, activeRequests);
    events.push(`request-${requestNumber}-started`);
    await new Promise((resolve) => setTimeout(resolve, slowRequestMs));
    appliedCount += 1;
    events.push(`request-${requestNumber}-applied`);
    activeRequests -= 1;
  };
  const runCycle = () => runSerializedMaterialPollCycle(
    refresh,
    () => {
      rearmCount += 1;
      events.push(`rearm-${rearmCount}`);
    },
    () => true,
  );

  const startedAt = Date.now();
  await runCycle();

  assert.equal(Date.now() - startedAt > nominalIntervalMs, true);
  assert.equal(appliedCount, 1);
  assert.equal(maximumActiveRequests, 1);
  assert.equal(rearmCount, 1);
  assert.deepEqual(events, ["request-1-started", "request-1-applied", "rearm-1"]);

  await runCycle();

  assert.equal(requestCount, 2);
  assert.equal(appliedCount, 2);
  assert.equal(maximumActiveRequests, 1);
  assert.equal(rearmCount, 2);
  assert.deepEqual(events, [
    "request-1-started",
    "request-1-applied",
    "rearm-1",
    "request-2-started",
    "request-2-applied",
    "rearm-2",
  ]);
});
