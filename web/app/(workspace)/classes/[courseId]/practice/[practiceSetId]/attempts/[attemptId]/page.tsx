"use client";

import { useParams } from "next/navigation";
import CourseScopedWorkspace from "@/components/courses/CourseScopedWorkspace";
import PracticeWorkspace from "@/components/practice/PracticeWorkspace";

export default function CourseAttemptPage() {
  const params = useParams<{
    practiceSetId: string;
    attemptId: string;
  }>();
  return (
    <CourseScopedWorkspace>
      <PracticeWorkspace
        initialPracticeSetId={params.practiceSetId}
        initialAttemptId={params.attemptId}
      />
    </CourseScopedWorkspace>
  );
}
