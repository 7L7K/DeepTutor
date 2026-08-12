"use client";

import { useCallback, useEffect, useState } from "react";
import { Check, Copy, KeyRound, Power, PowerOff, RotateCw, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  fetchEnrollment,
  rotateEnrollmentCode,
  setEnrollmentEnabled,
  type EnrollmentStatus,
} from "@/lib/admin-api";

const STATE_LABELS: Record<EnrollmentStatus["state"], string> = {
  active: "Active",
  disabled: "Disabled",
  not_configured: "Not configured",
  recovery_required: "Recovery required",
};

export function EnrollmentPanel() {
  const { t } = useTranslation();
  const [enrollment, setEnrollment] = useState<EnrollmentStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [oneTimeCode, setOneTimeCode] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const refresh = useCallback(async () => {
    const next = await fetchEnrollment();
    setEnrollment(next);
    return next;
  }, []);

  useEffect(() => {
    refresh().catch((reason) => {
      setError(reason instanceof Error ? reason.message : t("Failed to load enrollment"));
    });
  }, [refresh, t]);

  async function rotate() {
    if (!enrollment || busy) return;
    if (
      enrollment.configured &&
      !window.confirm(
        t("Rotate the shared invite code? The current code will stop working immediately."),
      )
    ) {
      return;
    }
    setBusy(true);
    setError("");
    setCopied(false);
    try {
      const result = await rotateEnrollmentCode(enrollment.revision);
      setEnrollment(result.enrollment);
      setOneTimeCode(result.code);
    } catch (reason) {
      await refresh().catch(() => undefined);
      setError(
        reason instanceof Error
          ? `${reason.message}. ${t(
              "A new code may have been activated, but it could not be displayed. Rotate again to create a code you can copy.",
            )}`
          : t("Failed to rotate invite code"),
      );
    } finally {
      setBusy(false);
    }
  }

  async function setEnabled(enabled: boolean) {
    if (!enrollment || busy) return;
    setBusy(true);
    setError("");
    try {
      setEnrollment(await setEnrollmentEnabled(enabled, enrollment.revision));
    } catch (reason) {
      await refresh().catch(() => undefined);
      setError(reason instanceof Error ? reason.message : t("Failed to update enrollment"));
    } finally {
      setBusy(false);
    }
  }

  async function copyCode() {
    if (!oneTimeCode) return;
    await navigator.clipboard.writeText(oneTimeCode);
    setCopied(true);
  }

  function closeSecret() {
    // The plaintext exists only in this transient state. Clearing it removes
    // the value from the rendered DOM and it cannot be recovered by refetching.
    setOneTimeCode(null);
    setCopied(false);
  }

  const unavailable = !enrollment?.model_available || enrollment?.recovery_required;

  return (
    <>
      <section className="mb-6 rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <KeyRound size={17} className="text-[var(--primary)]" />
              <h2 className="text-sm font-semibold text-[var(--foreground)]">
                {t("Enrollment")}
              </h2>
            </div>
            <p className="mt-1 text-xs text-[var(--muted-foreground)]">
              {t("Shared-code learner registration")}
            </p>
          </div>
          {enrollment && (
            <span className="rounded-full bg-[var(--muted)]/60 px-2.5 py-1 text-xs font-medium text-[var(--foreground)]">
              {t(STATE_LABELS[enrollment.state])}
            </span>
          )}
        </div>

        {enrollment ? (
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <div className="rounded-xl border border-[var(--border)] bg-[var(--background)]/50 px-3 py-2.5">
              <p className="text-xs text-[var(--muted-foreground)]">{t("Assigned model")}</p>
              <p className="mt-0.5 text-sm font-medium text-[var(--foreground)]">{t("Luna")}</p>
            </div>
            <div className="rounded-xl border border-[var(--border)] bg-[var(--background)]/50 px-3 py-2.5">
              <p className="text-xs text-[var(--muted-foreground)]">{t("Status")}</p>
              <p className="mt-0.5 text-sm font-medium text-[var(--foreground)]">
                {enrollment.model_available ? t("Available") : t("Unavailable")}
              </p>
            </div>
          </div>
        ) : (
          <p className="mt-4 text-sm text-[var(--muted-foreground)]">{t("Loading…")}</p>
        )}

        {error && (
          <p className="mt-3 rounded-lg bg-red-500/10 px-3 py-2 text-xs text-red-500">
            {error}
          </p>
        )}

        <div className="mt-4 flex flex-wrap gap-2">
          <button
            type="button"
            onClick={rotate}
            disabled={!enrollment || busy || unavailable}
            className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--foreground)] px-3 py-1.5 text-sm font-medium text-[var(--background)] disabled:cursor-not-allowed disabled:opacity-40"
          >
            {enrollment?.configured ? <RotateCw size={14} /> : <KeyRound size={14} />}
            {t(enrollment?.configured ? "Rotate" : "Generate")}
          </button>
          {enrollment?.configured && !enrollment.enabled && (
            <button
              type="button"
              onClick={() => setEnabled(true)}
              disabled={busy || unavailable}
              className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-1.5 text-sm text-[var(--foreground)] disabled:cursor-not-allowed disabled:opacity-40"
            >
              <Power size={14} />
              {t("Enable")}
            </button>
          )}
          {enrollment?.enabled && (
            <button
              type="button"
              onClick={() => setEnabled(false)}
              disabled={busy}
              className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-1.5 text-sm text-[var(--foreground)] disabled:cursor-not-allowed disabled:opacity-40"
            >
              <PowerOff size={14} />
              {t("Disable")}
            </button>
          )}
        </div>
      </section>

      {oneTimeCode !== null && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--overlay)] px-4"
          role="dialog"
          aria-modal="true"
          aria-labelledby="invite-code-title"
        >
          <div className="w-full max-w-md rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5 shadow-xl">
            <div className="flex items-center justify-between gap-4">
              <h2 id="invite-code-title" className="text-base font-semibold text-[var(--foreground)]">
                {t("Shared invite code")}
              </h2>
              <button
                type="button"
                onClick={closeSecret}
                className="rounded-md p-1 text-[var(--muted-foreground)] hover:bg-[var(--background)]"
                aria-label={t("Close")}
              >
                <X size={16} />
              </button>
            </div>
            <p className="mt-2 text-sm text-[var(--muted-foreground)]">
              {t("This code will not be shown again.")}
            </p>
            <code className="mt-4 block select-all rounded-xl border border-[var(--border)] bg-[var(--background)] px-4 py-3 text-center text-sm font-semibold tracking-wide text-[var(--foreground)]">
              {oneTimeCode}
            </code>
            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                onClick={copyCode}
                className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-1.5 text-sm text-[var(--foreground)]"
              >
                {copied ? <Check size={14} /> : <Copy size={14} />}
                {t(copied ? "Copied" : "Copy")}
              </button>
              <button
                type="button"
                onClick={closeSecret}
                className="rounded-lg bg-[var(--foreground)] px-3 py-1.5 text-sm font-medium text-[var(--background)]"
              >
                {t("Done")}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
