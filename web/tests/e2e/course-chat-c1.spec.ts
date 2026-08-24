import { expect, test, type Locator, type Page } from "@playwright/test";
import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const alicePassword = process.env.C1_ALICE_PASSWORD;
const bobPassword = process.env.C1_BOB_PASSWORD;
const carolPassword = process.env.C1_CAROL_PASSWORD;
const fixtureFile = process.env.C1_FIXTURE_FILE;
const browserStateFile = process.env.C1_BROWSER_STATE_FILE;
const evidenceDir = process.env.C1_EVIDENCE_DIR;

interface C1Fixture {
  alice_identity: string;
  alice_course_id: string;
  alice_no_ready_course_id: string;
  alice_ready_source_id: string;
  alice_ready_source_title: string;
  psychology_course_id: string;
  psychology_ready_source_id: string;
  psychology_ready_source_title: string;
  processing_only_course_id: string;
  failed_only_course_id: string;
  unsupported_course_id: string;
  unsupported_ready_source_id: string;
  provider_unavailable_course_id: string;
  bob_identity: string;
  bob_course_id: string;
  carol_identity: string;
}

interface C1BrowserState {
  sessionId: string;
  sessionUrl: string;
  psychologySessionId: string;
  psychologySessionUrl: string;
  providerUnavailableSessionId?: string;
  classesLandingCourseListCalls: number;
  totalCourseListCalls: number;
}

function fixture(): C1Fixture {
  if (!fixtureFile) throw new Error("C1_FIXTURE_FILE is required");
  return JSON.parse(readFileSync(fixtureFile, "utf8")) as C1Fixture;
}

async function signIn(page: Page, username: string, password: string) {
  const authReady = page.waitForResponse(
    (response) =>
      response.url().includes("/api/v1/auth/status") &&
      response.request().method() === "GET",
  );
  await page.goto("/login");
  expect((await authReady).status()).toBe(200);
  await page.getByLabel("Email or username").fill(username);
  await page.getByRole("textbox", { name: "Password", exact: true }).fill(password);
  const loginResponse = page.waitForResponse(
    (response) =>
      response.url().includes("/api/v1/auth/login") &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  expect((await loginResponse).status()).toBe(200);
  await page.waitForURL((url) => !url.pathname.startsWith("/login"));
}

async function signOut(page: Page) {
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login(?:\?|$)/);
}

async function tabTo(page: Page, locator: Locator, attempts = 100) {
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    await page.keyboard.press("Tab");
    if (await locator.evaluate((element) => element === document.activeElement)) {
      return;
    }
  }
  throw new Error(`Keyboard focus did not reach ${await locator.getAttribute("data-testid")}`);
}

type CapabilityProbeFixture = {
  failSettings: boolean;
  settingsDelayMs: number;
  settingsCalls: number;
};

async function mockCapabilityProbeShell(
  page: Page,
  probe: CapabilityProbeFixture,
) {
  await page.route("**/api/**", async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    const fulfill = (body: unknown, status = 200) =>
      route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(body),
      });

    if (pathname === "/api/v1/settings") {
      probe.settingsCalls += 1;
      if (probe.settingsDelayMs) {
        await new Promise((resolve) => setTimeout(resolve, probe.settingsDelayMs));
      }
      return probe.failSettings
        ? fulfill({ detail: "probe unavailable" }, 503)
        : fulfill({});
    }
    if (pathname === "/api/v1/settings/llm-options") {
      return fulfill({
        active: { profile_id: "school", model_id: "test-model" },
        options: [
          {
            profile_id: "school",
            model_id: "test-model",
            profile_name: "School",
            model_name: "Test model",
            model: "test-model",
            provider: "local",
            is_active_default: true,
          },
        ],
      });
    }
    if (pathname === "/api/v1/courses") {
      return fulfill({
        courses: [],
        capabilities: {
          grounded_generation: false,
          practice_generation: false,
          flashcard_generation: false,
          flashcard_generation_reason: null,
          grounded_generation_reason: null,
        },
      });
    }
    if (pathname === "/api/v1/sessions") return fulfill({ sessions: [] });
    if (pathname === "/api/v1/knowledge/list") {
      return fulfill({ knowledge_bases: [] });
    }
    if (pathname === "/api/v1/tools") {
      return fulfill({ enabled_optional_tools: [] });
    }
    if (pathname === "/api/v1/subagents/partners") {
      return fulfill({ partners: [] });
    }
    if (pathname === "/api/v1/subagents/connections") {
      return fulfill({ connections: [] });
    }
    if (pathname === "/api/v1/subagents/consult-settings") {
      return fulfill({ consult_budget: 1 });
    }
    if (pathname === "/api/v1/settings/chat-attachments") {
      return fulfill({
        effective: { max_file_bytes: 1024, max_total_bytes: 4096 },
      });
    }
    if (pathname === "/api/v1/auth/status" || pathname === "/api/v1/auth/login") {
      return route.continue();
    }
    return fulfill({});
  });
}

