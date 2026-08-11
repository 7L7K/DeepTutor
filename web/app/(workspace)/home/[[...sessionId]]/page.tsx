import { Suspense } from "react";
import GeneralStudyWorkspace from "@/components/chat/home/GeneralStudyWorkspace";

export default function ChatPage() {
  return (
    <Suspense fallback={null}>
      <GeneralStudyWorkspace />
    </Suspense>
  );
}
