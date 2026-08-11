import CourseOverview from "@/components/courses/CourseOverview";
import CourseScopedWorkspace from "@/components/courses/CourseScopedWorkspace";

export default function CourseOverviewPage() {
  return (
    <CourseScopedWorkspace>
      <CourseOverview />
    </CourseScopedWorkspace>
  );
}