test("initial capability probe failure renders Retry instead of a missing-grant notice", async ({
  page,
}) => {
  test.skip(!alicePassword, "Run through scripts/test-course-chat-c1 with disposable fixtures.");
  const probe: CapabilityProbeFixture = {
    failSettings: true,
    settingsDelayMs: 0,
    settingsCalls: 0,
  };
  await mockCapabilityProbeShell(page, probe);
  await signIn(page, "c1_alice", alicePassword!);

  await page.goto("/home");
  const failure = page.getByRole("alert").filter({
    hasText: "Feature access could not be verified",
  });
  await expect(failure).toBeVisible();
  await expect(
    page.getByText(/Chat and regeneration require an assigned LLM model/),
  ).toHaveCount(0);

  probe.failSettings = false;
  await failure.getByRole("button", { name: "Retry" }).click();
  await expect(page.locator("textarea").last()).toBeVisible();
  expect(probe.settingsCalls).toBeGreaterThanOrEqual(2);
});

test("failed focus refresh preserves the mounted composer draft and Retry recovers", async ({
  page,
}) => {
  test.skip(!alicePassword, "Run through scripts/test-course-chat-c1 with disposable fixtures.");
  const probe: CapabilityProbeFixture = {
    failSettings: false,
    settingsDelayMs: 0,
    settingsCalls: 0,
  };
  await mockCapabilityProbeShell(page, probe);
  await signIn(page, "c1_alice", alicePassword!);
  await page.goto("/home");

  const composer = page.locator("textarea").last();
  await expect(composer).toBeVisible();
  await composer.fill("Keep this unsent school draft");

  probe.failSettings = true;
  probe.settingsDelayMs = 250;
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await page.waitForTimeout(75);
  await expect(composer).toBeVisible();
  await expect(composer).toHaveValue("Keep this unsent school draft");

  const failure = page.getByRole("alert").filter({
    hasText: "Feature access could not be verified",
  });
  await expect(failure).toBeVisible();
  await expect(composer).toHaveValue("Keep this unsent school draft");

  probe.failSettings = false;
  probe.settingsDelayMs = 150;
  await failure.getByRole("button", { name: "Retry" }).click();
  await expect(composer).toBeVisible();
  await expect(composer).toHaveValue("Keep this unsent school draft");
  await expect(failure).toHaveCount(0);
  await expect(composer).toHaveValue("Keep this unsent school draft");
});

