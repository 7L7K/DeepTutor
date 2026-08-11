"use client";

import CourseShell from "@/components/courses/CourseShell";

/** Select and authorize a Course before rendering a direct-linked workspace. */
export default function CourseScopedWorkspace({
  children,
}: {
  children: React.ReactNode;
}) {
  return <CourseShell>{children}</CourseShell>;
}
