"use client";

import { LogOut } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { logout } from "@/lib/auth";
import { useAuthStatus } from "@/hooks/useAuthStatus";

interface LogoutButtonProps {
  collapsed?: boolean;
}

export function LogoutButton({ collapsed = false }: LogoutButtonProps) {
  const router = useRouter();
  const { t } = useTranslation();
  const { enabled } = useAuthStatus();
  const [error, setError] = useState(false);

  if (!enabled) return null;

  async function handleLogout() {
    setError(false);
    const result = await logout();
    if (result.ok) {
      router.replace("/login");
      return;
    }
    setError(true);
  }

  if (collapsed) {
    return (
      <div>
        <button
          onClick={handleLogout}
          className="rounded-lg p-2 text-[var(--muted-foreground)] transition-colors hover:bg-[var(--background)]/50 hover:text-red-500"
          aria-label={t("Sign out")}
          title={t("Sign out")}
        >
          <LogOut size={16} strokeWidth={1.5} />
        </button>
        {error && (
          <p role="alert" className="mt-1 text-xs text-red-500">
            {t("Unable to sign out. Please try again.")}
          </p>
        )}
      </div>
    );
  }

  return (
    <div>
      <button
        onClick={handleLogout}
        className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-[13.5px] text-[var(--muted-foreground)] transition-colors hover:bg-[var(--background)]/50 hover:text-red-500"
      >
        <LogOut size={16} strokeWidth={1.5} />
        <span>{t("Sign out")}</span>
      </button>
      {error && (
        <p role="alert" className="mt-1 px-3 text-xs text-red-500">
          {t("Unable to sign out. Please try again.")}
        </p>
      )}
    </div>
  );
}
