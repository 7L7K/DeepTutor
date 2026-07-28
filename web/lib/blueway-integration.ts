export type BlueWayConnectionState =
  | "pending"
  | "active"
  | "credential_recovery_required"
  | "revocation_pending"
  | "disconnected"
  | "error";

export type BlueWaySyncState =
  | "queued"
  | "fetching"
  | "validating"
  | "staging"
  | "indexing"
  | "completed"
  | "failed"
  | "cancelled";

export interface BlueWayConnectionView {
  id: string;
  state: BlueWayConnectionState;
  revision: number;
  scope_version: "academic.read.v1";
  connected_at?: number | null;
  last_sync_at?: number | null;
}

export interface BlueWaySyncRunView {
  id: string;
  state: BlueWaySyncState;
  counts?: Record<string, number>;
  error_code?: string | null;
}

export interface BlueWayIntegrationStatus {
  enabled: boolean;
  connection: BlueWayConnectionView | null;
  active_run: BlueWaySyncRunView | null;
}

export interface BlueWayConnectAttempt {
  attempt_id: string;
  user_code: string;
  verification_uri: string;
  expires_at: number;
  mode?: "connect" | "recovery";
}

export interface BlueWayUnlinkedRecord {
  record_kind: string;
  external_record_id: string;
  display_name?: string | null;
}

const RUNNING_SYNC_STATES = new Set<BlueWaySyncState>([
  "queued",
  "fetching",
  "validating",
  "staging",
  "indexing",
]);

export function blueWaySyncIsRunning(run: BlueWaySyncRunView | null): boolean {
  return run !== null && RUNNING_SYNC_STATES.has(run.state);
}

export function blueWayConnectionLabel(
  status: BlueWayIntegrationStatus,
): "unavailable" | "not_connected" | BlueWayConnectionState {
  if (!status.enabled) return "unavailable";
  return status.connection?.state ?? "not_connected";
}

export function blueWayResponseIsCurrent(
  requestIdentityEpoch: number,
  currentIdentityEpoch: number,
  requestSequence: number,
  currentSequence: number,
): boolean {
  return (
    blueWayIdentityIsCurrent(requestIdentityEpoch, currentIdentityEpoch) &&
    requestSequence === currentSequence
  );
}

export function blueWayIdentityIsCurrent(
  requestIdentityEpoch: number,
  currentIdentityEpoch: number,
): boolean {
  return requestIdentityEpoch === currentIdentityEpoch;
}

export async function applyBlueWayActionIfCurrent<T>(
  operation: Promise<T>,
  requestIdentityEpoch: number,
  currentIdentityEpoch: () => number,
  apply: (value: T) => void | Promise<void>,
): Promise<boolean> {
  const value = await operation;
  if (!blueWayIdentityIsCurrent(
    requestIdentityEpoch,
    currentIdentityEpoch(),
  )) return false;
  await apply(value);
  return true;
}

export function safeBlueWayVerificationUri(value: string): string | null {
  try {
    const parsed = new URL(value);
    const loopback = parsed.hostname === "localhost" || parsed.hostname === "127.0.0.1";
    if (parsed.protocol !== "https:" && !(loopback && parsed.protocol === "http:")) {
      return null;
    }
    if (parsed.username || parsed.password) return null;
    return parsed.toString();
  } catch {
    return null;
  }
}

/**
 * Reject accidental browser-facing credential fields. The backend contract is
 * deliberately metadata-only; this guard makes regressions visible before a
 * response is retained in component state or logged by browser tooling.
 */
export function assertCredentialFreePayload(value: unknown): void {
  walk(value, new Set());
}

function walk(value: unknown, seen: Set<object>): void {
  if (value === null || typeof value !== "object") return;
  if (seen.has(value)) return;
  seen.add(value);

  if (Array.isArray(value)) {
    value.forEach((item) => walk(item, seen));
    return;
  }

  for (const [key, nested] of Object.entries(value)) {
    const normalized = key.toLowerCase().replaceAll("-", "_");
    if (
      normalized === "access_token" ||
      normalized === "refresh_token" ||
      normalized === "client_secret" ||
      normalized === "master_key" ||
      normalized === "credential_ref" ||
      normalized === "key_id" ||
      normalized === "quarantine_path" ||
      normalized === "staging_path" ||
      normalized === "pkce_verifier" ||
      normalized === "device_code"
    ) {
      throw new Error("BlueWay response contained credential material");
    }
    walk(nested, seen);
  }
}
