import { apiFetch } from "@/lib/api";

export interface CurrentTester {
  id: string;
  tester_id: string;
  display_name: string;
}

async function expectJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail = `Request failed: ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body?.detail) detail = body.detail;
    } catch {
      // Use default detail.
    }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

export async function getCurrentTester(): Promise<CurrentTester | null> {
  const response = await apiFetch("/api/v1/access/me", { cache: "no-store" });
  if (response.status === 401) return null;
  const data = await expectJson<{ tester: CurrentTester }>(response);
  return data.tester;
}

export async function claimAccessCode(accessCode: string): Promise<CurrentTester> {
  const data = await expectJson<{ tester: CurrentTester }>(
    await apiFetch("/api/v1/access/claim", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ access_code: accessCode }),
    }),
  );
  return data.tester;
}

export async function logoutTester(): Promise<void> {
  await expectJson<{ ok: boolean }>(
    await apiFetch("/api/v1/access/logout", {
      method: "POST",
    }),
  );
}
