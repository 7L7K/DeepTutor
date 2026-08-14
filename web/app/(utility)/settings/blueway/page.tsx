"use client";

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import Image from "next/image";
import { useSearchParams } from "next/navigation";
import { CheckCircle2, Loader2, RefreshCw, Unplug } from "lucide-react";
import QRCode from "qrcode";

import { SettingsPageHeader } from "@/components/settings/shared";
import {
  cancelBlueWayConnection,
  cancelBlueWayRecovery,
  disconnectBlueWay,
  getBlueWayConnectStatus,
  getBlueWayCurrentAttempt,
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
  blueWayPairingErrorMessage,
  blueWayResponseIsCurrent,
  blueWaySyncIsRunning,
  safeBlueWayVerificationUri,
  safeBlueWayNativeApprovalUri,
  type BlueWayConnectAttempt,
  type BlueWayIntegrationStatus,
  type BlueWaySyncState,
  type BlueWayUnlinkedRecord,
} from "@/lib/blueway-integration";

const EMPTY_STATUS: BlueWayIntegrationStatus = {
  enabled: false,
  connection: null,
  active_run: null,
};

export default function BlueWaySettingsPage(props: {
  mode?: "settings" | "connect" | "complete";
}) {
  return (
    <Suspense fallback={<div className="p-5 text-sm text-[var(--muted-foreground)]">Checking connection…</div>}>
      <BlueWaySettingsPageContent {...props} />
    </Suspense>
  );
}

