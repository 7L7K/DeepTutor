import CourseChatRoute from "@/components/courses/CourseChatRoute";
import CourseScopedWorkspace from "@/components/courses/CourseScopedWorkspace";

export default function CourseChatHomePage() {
  return (
    <CourseScopedWorkspace>
      <CourseChatRoute />
    </CourseScopedWorkspace>
  );
}
