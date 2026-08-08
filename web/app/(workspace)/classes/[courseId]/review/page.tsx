import CourseScopedWorkspace from "@/components/courses/CourseScopedWorkspace";
import FlashcardsWorkspace from "@/components/flashcards/FlashcardsWorkspace";

export default function CourseReviewPage() {
  return (
    <CourseScopedWorkspace>
      <FlashcardsWorkspace />
    </CourseScopedWorkspace>
  );
}