function BlueWaySettingsPageContent({
  mode = "settings",
}: {
  mode?: "settings" | "connect" | "complete";
}) {
  const searchParams = useSearchParams();
  const completionAttemptId = safeAttemptId(searchParams.get("request_id"));
  const [status, setStatus] = useState<BlueWayIntegrationStatus | null>(null);
  const [attempt, setAttempt] = useState<BlueWayConnectAttempt | null>(null);
  const [unlinked, setUnlinked] = useState<BlueWayUnlinkedRecord[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [completionFinished, setCompletionFinished] = useState(false);
  const [showFallback, setShowFallback] = useState(false);
  const [fallbackQr, setFallbackQr] = useState<string | null>(null);
  const [clock, setClock] = useState(() => Date.now() / 1000);
  const identityEpochRef = useRef(0);
  const requestSequenceRef = useRef(0);
  const refreshInFlightRef = useRef(false);

  const refresh = useCallback(async () => {
    if (refreshInFlightRef.current) return;
    refreshInFlightRef.current = true;
    const identityEpoch = identityEpochRef.current;
    const requestSequence = ++requestSequenceRef.current;
    try {
      if (mode === "complete" && !completionAttemptId) {
        setStatus(null);
        setAttempt(null);
        setUnlinked([]);
        setMessage("This completion link is incomplete. Start a new connection from TEEECHR.");
        return;
      }
      let knownAttempt = attempt;
      if (!knownAttempt && mode !== "complete") {
        knownAttempt = await getBlueWayCurrentAttempt();
      }
      if (!knownAttempt && mode === "connect") {
        const current = await getBlueWayStatus();
        const canStart = !current.connection || current.connection.state === "disconnected" || current.connection.state === "error";
        if (canStart) {
          const started = await startBlueWayConnection();
          if (!blueWayResponseIsCurrent(
            identityEpoch,
            identityEpochRef.current,
            requestSequence,
            requestSequenceRef.current,
          )) return;
          setStatus(current);
          setAttempt(started);
          setMessage("");
          return;
        }
        knownAttempt = null;
      }
      if (knownAttempt && knownAttempt.state !== "pending") {
        const next = mode === "complete" && !completionFinished
          ? await getBlueWayConnectStatus(knownAttempt.attempt_id)
          : await getBlueWayStatus();
        if (!blueWayResponseIsCurrent(
          identityEpoch,
          identityEpochRef.current,
          requestSequence,
          requestSequenceRef.current,
        )) return;
        setStatus(next);
        setAttempt(next.pairing ?? knownAttempt);
        if (next.connection?.state === "active" && mode === "complete") setCompletionFinished(true);
        setMessage("");
        return;
      }
      const pollAttemptId = knownAttempt?.attempt_id ?? (mode === "complete" && !completionFinished ? completionAttemptId : null);
      const next = pollAttemptId
        ? knownAttempt?.mode === "recovery"
          ? await pollBlueWayRecovery(pollAttemptId)
          : await pollBlueWayConnection(pollAttemptId)
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
      if (next.pairing) {
        setAttempt(next.pairing);
      }
      if (next.connection?.state === "active") {
        if (mode === "complete") setCompletionFinished(true);
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
      setMessage(blueWayPairingErrorMessage(error));
    } finally {
      refreshInFlightRef.current = false;
    }
  }, [attempt, completionAttemptId, completionFinished, mode]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!attempt || attempt.state !== "pending") return;
    const timer = window.setInterval(() => {
      setClock(Date.now() / 1000);
      void refresh();
    }, 1000);
    return () => window.clearInterval(timer);
  }, [attempt, completionAttemptId, completionFinished, mode, refresh]);

  useEffect(() => {
    if (mode !== "complete" || completionFinished || !completionAttemptId) return;
    const timer = window.setInterval(() => void refresh(), 3000);
    return () => window.clearInterval(timer);
  }, [completionAttemptId, completionFinished, mode, refresh]);

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
      setShowFallback(false);
      setFallbackQr(null);
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
      setMessage(blueWayPairingErrorMessage(error));
    } finally {
      if (identityEpoch === identityEpochRef.current) setBusy(false);
    }
  }

  const connectionState = status ? blueWayConnectionLabel(status) : "loading";
  const pairingState = attempt?.state ?? "idle";
  const remainingSeconds = attempt?.state === "pending"
    ? Math.max(0, Math.ceil(attempt.expires_at - clock))
    : null;
  const pendingLeaseEnded = pairingState === "pending" && remainingSeconds === 0;
  const displayPairingState = pendingLeaseEnded ? "expired" : pairingState;
  const state = displayPairingState === "pending" ? "pending" : connectionState;
  const syncing = blueWaySyncIsRunning(status?.active_run ?? null);
  const syncTakingLonger = syncing
    && typeof status?.active_run?.created_at === "number"
    && clock - status.active_run.created_at >= 90;
  const verificationUri = attempt
    ? safeBlueWayVerificationUri(attempt.verification_uri)
    : null;
  const nativeApprovalUri = attempt
    ? safeBlueWayNativeApprovalUri({ request_id: attempt.request_id, user_code: attempt.user_code })
    : null;

  useEffect(() => {
    let current = true;
    if (!showFallback || !verificationUri) {
      setFallbackQr(null);
      return () => { current = false; };
    }
    void QRCode.toDataURL(verificationUri, {
      errorCorrectionLevel: "M",
      margin: 2,
      width: 240,
    }).then((value) => {
      if (current) setFallbackQr(value);
    }).catch(() => {
      if (current) setFallbackQr(null);
    });
    return () => { current = false; };
  }, [showFallback, verificationUri]);

  useEffect(() => {
    if (!syncing) return;
    const timer = window.setInterval(() => {
      setClock(Date.now() / 1000);
      void refresh();
    }, 3000);
    return () => window.clearInterval(timer);
  }, [refresh, syncing]);

  if (mode === "complete" && !completionAttemptId) {
    return (
      <div>
        <SettingsPageHeader
          title="Connection link unavailable"
          description="The approval result cannot be confirmed without a valid pairing request."
        />
        <section className="rounded-2xl border border-red-500/25 bg-red-500/5 p-5">
          <p role="alert" className="text-sm text-red-700 dark:text-red-300">
            This completion link is incomplete. Start a new connection from TEEECHR.
          </p>
        </section>
      </div>
    );
  }

  return (
    <div>
      <SettingsPageHeader
        title={mode === "complete" ? "Connection approved" : mode === "connect" ? "Connect BlueWay to TEEECHR" : "BlueWay connection"}
        description={mode === "complete"
          ? "Your approval was received. TEEECHR is checking the connection and preparing your classes."
          : "Privately bring your classes, assignments, notes, course material, and ready lecture transcripts into TEEECHR."}
      />

      <section className="rounded-2xl border border-[var(--border)]/70 bg-[var(--card)] p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 text-sm font-medium text-[var(--foreground)]">
              {state === "active" ? (
                <CheckCircle2 size={17} className="text-emerald-500" />
              ) : state === "pending" ? (
                <Loader2 size={17} className="animate-spin text-blue-500" />
              ) : state === "loading" || busy ? (
                <Loader2 size={17} className="animate-spin text-[var(--muted-foreground)]" />
              ) : (
                <Unplug size={17} className="text-[var(--muted-foreground)]" />
              )}
              {state === "pending"
                ? "Waiting for BlueWay approval"
                : state === "active"
                ? "Connected"
                : state === "credential_recovery_required"
                  ? "Credential recovery required"
                : state === "revocation_pending"
                  ? "Disconnecting safely"
                : state === "unavailable"
                  ? "Not enabled on this server"
                  : state === "loading"
                    ? "Checking connection"
                    : displayPairingState === "expired"
                      ? "Connection request expired"
                      : displayPairingState === "cancelled"
                        ? "Connection canceled"
                        : displayPairingState === "failed"
                          ? "Connection failed"
                          : displayPairingState === "approved"
                            ? "Connection approved"
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
          ) : state === "pending" ? (
            <button
              type="button"
              disabled={busy}
              onClick={() =>
                void run(async () => {
                  if (!attempt) return;
                  const next = attempt.mode === "recovery"
                    ? await cancelBlueWayRecovery(attempt.attempt_id)
                    : await cancelBlueWayConnection(attempt.attempt_id);
                  setAttempt(next);
                  setShowFallback(false);
                  setFallbackQr(null);
                })
              }
              className="rounded-lg border border-red-500/30 px-3 py-2 text-xs font-medium text-red-600 disabled:opacity-50 dark:text-red-400"
            >
              {attempt?.mode === "recovery" ? "Stop recovery" : "Stop pairing"}
            </button>
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
                    (nextAttempt) => {
                      setAttempt(nextAttempt);
                      setShowFallback(false);
                      setFallbackQr(null);
                    },
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
          ) : state === "not_connected" || displayPairingState === "expired" || displayPairingState === "cancelled" || displayPairingState === "failed" ? (
            <button
              type="button"
              disabled={busy}
              onClick={() =>
                void run(async (identityEpoch) => {
                  await applyBlueWayActionIfCurrent(
                    startBlueWayConnection(),
                    identityEpoch,
                    () => identityEpochRef.current,
                    (nextAttempt) => {
                      setAttempt(nextAttempt);
                      setShowFallback(false);
                      setFallbackQr(null);
                    },
                  );
                })
              }
              className="rounded-lg bg-[var(--foreground)] px-4 py-2 text-xs font-medium text-[var(--background)] disabled:opacity-50"
            >
                  {displayPairingState === "idle"
                ? "Start connection"
                : displayPairingState === "failed"
                  ? "Retry connection"
                  : displayPairingState === "cancelled"
                    ? "Redo connection"
                  : "Start new connection"}
            </button>
          ) : null}
        </div>

        {state === "credential_recovery_required" && (
          <p className="mt-4 rounded-xl border border-amber-500/25 bg-amber-500/5 p-3 text-xs leading-relaxed text-amber-800 dark:text-amber-200">
            TEEECHR cannot read the saved BlueWay credential, so sync and disconnect are safely paused. Your imported Courses, sources, mastery, and history remain available. Reconnect using the same BlueWay account to restore access.
          </p>
        )}

        {attempt?.state === "pending" && !pendingLeaseEnded && (
          <div className="mt-5 rounded-xl border border-blue-500/25 bg-blue-500/5 p-4">
            <p className="text-xs text-[var(--muted-foreground)]">
              Continue in the BlueWay app to review the academic-data consent. The cross-device fallback is available below.
            </p>
            <div className="mt-3 flex flex-wrap items-center gap-3">
              {nativeApprovalUri ? (
                <a
                  href={nativeApprovalUri}
                  className="inline-flex items-center rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white"
                >
                  Continue in BlueWay
                </a>
              ) : null}
              {!nativeApprovalUri ? (
                <span className="text-xs font-medium text-red-600 dark:text-red-400">
                  The server returned an invalid same-phone handoff.
                </span>
              ) : null}
            </div>
            <button
              type="button"
              onClick={() => setShowFallback((visible) => !visible)}
              className="mt-4 text-xs font-medium text-[var(--muted-foreground)] underline"
            >
              {showFallback ? "Hide another-device options" : "Use another device"}
            </button>
            {showFallback && (
              <div className="mt-3 rounded-lg border border-[var(--border)]/60 bg-[var(--background)] p-3">
                <p className="text-xs text-[var(--muted-foreground)]">
                  Open the fixed approval page on another device, then enter this one-time code. It expires in {formatRemaining(remainingSeconds)}.
                </p>
                {verificationUri ? (
                  <a
                    href={verificationUri}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="mt-2 block break-all text-xs font-medium text-blue-600 underline dark:text-blue-400"
                  >
                    Open approval page
                  </a>
                ) : null}
                {fallbackQr ? (
                  <Image
                    src={fallbackQr}
                    alt="QR code for the fixed BlueWay approval page"
                    width={192}
                    height={192}
                    unoptimized
                    className="mt-3 h-48 w-48 rounded bg-white p-2"
                  />
                ) : null}
                <code className="mt-3 inline-block rounded-lg bg-[var(--card)] px-4 py-2 text-lg font-semibold tracking-[0.18em]">
                  {attempt.user_code}
                </code>
              </div>
            )}
            <p className="mt-3 text-[11px] text-[var(--muted-foreground)]">
              Expires in {formatRemaining(remainingSeconds)}. The server—not this countdown—decides whether approval is valid.
            </p>
          </div>
        )}

        {displayPairingState === "expired" && (
          <p role="status" className="mt-5 rounded-xl border border-amber-500/25 bg-amber-500/5 p-3 text-xs text-amber-800 dark:text-amber-200">
            This connection request expired. Start a new connection.
          </p>
        )}
        {displayPairingState === "cancelled" && (
          <p role="status" className="mt-5 rounded-xl border border-[var(--border)]/60 p-3 text-xs text-[var(--muted-foreground)]">
            Connection canceled. Start a new connection when you are ready.
          </p>
        )}
        {displayPairingState === "failed" && (
          <p role="alert" className="mt-5 rounded-xl border border-red-500/25 bg-red-500/5 p-3 text-xs text-red-700 dark:text-red-300">
            Could not complete this connection. Retry after confirming there is no active request.
          </p>
        )}
        {displayPairingState === "approved" && state !== "active" && (
          <p role="status" className="mt-5 rounded-xl border border-emerald-500/25 bg-emerald-500/5 p-3 text-xs text-emerald-700 dark:text-emerald-300">
            Connection approved. TEEECHR is checking the connection and starting sync.
          </p>
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
              value={syncStateCopy(status?.active_run?.state, status?.connection?.last_sync_at)}
            />
            <Readiness label="Needs course" value={String(unlinked.length)} />
          </div>
          <p className="mt-4 text-xs leading-relaxed text-[var(--muted-foreground)]">
            Connection, structured sync, and Knowledge indexing are separate states. You can use a Course only after its sources report ready.
          </p>
          {syncTakingLonger && (
            <p role="status" className="mt-3 rounded-xl border border-amber-500/25 bg-amber-500/5 p-3 text-xs text-amber-800 dark:text-amber-200">
              Taking longer than expected. TEEECHR is continuing the same sync run; no duplicate sync was started.
            </p>
          )}
        </section>
      )}
    </div>
  );
}

function safeAttemptId(value: string | null): string | null {
  return value && /^[A-Za-z0-9-]{16,128}$/.test(value) ? value : null;
}

function formatRemaining(seconds: number | null): string {
  if (seconds === null) return "unknown time";
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return `${minutes}:${String(remainder).padStart(2, "0")}`;
}

function syncStateCopy(
  state: BlueWaySyncState | undefined,
  lastSyncAt?: number | null,
): string {
  switch (state) {
    case "queued": return "Waiting to import your classes";
    case "fetching": return "Fetching classes and academic data";
    case "validating": return "Checking imported data";
    case "staging": return "Preparing your Courses";
    case "indexing": return "Making your Course materials searchable";
    case "completed": return "Import complete";
    case "failed": return "Import could not finish";
    case "cancelled": return "Import canceled";
    default: return lastSyncAt ? "Import complete" : "Waiting to import your classes";
  }
}

function Readiness({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-[var(--border)]/60 px-4 py-3">
      <div className="text-[11px] text-[var(--muted-foreground)]">{label}</div>
      <div className="mt-1 text-sm font-medium capitalize">{value}</div>
    </div>
  );
}
