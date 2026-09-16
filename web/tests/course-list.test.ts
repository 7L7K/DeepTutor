import assert from "node:assert/strict";
import test from "node:test";
import { defaultSemester, groupClasses, semesterOptions } from "../lib/course-list";
import type { Course } from "../lib/course-api";
const course = (id: string, term: string | null, title = id, created_at = 1) => ({ id, term, title, created_at, workspace_kind: "academic_course", state: "active" } as Course);

test("uses saved semester labels and selected status without decoding opaque IDs", () => {
  const courses = [
    { ...course("b", "term-fall-1yzl4x3"), term_label: "First semester", term_selected: true, term_starts_on: "2026-09-10" },
    { ...course("a", "term-fall-0abcdef"), term_label: "First semester", term_selected: false },
    course("old", null),
  ];
  const options = semesterOptions(courses);
  assert.equal(defaultSemester(options), "term-fall-1yzl4x3");
  assert.equal(options[0].label, "First semester (1)");
  assert.equal(options[1].label, "First semester (2)");
  assert.equal(options.at(-1)?.label, "No semester assigned");
  assert.deepEqual(groupClasses(courses, "term-fall-1yzl4x3", "name").flatMap((g) => g.courses.map((c) => c.id)), ["b"]);
  assert.equal(semesterOptions([course("unknown", "term-fall-1234567")])[0].label, "Semester details unavailable");
});

test("orders terms by saved dates and keeps archived semesters accessible", () => {
  const courses = [
    { ...course("old", "one"), term_label: "Summer 2026", term_archived: true },
    { ...course("future", "two"), term_label: "Winter", term_starts_on: "2027-01-10" },
    { ...course("current", "three"), term_label: "Fall", term_starts_on: "2026-09-10", term_selected: true },
  ];
  assert.deepEqual(semesterOptions(courses).map(o => o.id), ["three", "two", "one"]);
  assert.equal(groupClasses(courses, null, "name").length, 3);
  assert.match(semesterOptions(courses)[2].label, /Archived semester/);
  assert.equal(defaultSemester(semesterOptions([course("unknown", "one")])), null);
  assert.equal(defaultSemester(semesterOptions(courses.map(c => ({...c, term_selected: true})))), null);
});

test("sort stays inside selected semester without mutating provider records", () => {
  const courses = [course("z", "fall-2026", "Zoology", 3), course("a", "fall-2026", "Algebra", 1), course("b", "summer-2026", "Biology", 9)];
  assert.deepEqual(groupClasses(courses, "fall-2026", "name")[0].courses.map((c) => c.id), ["a", "z"]);
  assert.deepEqual(groupClasses(courses, "fall-2026", "newest")[0].courses.map((c) => c.id), ["z", "a"]);
  assert.deepEqual(courses.map((c) => c.id), ["z", "a", "b"]);
  assert.equal(groupClasses(courses, "missing", "name").length, 0);
});

test("unassigned and same-label terms stay distinct across status groups", () => {
  const courses = [course("a", "term-fall-0aaaaaa"), course("b", "term-fall-0bbbbbb"), course("u", null)];
  const options = semesterOptions(courses);
  assert.equal(groupClasses(courses, "", "name")[0].courses[0].id, "u");
  assert.equal(groupClasses([courses[1]], null, "name", options)[0].label, options.find((o) => o.id === courses[1].term)?.label);
});
