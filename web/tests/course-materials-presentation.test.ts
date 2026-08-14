import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

const source = readFileSync(
  path.join(process.cwd(), "components", "courses", "CourseMaterials.tsx"),
  "utf8",
);

test("Course Materials presents source lifecycle as learner-readable sections", () => {
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
});

test("Failed material replacement uses the existing supersession contract", () => {
  assert.match(source, /const \[replacementSourceId, setReplacementSourceId\]/);
  assert.match(source, /attachCourseSource\(course\.id, file, supersedesSourceId\)/);
  assert.match(source, /Replace material/);
  assert.match(source, /openFilePicker\(source\.id\)/);
  assert.doesNotMatch(source, /Delete material/);
});
