"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { ShieldCheck } from "lucide-react";

import { useAuthStatus } from "@/hooks/useAuthStatus";

/**
 * Protect an admin-only page at the browser route boundary as well as at the
 * API boundary. Auth-disabled local runs are the implicit local admin.
 */
export default function AdminGate({
  children,
  required = true,
}: {
  children: React.ReactNode;
  required?: boolean;
}) {
  const router = useRouter();
  const { enabled, isAdmin, loading } = useAuthStatus();
  const denied = !loading && enabled && !isAdmin;

  useEffect(() => {
    if (denied) router.replace("/home");
  }, [denied, router]);

  if (!required) {
    return <>{children}</>;
  }

  if (!loading && (!enabled || isAdmin)) {
    return <>{children}</>;
  }

  if (loading) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center text-[13px] text-[var(--muted-foreground)]">
        Checking access…
      </div>
    );
  }

  if (denied) {
    return (
      <div className="mx-auto flex min-h-[40vh] max-w-md flex-col items-center justify-center text-center">
        <ShieldCheck size={24} className="mb-3 text-[var(--muted-foreground)]" />
        <h1 className="text-base font-semibold text-[var(--foreground)]">
          Administrator access required
        </h1>
        <p className="mt-2 text-sm text-[var(--muted-foreground)]">
          This area manages deployment-wide tools and settings.
        </p>
      </div>
    );
  }

  return <>{children}</>;
}
