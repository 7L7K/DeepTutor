import type { Course } from "./course-api";

export type ClassSort = "name" | "newest";

/** Labels and dates come from BlueWay; the opaque ID is only an identity key. */
export function semesterOptions(courses: Course[]) {
  const semesters = new Map<string, { id: string; label: string; startsOn: string | null; selected: boolean; archived: boolean }>();
  for (const course of courses) {
    const id = course.term ?? "";
    if (!semesters.has(id)) semesters.set(id, {
      id,
      label: id ? course.term_label || "Semester details unavailable" : "No semester assigned",
      startsOn: course.term_starts_on ?? null,
      selected: course.term_selected === true,
      archived: course.term_archived === true,
    });
  }
  const options = [...semesters.values()].sort((a, b) =>
    Number(b.selected) - Number(a.selected)
    || Number(!a.id) - Number(!b.id)
    || Number(a.archived) - Number(b.archived)
    || (b.startsOn ?? "").localeCompare(a.startsOn ?? "")
    || a.label.localeCompare(b.label, "en", { numeric: true })
    || a.id.localeCompare(b.id));
  const totals = new Map<string, number>();
  const seen = new Map<string, number>();
  for (const option of options) totals.set(option.label, (totals.get(option.label) ?? 0) + 1);
  return options.map((option) => {
    const index = (seen.get(option.label) ?? 0) + 1;
    seen.set(option.label, index);
    const label = totals.get(option.label)! > 1 ? `${option.label} (${index})` : option.label;
    return { ...option, label: option.archived ? `${label} · Archived semester` : label };
  });
}

export function defaultSemester(options: ReturnType<typeof semesterOptions>): string | null {
  const selected = options.filter((option) => option.selected && !option.archived);
  return selected.length === 1 ? selected[0].id : null;
}

export function groupClasses(courses: Course[], semester: string | null, sort: ClassSort, options = semesterOptions(courses)) {
  return options.map((option) => ({
    ...option,
    courses: courses.filter((course) => (course.term ?? "") === option.id && (semester === null || option.id === semester))
      .sort((a, b) => (sort === "newest" ? b.created_at - a.created_at : 0) || a.title.localeCompare(b.title, "en", { numeric: true }) || a.id.localeCompare(b.id)),
  })).filter((group) => group.courses.length > 0);
}
