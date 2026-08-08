"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { useCourses } from "@/context/CourseContext";
import { getCourse, type Course } from "@/lib/course-api";

/** Select and authorize a Course before rendering a direct-linked workspace. */
export default function CourseScopedWorkspace({
  children,
}: {
  children: React.ReactNode;
}) {
  const params = useParams<{ courseId: string }>();
  const courseId = params.courseId;
  const { courses, loading: coursesLoading, selectCourse } = useCourses();
  const [course, setCourse] = useState<Course | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void getCourse(courseId)
      .then((loaded) => {
        if (!cancelled) setCourse(loaded);
      })
      .catch((cause: unknown) => {
        if (!cancelled) {
          setCourse(null);
          setError(cause instanceof Error ? cause.message : "Course not found");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [courseId]);

  const listedCourse = course
    ? courses.find((item) => item.id === course.id) ?? null
    : null;

  useEffect(() => {
    if (listedCourse) selectCourse(listedCourse.id);
  }, [listedCourse, selectCourse]);

  if (loading || coursesLoading || (course && !listedCourse)) {
    return (
      <main className="px-6 py-10 sm:px-10">
        <div role="status" className="mx-auto max-w-5xl text-sm text-[var(--muted-foreground)]">
          Loading Course workspace…
        </div>
      </main>
    );
  }

  if (error || !course || !listedCourse) {
    return (
      <main className="px-6 py-10 sm:px-10">
        <div className="mx-auto max-w-5xl">
          <Link href="/classes" className="text-sm text-[var(--muted-foreground)] hover:text-[var(--foreground)]">
            Back to Classes
          </Link>
          <div role="alert" className="mt-8 rounded-2xl border border-red-300/60 bg-red-50/60 px-5 py-4 text-sm text-red-900 dark:border-red-900/60 dark:bg-red-950/20 dark:text-red-200">
            {error || "Course not found or not available to this account."}
          </div>
        </div>
      </main>
    );
  }

  return <>{children}</>;
}
