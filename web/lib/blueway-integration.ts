export type BlueWayConnectionState =
  | "pending"
  | "active"
  | "credential_recovery_required"
  | "revocation_pending"
  | "disconnected"
  | "error";

export type BlueWayPairingState =
  | "pending"
  | "approved"
  | "expired"
  | "cancelled"
  | "failed";

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
  created_at?: number;
}

export interface BlueWayIntegrationStatus {
  enabled: boolean;
  connection: BlueWayConnectionView | null;
  active_run: BlueWaySyncRunView | null;
  pairing?: BlueWayConnectAttempt | null;
}

export interface BlueWayConnectAttempt {
  attempt_id: string;
  request_id: string;
  user_code: string;
  verification_uri: string;
  expires_at: number;
  mode?: "connect" | "recovery";
  state: BlueWayPairingState;
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
    if (!loopback) {
      const allowedPath = parsed.hostname === "blueway-teeechr-beta.expo.app"
        || parsed.hostname === "blueway.gesahni.com"
        ? "/teeechr-connect"
        : null;
      if (allowedPath !== parsed.pathname || parsed.hash) return null;
      const keys = [...parsed.searchParams.keys()].sort();
      if (keys.length !== 2 || keys[0] !== "request_id" || keys[1] !== "user_code") return null;
      const requestId = parsed.searchParams.get("request_id");
      const userCode = parsed.searchParams.get("user_code");
      if (
        !requestId
        || !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(requestId)
        || !userCode
        || !/^[A-Za-z0-9_-]{8,64}$/.test(userCode)
      ) return null;
    }
    return parsed.toString();
  } catch {
    return null;
  }
}

/** Build the same-phone handoff without accepting a caller-controlled scheme or destination. */
export function safeBlueWayNativeApprovalUri(input: {
  request_id: string;
  user_code: string;
}): string | null {
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(input.request_id)) return null;
  if (!/^[A-Za-z0-9_-]{8,64}$/.test(input.user_code)) return null;
  return `blueway://teeechr-connect?request_id=${encodeURIComponent(input.request_id)}&user_code=${encodeURIComponent(input.user_code)}`;
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
