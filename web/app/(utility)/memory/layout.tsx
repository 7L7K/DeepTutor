// Bare shell — each memory page owns its own padding + scroll behavior.
// Hub uses `overflow-y-auto` with a max-width container; the L2/L3
// workbench pages use a full-height flex column with internal scrolling
// per pane (preview / LLM workspace) so the outer page never grows.
import { AdminOnlyGate } from "@/components/auth/AdminOnlyGate";

export default function MemoryLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <AdminOnlyGate>
      <main className="flex h-full min-h-0 flex-col bg-[var(--background)]">
        {children}
      </main>
    </AdminOnlyGate>
  );
}
