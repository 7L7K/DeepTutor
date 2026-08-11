import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

const source = readFileSync(
  path.join(process.cwd(), "components", "courses", "ClassesHome.tsx"),
  "utf8",
);

test("Classes presents a focused class entry point", () => {
  assert.match(source, /<h1[^>]*>\s*Classes\s*<\/h1>/);
  assert.match(source, /<Plus size=\{15\} \/>\s*Add class/);
  assert.match(source, /role="dialog"/);
  assert.match(source, /aria-modal="true"/);
  assert.match(source, /id="new-class-title"/);
  assert.match(source, /createCourse\(title\)/);
  assert.doesNotMatch(source, /Create Course/);
});

test("Class cards keep authoritative metadata and one clear destination", () => {
  assert.match(source, /Academic class/);
  assert.match(source, /learnerCourseTermLabel\(course\.term\)/);
  assert.match(source, /course\.state === "active" \? "Active" : "Archived"/);
  assert.match(source, /Open class/);
  assert.doesNotMatch(source, /Continue/);
  assert.doesNotMatch(source, /progress|recommend/i);
});

test("The empty state offers class creation and General Study", () => {
  assert.match(source, /No classes yet/);
  assert.match(
    source,
    /Add your first class to organize materials, Practice, Review,\s*and\s*Course Chat in one place\./,
  );
  assert.match(source, /Study without a class/);
  assert.match(source, /href="\/space\/learning"/);
  assert.match(source, /Open General Study/);
});

test("The lower General Study prompt only appears when classes exist", () => {
  assert.match(
    source,
    /\{academicCourses\.length \? \(\s*<p className="mt-10 text-sm text-\[var\(--muted-foreground\)\]">\s*Need general learning instead\?/,
  );
});
