"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import ChatHistorySection from "@/components/space/ChatHistorySection";
import UnifiedChatPage from "@/components/chat/home/UnifiedChatPage";

type GeneralStudyView = "chat" | "recent";

function viewFromSearch(search: string): GeneralStudyView {
  return new URLSearchParams(search).get("view") === "recent"
    ? "recent"
    : "chat";
}

export default function GeneralStudyWorkspace() {
  const searchParams = useSearchParams();
  const view = viewFromSearch(searchParams.toString());

  return (
    <main className="flex h-full min-h-0 flex-col bg-[var(--background)]">
      <header className="shrink-0 border-b border-[var(--border)]/70 px-6 pt-7 sm:px-8 sm:pt-8">
        <div className="mx-auto w-full max-w-[960px]">
          <p className="text-xs font-medium uppercase tracking-[0.14em] text-[var(--muted-foreground)]">
            TEEECHR
          </p>
          <h1 className="mt-2 font-serif text-2xl font-semibold tracking-tight text-[var(--foreground)] sm:text-[28px]">
            General Study
          </h1>
          <p className="mt-1.5 max-w-xl text-sm leading-6 text-[var(--muted-foreground)]">
            Study anything outside a class.
          </p>
          <nav
            aria-label="General Study views"
            className="mt-6 flex gap-5 overflow-x-auto"
          >
            <WorkspaceTab href="/home" active={view === "chat"}>
              Chat
            </WorkspaceTab>
            <WorkspaceTab
              href="/home?view=recent"
              active={view === "recent"}
            >
              Recent
            </WorkspaceTab>
          </nav>
        </div>
      </header>

      <div className="min-h-0 flex-1">
        {view === "recent" ? (
          <div className="h-full overflow-y-auto px-6 py-7 sm:px-8 sm:py-8">
            <div className="mx-auto w-full max-w-[960px]">
              <ChatHistorySection scope="general" />
            </div>
          </div>
        ) : (
          <UnifiedChatPage
            hideCourseBar
            hideCourseScope
            hideSurfaceLabel
            surfaceLabel="General Study"
          />
        )}
      </div>
    </main>
  );
}

function WorkspaceTab({
  href,
  active,
  children,
}: {
  href: string;
  active: boolean;
  children: string;
}) {
  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      className={`shrink-0 border-b-2 pb-3 text-sm font-medium transition-colors ${
        active
          ? "border-[var(--foreground)] text-[var(--foreground)]"
          : "border-transparent text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
      }`}
    >
      {children}
    </Link>
  );
}
