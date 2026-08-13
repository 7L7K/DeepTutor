import { redirect } from "next/navigation";

export default async function CourseChatCompatibilityPage({
  params,
}: {
  params: Promise<{ courseId: string }>;
}) {
  const { courseId } = await params;
  redirect(`/classes/${encodeURIComponent(courseId)}`);
}
