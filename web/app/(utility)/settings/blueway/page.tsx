"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { CheckCircle2, Loader2, RefreshCw, Unplug } from "lucide-react";

import { SettingsPageHeader } from "@/components/settings/shared";
import {
  disconnectBlueWay,
  getBlueWayStatus,
  listBlueWayUnlinked,
  pollBlueWayConnection,
  pollBlueWayRecovery,
  startBlueWayConnection,
  startBlueWayRecovery,
  startBlueWaySync,
} from "@/lib/blueway-api";
import {
  applyBlueWayActionIfCurrent,
  blueWayConnectionLabel,
  blueWayResponseIsCurrent,
  blueWaySyncIsRunning,
  safeBlueWayVerificationUri,
  type BlueWayConnectAttempt,
  type BlueWayIntegrationStatus,
  type BlueWayUnlinkedRecord,
} from "@/lib/blueway-integration";

const EMPTY_STATUS: BlueWayIntegrationStatus = {
  enabled: false,
  connection: null,
  active_run: null,
};

export default function BlueWaySettingsPage() {
  const [status, setStatus] = useState<BlueWayIntegrationStatus | null>(null);
  const [attempt, setAttempt] = useState<BlueWayConnectAttempt | null>(null);
  const [unlinked, setUnlinked] = useState<BlueWayUnlinkedRecord[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const identityEpochRef = useRef(0);
  const requestSequenceRef = useRef(0);
  const refreshInFlightRef = useRef(false);

  const refresh = useCallback(async () => {
    if (refreshInFlightRef.current) return;
    refreshInFlightRef.current = true;
    const identityEpoch = identityEpochRef.current;
    const requestSequence = ++requestSequenceRef.current;
    try {
      const next = attempt
        ? attempt.mode === "recovery"
          ? await pollBlueWayRecovery(attempt.attempt_id)
          : await pollBlueWayConnection(attempt.attempt_id)
        : await getBlueWayStatus();
      const nextUnlinked = next.connection?.state === "active"
        ? await listBlueWayUnlinked()
        : [];
      if (!blueWayResponseIsCurrent(
        identityEpoch,
        identityEpochRef.current,
        requestSequence,
        requestSequenceRef.current,
      )) return;
      setStatus(next);
      if (next.connection?.state === "active") {
        setAttempt(null);
      }
      setUnlinked(nextUnlinked);
      setMessage("");
    } catch (error) {
      if (!blueWayResponseIsCurrent(
        identityEpoch,
        identityEpochRef.current,
        requestSequence,
        requestSequenceRef.current,
      )) return;
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      refreshInFlightRef.current = false;
    }
  }, [attempt]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!attempt) return;
    const timer = window.setInterval(() => void refresh(), 3000);
    return () => window.clearInterval(timer);
  }, [attempt, refresh]);

  useEffect(() => {
    const clearForIdentityChange = () => {
      identityEpochRef.current += 1;
      requestSequenceRef.current += 1;
      const identityEpoch = identityEpochRef.current;
      const requestSequence = requestSequenceRef.current;
      setStatus(null);
      setAttempt(null);
      setUnlinked([]);
      setBusy(false);
      setMessage("");
      void getBlueWayStatus()
        .then((next) => {
          if (blueWayResponseIsCurrent(
            identityEpoch,
            identityEpochRef.current,
            requestSequence,
            requestSequenceRef.current,
          )) setStatus(next);
        })
        .catch(() => {
          if (blueWayResponseIsCurrent(
            identityEpoch,
            identityEpochRef.current,
            requestSequence,
            requestSequenceRef.current,
          )) setStatus(EMPTY_STATUS);
        });
    };
    window.addEventListener("dt:auth-changed", clearForIdentityChange);
    return () => window.removeEventListener("dt:auth-changed", clearForIdentityChange);
  }, []);

  async function run(action: (identityEpoch: number) => Promise<void>) {
    const identityEpoch = identityEpochRef.current;
    setBusy(true);
    setMessage("");
    try {
      await action(identityEpoch);
    } catch (error) {
      if (identityEpoch !== identityEpochRef.current) return;
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      if (identityEpoch === identityEpochRef.current) setBusy(false);
    }
  }

  const state = status ? blueWayConnectionLabel(status) : "loading";
  const syncing = blueWaySyncIsRunning(status?.active_run ?? null);
  const verificationUri = attempt
    ? safeBlueWayVerificationUri(attempt.verification_uri)
    : null;

  return (
    <div>
      <SettingsPageHeader
        title="BlueWay connection"
        description="Privately bring your classes, assignments, notes, course material, and ready lecture transcripts into TEEECHR."
      />

      <section className="rounded-2xl border border-[var(--border)]/70 bg-[var(--card)] p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 text-sm font-medium text-[var(--foreground)]">
              {state === "active" ? (
                <CheckCircle2 size={17} className="text-emerald-500" />
              ) : state === "loading" || busy ? (
                <Loader2 size={17} className="animate-spin text-[var(--muted-foreground)]" />
              ) : (
                <Unplug size={17} className="text-[var(--muted-foreground)]" />
              )}
              {state === "active"
                ? "Connected"
                : state === "credential_recovery_required"
                  ? "Credential recovery required"
                : state === "revocation_pending"
                  ? "Disconnecting safely"
                : state === "unavailable"
                  ? "Not enabled on this server"
                  : state === "loading"
                    ? "Checking connection"
                    : "Not connected"}
            </div>
            <p className="mt-2 max-w-2xl text-xs leading-relaxed text-[var(--muted-foreground)]">
              Connecting grants read-only access to all supported academic data in your BlueWay account. It does not share your private TEEECHR workspace, change BlueWay data, or copy raw lecture audio.
            </p>
          </div>

          {state === "active" ? (
            <div className="flex gap-2">
              <button
                type="button"
                disabled={busy || syncing}
                onClick={() =>
                  void run(async (identityEpoch) => {
                    await applyBlueWayActionIfCurrent(
                      startBlueWaySync(),
                      identityEpoch,
                      () => identityEpochRef.current,
                      async () => refresh(),
                    );
                  })
                }
                className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-2 text-xs font-medium disabled:opacity-50"
              >
                <RefreshCw size={14} className={syncing ? "animate-spin" : ""} />
                {syncing ? "Syncing" : "Sync now"}
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() =>
                  void run(async (identityEpoch) => {
                    const connection = status?.connection;
                    if (!connection) return;
                    if (!window.confirm("Disconnect BlueWay? Imported Courses and sources will be kept, but future sync will stop.")) return;
                    await applyBlueWayActionIfCurrent(
                      disconnectBlueWay(connection.revision),
                      identityEpoch,
                      () => identityEpochRef.current,
                      async () => {
                        setAttempt(null);
                        await refresh();
                      },
                    );
                  })
                }
                className="rounded-lg border border-red-500/30 px-3 py-2 text-xs font-medium text-red-600 disabled:opacity-50 dark:text-red-400"
              >
                Disconnect
              </button>
            </div>
          ) : state === "credential_recovery_required" ? (
            <button
              type="button"
              disabled={busy}
              onClick={() =>
                void run(async (identityEpoch) => {
                  await applyBlueWayActionIfCurrent(
                    startBlueWayRecovery(),
                    identityEpoch,
                    () => identityEpochRef.current,
                    (nextAttempt) => setAttempt(nextAttempt),
                  );
                })
              }
              className="rounded-lg border border-amber-500/30 px-3 py-2 text-xs font-medium text-amber-700 disabled:opacity-50 dark:text-amber-300"
            >
              Reconnect BlueWay
            </button>
          ) : state === "revocation_pending" ? (
            <button
              type="button"
              disabled={busy}
              onClick={() =>
                void run(async (identityEpoch) => {
                  const connection = status?.connection;
                  if (!connection) return;
                  await applyBlueWayActionIfCurrent(
                    disconnectBlueWay(connection.revision),
                    identityEpoch,
                    () => identityEpochRef.current,
                    async () => refresh(),
                  );
                })
              }
              className="rounded-lg border border-amber-500/30 px-3 py-2 text-xs font-medium text-amber-700 disabled:opacity-50 dark:text-amber-300"
            >
              Retry secure disconnect
            </button>
          ) : state === "not_connected" ? (
            <button
              type="button"
              disabled={busy}
              onClick={() =>
                void run(async (identityEpoch) => {
                  await applyBlueWayActionIfCurrent(
                    startBlueWayConnection(),
                    identityEpoch,
                    () => identityEpochRef.current,
                    (nextAttempt) => setAttempt(nextAttempt),
                  );
                })
              }
              className="rounded-lg bg-[var(--foreground)] px-4 py-2 text-xs font-medium text-[var(--background)] disabled:opacity-50"
            >
              Connect BlueWay
            </button>
          ) : null}
        </div>

        {state === "credential_recovery_required" && (
          <p className="mt-4 rounded-xl border border-amber-500/25 bg-amber-500/5 p-3 text-xs leading-relaxed text-amber-800 dark:text-amber-200">
            TEEECHR cannot read the saved BlueWay credential, so sync and disconnect are safely paused. Your imported Courses, sources, mastery, and history remain available. Reconnect using the same BlueWay account to restore access.
          </p>
        )}

        {attempt && (
          <div className="mt-5 rounded-xl border border-blue-500/25 bg-blue-500/5 p-4">
            <p className="text-xs text-[var(--muted-foreground)]">
              Open this BlueWay approval page, sign in to {attempt.mode === "recovery" ? "the same BlueWay account" : "BlueWay"}, review the academic-data consent, and enter the one-time code:
            </p>
            <div className="mt-3 flex flex-wrap items-center gap-3">
              {verificationUri ? (
                <a
                  href={verificationUri}
                  target="_blank"
                  rel="noreferrer noopener"
                  className="text-sm font-medium text-blue-600 underline dark:text-blue-400"
                >
                  Open BlueWay
                </a>
              ) : (
                <span className="text-xs font-medium text-red-600 dark:text-red-400">
                  The server returned an unsafe approval address.
                </span>
              )}
              <code className="rounded-lg bg-[var(--background)] px-4 py-2 text-lg font-semibold tracking-[0.18em]">
                {attempt.user_code}
              </code>
            </div>
            <p className="mt-3 text-[11px] text-[var(--muted-foreground)]">
              This page checks for approval automatically. The code expires and cannot be reused.
            </p>
          </div>
        )}

        {message && (
          <p role="alert" className="mt-4 text-xs text-red-600 dark:text-red-400">
            {message}
          </p>
        )}
      </section>

      {state === "active" && (
        <section className="mt-4 rounded-2xl border border-[var(--border)]/70 bg-[var(--card)] p-5">
          <h2 className="text-sm font-medium">Import readiness</h2>
          <div className="mt-3 grid gap-3 sm:grid-cols-3">
            <Readiness label="Connection" value="Accepted" />
            <Readiness
              label="Academic sync"
              value={status?.active_run?.state ?? (status?.connection?.last_sync_at ? "Completed" : "Waiting")}
            />
            <Readiness label="Needs course" value={String(unlinked.length)} />
          </div>
          <p className="mt-4 text-xs leading-relaxed text-[var(--muted-foreground)]">
            Connection, structured sync, and Knowledge indexing are separate states. You can use a Course only after its sources report ready.
          </p>
        </section>
      )}
    </div>
  );
}

function Readiness({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-[var(--border)]/60 px-4 py-3">
      <div className="text-[11px] text-[var(--muted-foreground)]">{label}</div>
      <div className="mt-1 text-sm font-medium capitalize">{value}</div>
    </div>
  );
}