test("Alice opens exact Course Chat, persists its citation, and reopens it", async ({
  page,
}) => {
  test.skip(
    !alicePassword || !browserStateFile || !evidenceDir,
    "Run through scripts/test-course-chat-c1 with disposable fixtures.",
  );
  const proof = fixture();
  await signIn(page, "c1_alice", alicePassword!);

  let courseListCalls = 0;
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (
      request.method() === "GET" &&
      url.pathname === "/api/v1/courses"
    ) {
      courseListCalls += 1;
    }
  });
  await page.goto("/classes");
  await expect(page.getByRole("heading", { name: "Biology 101" })).toBeVisible();
  await expect(
    page
      .getByTestId(`course-card-${proof.alice_course_id}`)
      .getByText("Fall 2026", { exact: true }),
  ).toBeVisible();
  const classesLandingCourseListCalls = courseListCalls;
  expect(classesLandingCourseListCalls).toBeLessThanOrEqual(1);

  await page.goto(`/classes/${encodeURIComponent(proof.alice_course_id)}`);
  await expect(page.getByRole("heading", { name: "Biology 101" })).toBeVisible();
  await expect(page.getByText("Fall 2026", { exact: true })).toBeVisible();
  await expect(page.getByTestId("course-overview-dashboard")).toBeVisible();
  await expect(page.getByTestId("course-chat-link")).toHaveCount(0);
  await page.screenshot({
    path: join(evidenceDir!, "screenshots", "course-overview-desktop.png"),
    fullPage: true,
  });

  const chatLink = page.getByRole("link", { name: "Chat", exact: true });
  await tabTo(page, chatLink);
  await expect(chatLink).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(
    new RegExp(`/classes/${proof.alice_course_id}/chat$`),
  );
  await expect(page.getByTestId("course-chat-route")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Biology 101" })).toBeVisible();
  await expect(page.getByText("Fall 2026", { exact: true })).toBeVisible();
  await expect(
    page.getByText(/Two other materials are not currently available/),
  ).toBeVisible();

  const composer = page.locator("textarea").last();
  await tabTo(page, composer);
  await expect(composer).toBeFocused();
  await page.keyboard.type("What molecule stores usable cellular energy?");
  await page.keyboard.press("Enter");
  await expect(
    page.getByText(/Deterministic course answer: ATP stores usable cellular energy/),
  ).toBeVisible({ timeout: 30_000 });
  await expect(page).toHaveURL(
    new RegExp(`/classes/${proof.alice_course_id}/chat/[^/]+$`),
  );
  const sessionUrl = new URL(page.url()).pathname;
  const sessionId = decodeURIComponent(sessionUrl.split("/").at(-1) || "");
  expect(sessionId).not.toBe("");

  await expect(page.getByTestId("course-citations")).toBeVisible();
  await expect(
    page.getByTestId(`course-citation-${proof.alice_ready_source_id}`),
  ).toContainText(proof.alice_ready_source_title);
  await expect(page.getByText("biology-private-source.txt")).toHaveCount(0);
  await expect(page.getByText(/^personal:kb:course_/)).toHaveCount(0);

  const persisted = await page.evaluate(async (id) => {
    const response = await fetch(`/api/v1/sessions/${encodeURIComponent(id)}`, {
      cache: "no-store",
    });
    return { status: response.status, body: await response.json() };
  }, sessionId);
  expect(persisted.status).toBe(200);
  expect(persisted.body.course_id).toBe(proof.alice_course_id);
  expect(JSON.stringify(persisted.body)).not.toContain("biology-private-source.txt");
  expect(JSON.stringify(persisted.body)).toContain(proof.alice_ready_source_id);

  await page.screenshot({
    path: join(evidenceDir!, "screenshots", "course-chat-grounded-desktop.png"),
    fullPage: true,
  });
  await page.reload();
  await expect(page.getByRole("heading", { name: "Biology 101" })).toBeVisible();
  await expect(
    page.getByText(/Deterministic course answer: ATP stores usable cellular energy/),
  ).toBeVisible();
  await expect(
    page.getByTestId(`course-citation-${proof.alice_ready_source_id}`),
  ).toBeVisible();

  await page.getByRole("link", { name: "Overview", exact: true }).click();
  await expect(page).toHaveURL(
    new RegExp(`/classes/${proof.alice_course_id}$`),
  );
  await page.goto(sessionUrl);
  await expect(
    page.getByText(/Deterministic course answer: ATP stores usable cellular energy/),
  ).toBeVisible();

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("button", { name: "Open navigation" })).toBeVisible();
  const mobileSidebar = page.locator("aside").first();
  await expect
    .poll(async () => (await mobileSidebar.boundingBox())?.x ?? 0)
    .toBeLessThanOrEqual(-219);
  const mobileHeading = page.getByRole("heading", { name: "Biology 101" });
  const mobileCitations = page.getByTestId("course-citations");
  for (const element of [mobileHeading, mobileCitations, composer]) {
    await expect(element).toBeVisible();
    const bounds = await element.boundingBox();
    expect(bounds).not.toBeNull();
    expect(bounds!.x).toBeGreaterThanOrEqual(0);
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(390);
  }
  await page.screenshot({
    path: join(evidenceDir!, "screenshots", "course-chat-grounded-mobile.png"),
    fullPage: true,
  });

  await page.setViewportSize({ width: 1280, height: 720 });
  await page.goto(
    `/classes/${encodeURIComponent(proof.psychology_course_id)}/chat/${encodeURIComponent(sessionId)}`,
  );
  await expect(
    page.getByText(
      "Course Chat was not found or is not available to this account.",
      { exact: true },
    ),
  ).toBeVisible();
  await page.screenshot({
    path: join(evidenceDir!, "screenshots", "course-chat-session-mismatch.png"),
    fullPage: true,
  });

  await page.goto(
    `/classes/${encodeURIComponent(proof.psychology_course_id)}/chat`,
  );
  await expect(page.getByRole("heading", { name: "Psychology 201" })).toBeVisible();
  const psychologyComposer = page.locator("textarea").last();
  await psychologyComposer.fill("What does working memory do?");
  await psychologyComposer.press("Enter");
  await expect(
    page.getByText(
      /Deterministic course answer: Working memory temporarily holds information/,
    ),
  ).toBeVisible({ timeout: 30_000 });
  await expect(
    page.getByTestId(`course-citation-${proof.psychology_ready_source_id}`),
  ).toContainText(proof.psychology_ready_source_title);
  await expect(
    page.getByTestId(`course-citation-${proof.alice_ready_source_id}`),
  ).toHaveCount(0);
  await expect(page.getByText(/ATP stores usable cellular energy/)).toHaveCount(0);
  const psychologySessionUrl = new URL(page.url()).pathname;
  const psychologySessionId = decodeURIComponent(
    psychologySessionUrl.split("/").at(-1) || "",
  );
  expect(psychologySessionId).not.toBe("");
  await page.screenshot({
    path: join(evidenceDir!, "screenshots", "course-chat-psychology-grounded.png"),
    fullPage: true,
  });

  writeFileSync(
    browserStateFile!,
    JSON.stringify({
      sessionId,
      sessionUrl,
      psychologySessionId,
      psychologySessionUrl,
      classesLandingCourseListCalls,
      totalCourseListCalls: courseListCalls,
    } satisfies C1BrowserState),
    { encoding: "utf8", mode: 0o600 },
  );
});

