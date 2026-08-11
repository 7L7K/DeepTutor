import CourseMaterials from "@/components/courses/CourseMaterials";
import CourseScopedWorkspace from "@/components/courses/CourseScopedWorkspace";

export default function CourseMaterialsPage() {
  return (
    <CourseScopedWorkspace>
      <CourseMaterials />
    </CourseScopedWorkspace>
  );
}
