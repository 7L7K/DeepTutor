import {
  expect,
  test,
  type BrowserContext,
  type Page,
  type Request,
} from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import { ADMIN_ONLY_ROUTE_PREFIXES } from "../../lib/capability-routes";

const adminUsername = process.env.D2_ADMIN_USERNAME;
const adminPassword = process.env.D2_ADMIN_PASSWORD;
const learnerUsername = process.env.D2_LEARNER_USERNAME;
const learnerPassword = process.env.D2_LEARNER_PASSWORD;
const evidenceDir = process.env.D2_EVIDENCE_DIR;
const harnessEnabled = process.env.D2_HARNESS === "1";

// Mirror the admin-only settings policy in settings-nav. Importing that module
// into the standalone Playwright node loader would also load browser aliases,
// so this deliberately enumerates the policy-owned category/leaf URLs.
const ADMIN_ONLY_SETTINGS_ROUTES = [
  "/settings/mineru",
  "/settings/network",
  "/settings/models",
  "/settings/llm",
  "/settings/embedding",
  "/settings/search",
  "/settings/tts",
  "/settings/stt",
  "/settings/image",
  "/settings/video",
  "/settings/document-parsing",
  "/settings/capabilities",
  "/settings/attachments",
  "/settings/agents",
  "/settings/agents/claude-code",
  "/settings/agents/codex",
  "/settings/agents/gemini",
  "/settings/agents/kimi",
  "/settings/agents/opencode",
  "/settings/agents/mimo",
  "/settings/memory",
] as const;

const LEARNER_SAFE_SETTINGS_ALIASES = [
  { route: "/settings/mcp", redirect: "/space/mcp" },
] as const;

const LEARNER_SAFE_PAGE_API_PATHS = new Set([
  "/api/v1/auth/status",
  "/api/v1/auth/is_first_user",
  "/api/v1/auth/login",
  "/api/v1/auth/logout",
  "/api/v1/courses",
  "/api/v1/sessions",
  "/api/v1/settings",
  "/api/v1/settings/chat-attachments",
  "/api/v1/settings/llm-options",
  "/api/v1/system/status",
  "/api/v1/space/mcp/servers",
  "/api/v1/knowledge/list",
  "/api/v1/tools",
  "/api/v1/subagents/consult-settings",
  "/api/v1/subagents/partners",
  "/api/v1/subagents/connections",
]);

const LEARNER_FORBIDDEN_PAGE_API_PATHS = [
  /^\/api\/v1\/subagents\/(?:settings|options|backends\/options)(?:\/|$)/,
  /^\/api\/v1\/subagents\/partners\/.+/,
  /^\/api\/v1\/auth\/users(?:\/|$)/,
  /^\/api\/v1\/knowledge\/(?:connected|connector|config|linked)(?:\/|$)/,
  /^\/api\/v1\/(?:memory|co-writer|book|space\/cli-apps)(?:\/|$)/,
  /^\/api\/v1\/settings\/(?:catalog|apply|mcp|mineru|network|providers|agents)(?:\/|$)/,
];

type AuthProjection = {
  enabled: boolean;
  authenticated: boolean;
  username: string | null;
  role: string | null;
  is_admin: boolean;
};

type RequestRecord = {
  phase: string;
  method: string;
  path: string;
  status?: number;
  failure?: string;
  consultBudget?: unknown;
};

type BrowserEvidence = {
  requests: RequestRecord[];
  console: Array<{ type: string; text: string }>;
  pageErrors: string[];
  protectedRouteResults: Array<{
    route: string;
    finalPath: string;
    gated: boolean;
  }>;
  explicitChecks: Array<{ phase: string; method: string; path: string; status: number }>;
  authProjections: Array<{
    phase: string;
    status: number;
    body: AuthProjection;
  }>;
};

function requireFixture() {
  if (
    !adminUsername ||
    !adminPassword ||
    !learnerUsername ||
    !learnerPassword ||
    !evidenceDir ||
    !harnessEnabled
  ) {
    throw new Error(
      "D2 harness fixtures are required; run scripts/test-day2-learner-admin.",
    );
  }
}

async function signIn(
  page: Page,
  username: string,
  password: string,
  nextPath: string,
) {
  const authReady = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/api/v1/auth/status" &&
      response.request().method() === "GET",
  );
  await page.goto(`/login?next=${encodeURIComponent(nextPath)}`);
  expect((await authReady).status()).toBe(200);
  await page.getByLabel("Email or username").fill(username);
  await page.getByRole("textbox", { name: "Password", exact: true }).fill(password);
  const loginResponse = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/api/v1/auth/login" &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  expect((await loginResponse).status()).toBe(200);
  await page.waitForURL((url) => url.pathname === nextPath);
}