test("unsupported and provider-unavailable turns fail truthfully", async ({ page }) => {
  test.skip(
    !alicePassword || !browserStateFile || !evidenceDir,
    "Run through scripts/test-course-chat-c1 with disposable fixtures.",
  );
  const proof = fixture();
  const terminalFramesPath = join(
    evidenceDir!,
    "backend",
    "provider-unavailable-terminal-frames.ndjson",
  );
  const terminalFrames: Array<{
    type?: string;
    content?: string;
    metadata?: Record<string, unknown>;
    session_id?: string;
    turn_id?: string;
    seq?: number;
  }> = [];
  page.on("websocket", (socket) => {
    socket.on("framereceived", ({ payload }) => {
      if (typeof payload !== "string") return;
      try {
        const event = JSON.parse(payload) as {
          type?: string;
          content?: string;
          metadata?: Record<string, unknown>;
          session_id?: string;
          turn_id?: string;
          seq?: number;
        };
        if (!["session", "error", "done"].includes(event.type || "")) return;
        terminalFrames.push(event);
      } catch {
        // Non-JSON heartbeat or development traffic is not proof evidence.
      }
    });
  });
  await signIn(page, "c1_alice", alicePassword!);

  await page.goto(
    `/classes/${encodeURIComponent(proof.unsupported_course_id)}/chat`,
  );
  const unsupportedComposer = page.locator("textarea").last();
  await unsupportedComposer.fill("What is the answer outside these materials?");
  await unsupportedComposer.press("Enter");
  await expect(
    page.getByText(
      "I could not find support for that answer in the available Course materials.",
      { exact: true },
    ),
  ).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("course-citations")).toHaveCount(0);
  await page.screenshot({
    path: join(evidenceDir!, "screenshots", "course-chat-unsupported.png"),
    fullPage: true,
  });

  await page.goto(
    `/classes/${encodeURIComponent(proof.provider_unavailable_course_id)}/chat`,
  );
  const unavailableComposer = page.locator("textarea").last();
  await unavailableComposer.fill("Can the Course provider answer?");
  await unavailableComposer.press("Enter");
  await expect(
    page.getByText("Deterministic provider unavailable for C1 proof", {
      exact: true,
    }),
  ).toBeVisible({ timeout: 30_000 });
  await expect(page).toHaveURL(
    new RegExp(`/classes/${proof.provider_unavailable_course_id}/chat/[^/]+$`),
  );
  const providerUnavailableSessionId = decodeURIComponent(
    new URL(page.url()).pathname.split("/").at(-1) || "",
  );
  const browserState = JSON.parse(
    readFileSync(browserStateFile!, "utf8"),
  ) as C1BrowserState;
  writeFileSync(
    browserStateFile!,
    JSON.stringify({ ...browserState, providerUnavailableSessionId }),
  );
  writeFileSync(
    terminalFramesPath,
    `${terminalFrames
      .filter((event) => event.session_id === providerUnavailableSessionId)
      .map((event) => JSON.stringify(event))
      .join("\n")}\n`,
  );
  await page.screenshot({
    path: join(evidenceDir!, "screenshots", "course-chat-provider-unavailable.png"),
    fullPage: true,
  });
});

