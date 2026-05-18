import { Suspense } from "react";

import FlashcardsWorkspace from "@/components/practice/FlashcardsWorkspace";

export default function PracticeFlashcardsPage() {
  return (
    <Suspense fallback={null}>
      <FlashcardsWorkspace />
    </Suspense>
  );
}
