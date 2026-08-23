"use client";

import { Lock } from "lucide-react";
import { useTranslation } from "react-i18next";

import { CAPABILITY_LABEL, type Capability } from "@/lib/capability-routes";

import { useCapabilityAccess } from "./CapabilityAccessContext";

export function CapabilityCheckingNotice() {
  const { t } = useTranslation();
  return (
    <div
      role="status"
      className="flex min-h-[40vh] items-center justify-center text-[13px] text-[var(--muted-foreground)]"
    >
      {t("Checking feature access…")}
    </div>
  );
}

export function CapabilityProbeFailureNotice({
  onRetry,
  compact = false,
}: {
  onRetry: () => void;
  compact?: boolean;
}) {
  const { t } = useTranslation();
  return (
    <div
      role="alert"
      className={
        compact
          ? "mx-auto mb-3 flex w-full max-w-3xl items-center justify-between gap-4 rounded-xl border border-red-300/60 bg-red-50/60 px-4 py-3 text-sm text-red-900 dark:border-red-900/60 dark:bg-red-950/20 dark:text-red-200"
          : "mx-auto flex min-h-[40vh] max-w-md flex-col items-center justify-center px-6 text-center"
      }
    >
      <div>
        <div className="font-medium">{t("Feature access could not be verified")}</div>
        <p className="mt-1 text-sm opacity-80">
          {t("Check your connection and try again.")}
        </p>
      </div>
      <button
        type="button"
        onClick={onRetry}
        className="mt-4 shrink-0 rounded-lg border border-current px-3 py-2 text-sm font-medium hover:opacity-80"
      >
        {t("Retry")}
      </button>
    </div>
  );
}

/**
 * Full-surface "this feature is locked" notice. Shown in place of a feature
 * page when the current user lacks the required model capability. Never hides
 * the feature — it explains why it is unavailable and what to do.
 */
export function LockedFeatureNotice({
  capability,
}: {
  capability: Capability;
}) {
  const { t } = useTranslation();
  const modelLabel = t(CAPABILITY_LABEL[capability]);

  return (
    <div className="flex h-full w-full items-center justify-center p-6">
      <div className="flex max-w-md flex-col items-center gap-4 rounded-2xl border border-[var(--border)] bg-[var(--secondary)]/40 px-8 py-10 text-center">
        <div className="flex h-12 w-12 items-center justify-center rounded-full bg-[var(--background)] text-[var(--muted-foreground)]">
          <Lock size={20} strokeWidth={1.8} />
        </div>
        <h2 className="text-base font-semibold text-[var(--foreground)]">
          {t("Feature locked")}
        </h2>
        <p className="text-sm leading-relaxed text-[var(--muted-foreground)]">
          {t(
            "Your account doesn't have {{model}} assigned yet. Please contact your administrator to get access.",
            { model: modelLabel },
          )}
        </p>
      </div>
    </div>
  );
}

/**
 * Renders {children} only when the user has the required capability; otherwise
 * renders the locked notice. Pass capability=null to never gate.
 */
export function RequireCapability({
  capability,
  children,
}: {
  capability: Capability | null;
  children: React.ReactNode;
}) {
  const { known, loading, error, has, refresh } = useCapabilityAccess();
  if (!capability) return <>{children}</>;
  if (!known && loading) return <CapabilityCheckingNotice />;
  if (!known && error) {
    return <CapabilityProbeFailureNotice onRetry={() => void refresh()} />;
  }
  if (!known) return <CapabilityCheckingNotice />;
  const granted = has(capability);
  return (
    <>
      {error ? (
        <CapabilityProbeFailureNotice
          compact
          onRetry={() => void refresh()}
        />
      ) : null}
      {granted ? children : <LockedFeatureNotice capability={capability} />}
    </>
  );
}