test("Bob cannot open Alice Course or Course session URLs", async ({ page }) => {
  test.skip(
    !bobPassword || !browserStateFile || !evidenceDir,
    "Run through scripts/test-course-chat-c1 with disposable fixtures.",
  );
  const proof = fixture();
  const state = JSON.parse(
    readFileSync(browserStateFile!, "utf8"),
  ) as C1BrowserState;
  await signIn(page, "c1_bob", bobPassword!);

  await page.goto(`/classes/${encodeURIComponent(proof.alice_course_id)}/chat`);
  const denial = page.getByText(
    "Course resource not found",
    { exact: true },
  );
  await expect(denial).toBeVisible();
  await expect(page.getByText(proof.alice_ready_source_title)).toHaveCount(0);

  await page.goto(state.sessionUrl);
  await expect(denial).toBeVisible();
  const denied = await page.evaluate(async (id) => {
    const response = await fetch(`/api/v1/sessions/${encodeURIComponent(id)}`, {
      cache: "no-store",
    });
    return response.status;
  }, state.sessionId);
  expect(denied).toBe(404);
  await expect(page.getByText("Biology 101", { exact: true })).toHaveCount(0);
  await page.screenshot({
    path: join(evidenceDir!, "screenshots", "course-chat-foreign-denied.png"),
    fullPage: true,
  });

  await page.goto(`/classes/${encodeURIComponent(proof.bob_course_id)}`);
  await expect(page.getByRole("heading", { name: "Bob Private Chemistry" })).toBeVisible();
});

test("zero-ready and zero-Course states stay truthful without a Chat session", async ({
  page,
}) => {
  test.skip(
    !alicePassword || !carolPassword || !evidenceDir,
    "Run through scripts/test-course-chat-c1 with disposable fixtures.",
  );
  const proof = fixture();
  await signIn(page, "c1_alice", alicePassword!);
  await page.goto(
    `/classes/${encodeURIComponent(proof.alice_no_ready_course_id)}/chat`,
  );
  await expect(page.getByTestId("course-chat-readiness-banner")).toBeVisible();
  await expect(page.getByTestId("course-chat-readiness-banner")).toContainText(
    "This Course has no materials yet.",
  );
  await expect(page.getByRole("link", { name: "Add materials" })).toBeVisible();
  await expect(page.getByTestId("course-chat-route")).toBeVisible();
  await page.screenshot({
    path: join(evidenceDir!, "screenshots", "course-chat-zero-ready.png"),
    fullPage: true,
  });

  const processingUpload = await page.evaluate(async (courseId) => {
    const body = new FormData();
    body.append(
      "files",
      new File(["Processing-state proof source."], "processing-proof.txt", {
        type: "text/plain",
      }),
    );
    body.append("kind", "notes");
    body.append("display_name", "Processing proof notes.txt");
    const response = await fetch(
      `/api/v1/courses/${encodeURIComponent(courseId)}/sources`,
      {
        method: "POST",
        headers: { "Idempotency-Key": "c1-processing-runtime-proof" },
        body,
      },
    );
    return { status: response.status, body: await response.json() };
  }, proof.processing_only_course_id);
  expect(processingUpload.status).toBe(202);
  expect(processingUpload.body.state).toBe("processing");

  await page.goto(
    `/classes/${encodeURIComponent(proof.processing_only_course_id)}/chat`,
  );
  await expect(
    page.getByTestId("course-chat-readiness-banner"),
  ).toBeVisible();
  await expect(page.getByTestId("course-chat-readiness-banner")).toContainText(
    "Course materials are still processing.",
  );
  await expect(page.getByTestId("course-chat-route")).toBeVisible();
  await page.screenshot({
    path: join(evidenceDir!, "screenshots", "course-chat-processing-only.png"),
    fullPage: true,
  });

  await page.goto(
    `/classes/${encodeURIComponent(proof.failed_only_course_id)}/chat`,
  );
  await expect(page.getByTestId("course-chat-readiness-banner")).toBeVisible();
  await expect(page.getByTestId("course-chat-readiness-banner")).toContainText(
    "Course materials could not be prepared for Chat.",
  );
  await expect(page.getByTestId("course-chat-route")).toBeVisible();
  await page.screenshot({
    path: join(evidenceDir!, "screenshots", "course-chat-failed-only.png"),
    fullPage: true,
  });

  await signOut(page);
  await signIn(page, "c1_carol", carolPassword!);
  await page.goto("/classes");
  await expect(page.getByRole("heading", { name: "No Classes yet" })).toBeVisible();
  await page.screenshot({
    path: join(evidenceDir!, "screenshots", "classes-zero-course.png"),
    fullPage: true,
  });
});
