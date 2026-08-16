import CourseChatRoute from "@/components/courses/CourseChatRoute";
import CourseScopedWorkspace from "@/components/courses/CourseScopedWorkspace";

export default function CourseChatSessionPage() {
  return (
    <CourseScopedWorkspace>
      <CourseChatRoute />
    </CourseScopedWorkspace>
  );
}
