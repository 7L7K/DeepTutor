import { Suspense } from "react";
import BlueWayLaunch from "@/components/launch/BlueWayLaunch";

export default function BlueWayLaunchPage() {
  return (
    <Suspense fallback={<main className="flex min-h-screen items-center justify-center text-sm text-[var(--muted-foreground)]">Opening your Course…</main>}>
      <BlueWayLaunch />
    </Suspense>
  );
}
