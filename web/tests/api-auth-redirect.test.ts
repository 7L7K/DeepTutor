import test from "node:test";
import assert from "node:assert/strict";
import { normalizeAuthNext } from "../lib/auth-redirect";

// Auth state is resolved at runtime, not from a build-time env var: apiFetch's
// 401 → /login redirect is gated by a flag set via setRuntimeAuthEnabled (which
// web/lib/auth.ts → fetchAuthStatus calls once the backend reports the real
// state). The frontend uses relative paths; URL forwarding happens in proxy.ts
// at request time, reading DEEPTUTOR_API_BASE_URL set by the launcher / Docker
// entrypoint from data/user/settings.

let apiModulePromise: Promise<typeof import("../lib/api")> | null = null;

async function loadApiModule(): Promise<typeof import("../lib/api")> {
  apiModulePromise ??= import("../lib/api");
  return apiModulePromise;
}

// Install a fake `window` whose `location.href` assignment is recorded instead
// of triggering a real navigation, so we can assert whether apiFetch redirected.
function installWindow(pathname: string, search = ""): {
  redirectedTo: () => string | null;
} {
  let redirect: string | null = null;
  const location = { pathname, search, href: "" };
  Object.defineProperty(location, "href", {
    get: () => redirect ?? "",
    set: (value: string) => {
      redirect = value;
    },
    configurable: true,
  });
  (globalThis as { window?: unknown }).window = { location };
  return { redirectedTo: () => redirect };
}

function clearWindow(): void {
  delete (globalThis as { window?: unknown }).window;
}

// Replace global fetch with one that always yields the given response.
function stubFetch(response: Response): () => void {
  const original = globalThis.fetch;
  (globalThis as { fetch: typeof fetch }).fetch = async () => response;
  return () => {
    (globalThis as { fetch: typeof fetch }).fetch = original;
  };
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

// Let pending microtasks run so apiFetch's async body reaches the redirect
// branch. The call itself must NOT be awaited there: on redirect apiFetch
// returns a promise that never resolves.
function tick(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

test("apiFetch redirects to /login on 401 when auth is enabled and no opt-out", async () => {
  const { apiFetch, setRuntimeAuthEnabled } = await loadApiModule();
  setRuntimeAuthEnabled(true);
  const win = installWindow("/dashboard");
  const restore = stubFetch(jsonResponse(401, { detail: "unauthorized" }));
  try {
    // Do not await: apiFetch returns a never-resolving promise once it redirects.
    void apiFetch("http://localhost:8001/api/v1/knowledge/list");
    await tick();
    assert.equal(win.redirectedTo(), "/login?next=%2Fdashboard");
  } finally {
    restore();
    clearWindow();
  }
});

test("apiFetch does NOT redirect on 401 when auth is disabled (default)", async () => {
  // Regression guard: in the default auth-disabled deployment the runtime flag
  // is never turned on, so a stray 401 must NOT bounce the user to /login.
  const { apiFetch, setRuntimeAuthEnabled } = await loadApiModule();
  setRuntimeAuthEnabled(false);
  const win = installWindow("/dashboard");
  const restore = stubFetch(jsonResponse(401, { detail: "unauthorized" }));
  try {
    const res = await apiFetch("http://localhost:8001/api/v1/knowledge/list");
    assert.equal(res.status, 401);
    assert.equal(win.redirectedTo(), null);
  } finally {
    restore();
    clearWindow();
    setRuntimeAuthEnabled(true);
  }
});

test("apiFetch does NOT redirect on 401 when skipAuthRedirect is set", async () => {
  // Regression guard: the login endpoint returns 401 for wrong credentials, and
  // that must reach the caller as an inline error instead of reloading the page.
  const { apiFetch } = await loadApiModule();
  const win = installWindow("/login");
  const restore = stubFetch(
    jsonResponse(401, { detail: "Incorrect username or password" }),
  );
  try {
    const res = await apiFetch("http://localhost:8001/api/v1/auth/login", {
      method: "POST",
      skipAuthRedirect: true,
    });
    assert.equal(res.status, 401);
    assert.equal(win.redirectedTo(), null);
    const data = (await res.json()) as { detail?: string };
    assert.equal(data.detail, "Incorrect username or password");
  } finally {
    restore();
    clearWindow();
  }
});

test("apiFetch preserves launch query identity when recovering an expired session", async () => {
  const { apiFetch, setRuntimeAuthEnabled } = await loadApiModule();
  setRuntimeAuthEnabled(true);
  const win = installWindow(
    "/launch/blueway",
    "?external_course_id=biology-101&external_term_id=fall-2026",
  );
  const restore = stubFetch(jsonResponse(401, { detail: "unauthorized" }));
  try {
    void apiFetch("/api/v1/integrations/blueway/launch");
    await tick();
    assert.equal(
      win.redirectedTo(),
      "/login?next=%2Flaunch%2Fblueway%3Fexternal_course_id%3Dbiology-101%26external_term_id%3Dfall-2026",
    );
  } finally {
    restore();
    clearWindow();
  }
});

test("apiFetch passes successful responses through without redirecting", async () => {
  const { apiFetch } = await loadApiModule();
  const win = installWindow("/dashboard");
  const restore = stubFetch(jsonResponse(200, { ok: true }));
  try {
    const res = await apiFetch("http://localhost:8001/api/v1/auth/status");
    assert.equal(res.status, 200);
    assert.equal(win.redirectedTo(), null);
  } finally {
    restore();
    clearWindow();
  }
});

test("login continuation accepts only relative exact launch state", () => {
  assert.equal(
    normalizeAuthNext("/launch/blueway?external_course_id=biology-101&external_term_id=fall-2026"),
    "/launch/blueway?external_course_id=biology-101&external_term_id=fall-2026",
  );
  assert.equal(
    normalizeAuthNext("/launch/blueway?external_course_id=legacy-101"),
    "/launch/blueway?external_course_id=legacy-101",
  );
  assert.equal(normalizeAuthNext("https://foreign.example/steal"), "/");
  assert.equal(normalizeAuthNext("//foreign.example/steal"), "/");
  assert.equal(normalizeAuthNext("javascript:alert(1)"), "/");
  assert.equal(normalizeAuthNext("data:text/html,evil"), "/");
  assert.equal(normalizeAuthNext("file:///etc/passwd"), "/");
  assert.equal(normalizeAuthNext("/%2F%2Fforeign.example"), "/");
});

test("launch continuation rejects malformed or ambiguous query state", () => {
  assert.equal(normalizeAuthNext("/launch/blueway"), "/");
  assert.equal(normalizeAuthNext("/launch/blueway?external_course_id=   "), "/");
  assert.equal(normalizeAuthNext("/launch/blueway?external_course_id=biology&external_term_id=   "), "/");
  assert.equal(normalizeAuthNext("/launch/blueway?external_course_id=a&external_course_id=b"), "/");
  assert.equal(normalizeAuthNext("/launch/blueway?external_course_id=biology&unexpected=value"), "/");
});
