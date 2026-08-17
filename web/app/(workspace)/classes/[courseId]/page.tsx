import CourseOverview from "@/components/courses/CourseOverview";
import CourseScopedWorkspace from "@/components/courses/CourseScopedWorkspace";

export default function CoursePage() {
  return (
    <CourseScopedWorkspace>
      <CourseOverview />
    </CourseScopedWorkspace>
  );
}
