import CourseChatRoute from "@/components/courses/CourseChatRoute";
import CourseScopedWorkspace from "@/components/courses/CourseScopedWorkspace";

export default function CoursePage() {
  return (
    <CourseScopedWorkspace>
      <CourseChatRoute />
    </CourseScopedWorkspace>
  );
}