async function signOut(page: Page) {
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login(?:\?|$)/);
}

async function settleShell(page: Page) {
  await page.waitForLoadState("domcontentloaded");
  // Let the shell's auth, settings, session, and navigation probes finish
  // before the next route change. A route transition is not an application
  // error, but it must not hide one by aborting the in-flight probes.
  await page.waitForTimeout(600);
}

function endpoint(url: string): string {
  return new URL(url).pathname;
}

async function readAuthProjection(page: Page): Promise<{
  status: number;
  body: AuthProjection;
}> {
  const response = await page.context().request.get(
    new URL("/api/v1/auth/status", page.url()).toString(),
  );
  const payload = (await response.json()) as Partial<AuthProjection>;
  return {
    status: response.status(),
    body: {
      enabled: Boolean(payload.enabled),
      authenticated: Boolean(payload.authenticated),
      username: payload.username ?? null,
      role: payload.role ?? null,
      is_admin: Boolean(payload.is_admin),
    },
  };
}

function attachDiagnostics(
  page: Page,
  evidence: BrowserEvidence,
  responseTasks: Promise<void>[],
  phase: () => string,
) {
  const requestPhases = new WeakMap<Request, string>();
  page.on("request", (request) => {
    const requestPhase = phase();
    requestPhases.set(request, requestPhase);
    const path = endpoint(request.url());
    if (path.startsWith("/api/")) {
      evidence.requests.push({ phase: requestPhase, method: request.method(), path });
    }
  });
  page.on("response", (response) => {
    const path = endpoint(response.url());
    if (!path.startsWith("/api/")) return;
    const item: RequestRecord = {
      phase: requestPhases.get(response.request()) ?? phase(),
      method: response.request().method(),
      path,
      status: response.status(),
    };
    evidence.requests.push(item);
    if (path === "/api/v1/subagents/consult-settings") {
      responseTasks.push(
        response
          .json()
          .then((body) => {
            item.consultBudget = body;
          })
          .catch(() => undefined),
      );
    }
  });
  page.on("requestfailed", (request) => {
    const path = endpoint(request.url());
    if (path.startsWith("/api/")) {
      evidence.requests.push({
        phase: requestPhases.get(request) ?? phase(),
        method: request.method(),
        path,
        failure: request.failure()?.errorText ?? "unknown request failure",
      });
    }
  });
  page.on("console", (message) => {
    if (message.type() === "warning" || message.type() === "error") {
      evidence.console.push({ type: message.type(), text: message.text() });
    }
  });
  page.on("pageerror", (error) => evidence.pageErrors.push(error.message));
}

async function openSameSessionPage(
  context: BrowserContext,
  route: string,
  evidence: BrowserEvidence,
  responseTasks: Promise<void>[],
  phase: string,
) {
  const routePage = await context.newPage();
  attachDiagnostics(routePage, evidence, responseTasks, () => phase);
  await routePage.goto(route);
  await settleShell(routePage);
  return routePage;
}

