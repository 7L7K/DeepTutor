import CourseScopedWorkspace from "@/components/courses/CourseScopedWorkspace";
import PracticeWorkspace from "@/components/practice/PracticeWorkspace";

export default function CoursePracticePage() {
  return (
    <CourseScopedWorkspace>
      <PracticeWorkspace />
    </CourseScopedWorkspace>
  );
}
