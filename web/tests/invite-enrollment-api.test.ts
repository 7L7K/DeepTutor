import test from "node:test";
import assert from "node:assert/strict";

import {
  fetchEnrollment,
  rotateEnrollmentCode,
  setEnrollmentEnabled,
} from "../lib/admin-api";
import { register } from "../lib/auth";

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

test("invited registration sends the shared code and succeeds into auth context", async () => {
  const priorFetch = globalThis.fetch;
  const priorWindow = (globalThis as any).window;
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  let changed = 0;
  (globalThis as any).window = {
    dispatchEvent: () => {
      changed += 1;
    },
  };
  globalThis.fetch = (async (url: string | URL | Request, init?: RequestInit) => {
    calls.push({ url: String(url), init });
    return response({ ok: true, role: "user" }, 201);
  }) as typeof fetch;
  try {
    const result = await register(
      "student1",
      "password1234",
      "TEEECHR-7KM3-Q2WY-9NFX-P8TR",
    );
    assert.equal(result.ok, true);
    assert.deepEqual(JSON.parse(String(calls[0].init?.body)), {
      username: "student1",
      password: "password1234",
      invite_code: "TEEECHR-7KM3-Q2WY-9NFX-P8TR",
    });
    assert.equal(changed, 1);
  } finally {
    globalThis.fetch = priorFetch;
    (globalThis as any).window = priorWindow;
  }
});

test("enrollment admin calls use CAS revisions and never put code in a URL", async () => {
  const priorFetch = globalThis.fetch;
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  globalThis.fetch = (async (url: string | URL | Request, init?: RequestInit) => {
    calls.push({ url: String(url), init });
    if (init?.method === "POST") {
      return response({
        code: "TEEECHR-7KM3-Q2WY-9NFX-P8TR",
        enrollment: { revision: 5 },
      });
    }
    return response({ revision: 4, state: "disabled" });
  }) as typeof fetch;
  try {
    await fetchEnrollment();
    await rotateEnrollmentCode(4);
    await setEnrollmentEnabled(false, 5);
    assert.deepEqual(calls.map((call) => call.url), [
      "/api/v1/auth/enrollment",
      "/api/v1/auth/enrollment/code",
      "/api/v1/auth/enrollment/enabled",
    ]);
    assert.deepEqual(JSON.parse(String(calls[1].init?.body)), {
      expected_revision: 4,
    });
    assert.deepEqual(JSON.parse(String(calls[2].init?.body)), {
      enabled: false,
      expected_revision: 5,
    });
  } finally {
    globalThis.fetch = priorFetch;
  }
});
