import CourseChatRoute from "@/components/courses/CourseChatRoute";
import CourseScopedWorkspace from "@/components/courses/CourseScopedWorkspace";

export default function CourseChatPage() {
  return (
    <CourseScopedWorkspace>
      <CourseChatRoute />
    </CourseScopedWorkspace>
  );
}
