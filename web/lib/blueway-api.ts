import { apiFetch, apiUrl } from "@/lib/api";
import {
  assertCredentialFreePayload,
  type BlueWayConnectAttempt,
  type BlueWayIntegrationStatus,
  type BlueWaySyncRunView,
  type BlueWayUnlinkedRecord,
} from "@/lib/blueway-integration";

async function integrationJson<T>(response: Response): Promise<T> {
  const body = (await response.json().catch(() => ({}))) as Record<string, unknown>;
  if (!response.ok) {
    throw new Error(String(body.detail || `Request failed: ${response.status}`));
  }
  assertCredentialFreePayload(body);
  return body as T;
}

export async function getBlueWayStatus(): Promise<BlueWayIntegrationStatus> {
  return integrationJson<BlueWayIntegrationStatus>(
    await apiFetch(apiUrl("/api/v1/integrations/blueway"), {
      cache: "no-store",
    }),
  );
}

export async function startBlueWayConnection(): Promise<BlueWayConnectAttempt> {
  return integrationJson<BlueWayConnectAttempt>(
    await apiFetch(apiUrl("/api/v1/integrations/blueway/connect/start"), {
      method: "POST",
    }),
  );
}

export async function getBlueWayCurrentAttempt(): Promise<BlueWayConnectAttempt | null> {
  const payload = await integrationJson<{ attempt: BlueWayConnectAttempt | null }>(
    await apiFetch(apiUrl("/api/v1/integrations/blueway/connect/current"), {
      cache: "no-store",
    }),
  );
  return payload.attempt;
}

export async function startBlueWayRecovery(): Promise<BlueWayConnectAttempt> {
  const attempt = await integrationJson<BlueWayConnectAttempt>(
    await apiFetch(apiUrl("/api/v1/integrations/blueway/recovery/start"), {
      method: "POST",
    }),
  );
  return { ...attempt, mode: "recovery" };
}

export async function getBlueWayConnectStatus(
  attemptId: string,
): Promise<BlueWayIntegrationStatus> {
  return integrationJson<BlueWayIntegrationStatus>(
    await apiFetch(
      apiUrl(`/api/v1/integrations/blueway/connect/${encodeURIComponent(attemptId)}/status`),
      { cache: "no-store" },
    ),
  );
}

export async function pollBlueWayConnection(
  attemptId: string,
): Promise<BlueWayIntegrationStatus> {
  return integrationJson<BlueWayIntegrationStatus>(
    await apiFetch(
      apiUrl(`/api/v1/integrations/blueway/connect/${encodeURIComponent(attemptId)}/poll`),
      { method: "POST" },
    ),
  );
}

export async function pollBlueWayRecovery(
  attemptId: string,
): Promise<BlueWayIntegrationStatus> {
  return integrationJson<BlueWayIntegrationStatus>(
    await apiFetch(
      apiUrl(`/api/v1/integrations/blueway/recovery/${encodeURIComponent(attemptId)}/poll`),
      { method: "POST" },
    ),
  );
}

export async function cancelBlueWayConnection(
  attemptId: string,
): Promise<BlueWayConnectAttempt> {
  const payload = await integrationJson<{ attempt: BlueWayConnectAttempt }>(
    await apiFetch(
      apiUrl(`/api/v1/integrations/blueway/connect/${encodeURIComponent(attemptId)}/cancel`),
      { method: "POST" },
    ),
  );
  return payload.attempt;
}

export async function startBlueWaySync(): Promise<BlueWaySyncRunView> {
  return integrationJson<BlueWaySyncRunView>(
    await apiFetch(apiUrl("/api/v1/integrations/blueway/sync"), {
      method: "POST",
    }),
  );
}

export async function listBlueWayUnlinked(): Promise<BlueWayUnlinkedRecord[]> {
  const payload = await integrationJson<{ records: BlueWayUnlinkedRecord[] }>(
    await apiFetch(apiUrl("/api/v1/integrations/blueway/unlinked"), {
      cache: "no-store",
    }),
  );
  return payload.records;
}

export async function disconnectBlueWay(expectedRevision: number): Promise<void> {
  await integrationJson<Record<string, unknown>>(
    await apiFetch(apiUrl("/api/v1/integrations/blueway/disconnect"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ expected_revision: expectedRevision }),
    }),
  );
}
