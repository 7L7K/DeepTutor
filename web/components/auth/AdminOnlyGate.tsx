"use client";

import { useEffect, type ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";

import { useAuthStatus } from "@/hooks/useAuthStatus";

/**
 * Client-side route guard for deployment-wide administrator surfaces.
 *
 * The backend remains the authority. This guard prevents an ordinary account
 * from mounting the page, fetching its admin data, or seeing a flash of the
 * protected UI after following a direct URL.
 */
export function AdminOnlyGate({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const { authenticated, isAdmin, loading } = useAuthStatus();

  useEffect(() => {
    if (loading) return;
    if (!authenticated) {
      const next = encodeURIComponent(
        `${pathname}${window.location.search}`,
      );
      router.replace(`/login?next=${next}`);
      return;
    }
    if (!isAdmin) {
      router.replace("/classes");
    }
  }, [authenticated, isAdmin, loading, pathname, router]);

  if (loading || !authenticated || !isAdmin) {
    return (
      <main
        className="flex h-full min-h-0 items-center justify-center bg-[var(--background)] px-6 text-sm text-[var(--muted-foreground)]"
        role="status"
      >
        Checking access…
      </main>
    );
  }

  return <>{children}</>;
}