test("Day 2 learner shell and authorization boundary", async ({
  page,
}) => {
  test.setTimeout(120_000);
  requireFixture();

  const evidence: BrowserEvidence = {
    requests: [],
    console: [],
    pageErrors: [],
    protectedRouteResults: [],
    explicitChecks: [],
    authProjections: [],
  };
  const responseTasks: Promise<void>[] = [];
  let phase = "learner_login";
  const persistEvidence = () => {
    mkdirSync(evidenceDir!, { recursive: true, mode: 0o700 });
    writeFileSync(
      join(evidenceDir!, "day2-learner-admin-browser.json"),
      `${JSON.stringify(evidence, null, 2)}\n`,
      { mode: 0o600 },
    );
  };

  attachDiagnostics(page, evidence, responseTasks, () => phase);

  try {
    phase = "learner_shell";
    await signIn(page, learnerUsername!, learnerPassword!, "/home");
    await settleShell(page);
    await expect(page).toHaveURL(/\/home(?:\?|$)/);
    await expect(
      page.getByRole("heading", { name: "General Study", exact: true }),
    ).toBeVisible();
    const learnerAfterLogin = await readAuthProjection(page);
    evidence.authProjections.push({ phase: "learner_after_login", ...learnerAfterLogin });
    expect(learnerAfterLogin).toEqual({
      status: 200,
      body: {
        enabled: true,
        authenticated: true,
        username: learnerUsername,
        role: "user",
        is_admin: false,
      },
    });
    await page.getByRole("button", { name: "More", exact: true }).click();
    const partnersLink = page.getByRole("menuitem", {
      name: "Partners",
      exact: true,
    });
    await expect(partnersLink).toBeVisible();
    await expect(partnersLink).toHaveAttribute("href", "/partners");

    await expect
      .poll(() =>
        evidence.requests.some(
          (item) =>
            item.path === "/api/v1/subagents/consult-settings" &&
            item.method === "GET" &&
            item.status === 200,
        ),
      )
      .toBe(true);
    await Promise.allSettled(responseTasks);
    const learnerConsultResponses = evidence.requests.filter(
      (item) =>
        item.path === "/api/v1/subagents/consult-settings" &&
        item.method === "GET" &&
        item.status === 200,
    );
    expect(learnerConsultResponses.length).toBeGreaterThan(0);
    expect(learnerConsultResponses[0]?.consultBudget).toEqual({
      consult_budget: 7,
    });
    expect(
      evidence.requests.filter(
        (item) =>
          item.path === "/api/v1/subagents/settings" && item.method === "GET",
      ),
    ).toHaveLength(0);

    const learnerSettingsPath = "/api/v1/subagents/settings";
    const directLearnerSettings = await page.context().request.get(
      new URL(learnerSettingsPath, page.url()).toString(),
    );
    const learnerSettingsStatus = directLearnerSettings.status();
    // Consume the body before the next browser phase. APIResponse is not
    // independently disposable because it belongs to the shared browser
    // context request client, but reading it releases its buffered payload.
    await directLearnerSettings.body();
    evidence.explicitChecks.push({
      phase: "learner_privileged_settings",
      method: "GET",
      path: learnerSettingsPath,
      status: learnerSettingsStatus,
    });
    expect(learnerSettingsStatus).toBe(403);

    const learnerUsersPath = "/api/v1/auth/users";
    const directLearnerUsers = await page.context().request.get(
      new URL(learnerUsersPath, page.url()).toString(),
    );
    const learnerUsersStatus = directLearnerUsers.status();
    await directLearnerUsers.body();
    evidence.explicitChecks.push({
      phase: "learner_privileged_users",
      method: "GET",
      path: learnerUsersPath,
      status: learnerUsersStatus,
    });
    expect(learnerUsersStatus).toBe(403);

    const classesPage = await openSameSessionPage(
      page.context(),
      "/classes",
      evidence,
      responseTasks,
      "learner_classes",
    );
    await expect(classesPage).toHaveURL(/\/classes$/);
    await expect(classesPage.getByRole("heading", { name: /Classes/ })).toBeVisible();
    await classesPage.close();

    const partnersPage = await openSameSessionPage(
      page.context(),
      "/partners",
      evidence,
      responseTasks,
      "learner_partners",
    );
    await expect(partnersPage).toHaveURL(/\/partners$/);
    await expect(
      partnersPage.getByRole("heading", { name: "Partners", exact: true }),
    ).toBeVisible();
    const learnerPartnerList = await partnersPage.evaluate(async () => {
      const response = await fetch("/api/v1/subagents/partners", {
        cache: "no-store",
      });
      return { status: response.status, body: await response.json() };
    });
    expect(learnerPartnerList.status).toBe(200);
    expect(learnerPartnerList.body).toEqual({ partners: [] });
    await partnersPage.close();

    const protectedRoutes: ReadonlyArray<{ route: string; redirect: string }> = [
      ...ADMIN_ONLY_ROUTE_PREFIXES.map((route) => ({ route, redirect: "/home" })),
      ...ADMIN_ONLY_SETTINGS_ROUTES.map((route) => ({ route, redirect: "/home" })),
      { route: "/partners/new", redirect: "/home" },
      { route: "/partners/new/", redirect: "/home" },
      { route: "/partners/day2-unassigned-partner", redirect: "/home" },
      { route: "/partners/day2-unassigned-partner/", redirect: "/home" },
      { route: "/admin/users", redirect: "/classes" },
      { route: "/settings/agents/codex", redirect: "/home" },
    ];
    for (const { route, redirect } of protectedRoutes) {
      const protectedPage = await openSameSessionPage(
        page.context(),
        route,
        evidence,
        responseTasks,
        `learner_protected_${route.replaceAll("/", "_").slice(1)}`,
      );
      await expect
        .poll(() => new URL(protectedPage.url()).pathname)
        .toBe(redirect);
      const finalPath = new URL(protectedPage.url()).pathname;
      evidence.protectedRouteResults.push({ route, finalPath, gated: true });
      expect(finalPath).toBe(redirect);
      await protectedPage.close();
    }

    for (const { route, redirect } of LEARNER_SAFE_SETTINGS_ALIASES) {
      const aliasPage = await openSameSessionPage(
        page.context(),
        route,
        evidence,
        responseTasks,
        `learner_safe_alias_${route.replaceAll("/", "_").slice(1)}`,
      );
      await expect.poll(() => new URL(aliasPage.url()).pathname).toBe(redirect);
      if (route === "/settings/mcp") {
        await expect
          .poll(() =>
            evidence.requests.some(
              (item) =>
                item.phase === "learner_safe_alias_settings_mcp" &&
                item.method === "GET" &&
                item.path === "/api/v1/space/mcp/servers" &&
                item.status === 200,
            ),
          )
          .toBe(true);
      }
      await aliasPage.close();
    }

    expect(
      evidence.requests.filter((item) =>
        /^\/api\/v1\/subagents\/partners\/.+/.test(item.path),
      ),
    ).toEqual([]);
    const learnerAfterRedirects = await readAuthProjection(page);
    evidence.authProjections.push({
      phase: "learner_after_protected_redirects",
      ...learnerAfterRedirects,
    });
    expect(learnerAfterRedirects).toEqual({
      status: 200,
      body: {
        enabled: true,
        authenticated: true,
        username: learnerUsername,
        role: "user",
        is_admin: false,
      },
    });

    phase = "learner_sign_out";
    await signOut(page);
    await settleShell(page);
    phase = "admin_home";
    await signIn(page, adminUsername!, adminPassword!, "/home");
    await settleShell(page);

    await expect(page).toHaveURL(/\/home(?:\?|$)/);
    await expect(
      page.getByRole("heading", { name: "General Study", exact: true }),
    ).toBeVisible();
    const adminAfterLogin = await readAuthProjection(page);
    evidence.authProjections.push({ phase: "admin_after_login", ...adminAfterLogin });
    expect(adminAfterLogin).toEqual({
      status: 200,
      body: {
        enabled: true,
        authenticated: true,
        username: adminUsername,
        role: "admin",
        is_admin: true,
      },
    });

    const adminUsersPath = "/api/v1/auth/users";
    const directAdminUsers = await page.context().request.get(
      new URL(adminUsersPath, page.url()).toString(),
    );
    const adminUsersStatus = directAdminUsers.status();
    const adminUsers = (await directAdminUsers.json()) as Array<{
      username?: string;
      role?: string;
    }>;
    evidence.explicitChecks.push({
      phase: "admin_privileged_users",
      method: "GET",
      path: adminUsersPath,
      status: adminUsersStatus,
    });
    expect(adminUsersStatus).toBe(200);
    expect(adminUsers).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ username: adminUsername, role: "admin" }),
        expect.objectContaining({ username: learnerUsername, role: "user" }),
      ]),
    );

    phase = "admin_privileged_api";
    const adminProjection = await page.evaluate(async () => {
      const [settings, consult] = await Promise.all([
        fetch("/api/v1/subagents/settings", { cache: "no-store" }),
        fetch("/api/v1/subagents/consult-settings", { cache: "no-store" }),
      ]);
      return {
        settingsStatus: settings.status,
        consultStatus: consult.status,
        consult: await consult.json(),
      };
    });
    expect(adminProjection).toEqual({
      settingsStatus: 200,
      consultStatus: 200,
      consult: { consult_budget: 7 },
    });
    expect(
      evidence.requests.filter((item) =>
        /^\/api\/v1\/subagents\/(?:options|backends\/options)(?:\/|$)/.test(item.path),
      ),
    ).toEqual([]);

    await Promise.allSettled(responseTasks);
    const learnerPageRequests = evidence.requests.filter((item) =>
      item.phase.startsWith("learner_"),
    );
    expect(learnerPageRequests.length).toBeGreaterThan(0);
    expect(
      learnerPageRequests.every((item) => LEARNER_SAFE_PAGE_API_PATHS.has(item.path)),
    ).toBe(true);
    expect(
      learnerPageRequests.filter((item) =>
        LEARNER_FORBIDDEN_PAGE_API_PATHS.some((pattern) => pattern.test(item.path)),
      ),
    ).toEqual([]);
    const unexpectedAuthOrRuntime = evidence.requests.filter(
      (item) =>
        Boolean(item.failure) ||
        (item.status !== undefined && item.status >= 500) ||
        item.status === 401 ||
        item.status === 403,
    );
    expect(unexpectedAuthOrRuntime).toEqual([]);
    expect(evidence.pageErrors).toEqual([]);
    expect(evidence.console.filter((item) => item.type === "error")).toEqual([]);
  } finally {
    persistEvidence();
  }
});
