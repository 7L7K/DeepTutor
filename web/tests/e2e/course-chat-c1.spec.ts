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
  bob_identity: string;
  bob_course_id: string;
  carol_identity: string;
}

interface C1BrowserState {
  sessionId: string;
  sessionUrl: string;
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
  await page.getByLabel("Password").fill(password);
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
  await expect(page.getByText("Fall 2026", { exact: true })).toBeVisible();
  const classesLandingCourseListCalls = courseListCalls;
  expect(classesLandingCourseListCalls).toBeLessThanOrEqual(1);

  await page.goto(`/classes/${encodeURIComponent(proof.alice_course_id)}`);
  await expect(page.getByRole("heading", { name: "Biology 101" })).toBeVisible();
  await expect(page.getByText("Term: Fall 2026", { exact: true })).toBeVisible();
  await page.screenshot({
    path: join(evidenceDir!, "screenshots", "course-overview-desktop.png"),
    fullPage: true,
  });

  const chatLink = page.getByTestId("course-chat-link");
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

  await page.getByRole("link", { name: "Back to Course" }).click();
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

  writeFileSync(
    browserStateFile!,
    JSON.stringify({
      sessionId,
      sessionUrl,
      classesLandingCourseListCalls,
      totalCourseListCalls: courseListCalls,
    } satisfies C1BrowserState),
    { encoding: "utf8", mode: 0o600 },
  );
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
    "Course Chat was not found or is not available to this account.",
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
  await expect(
    page.getByRole("heading", {
      name: "This Course does not have any materials yet.",
    }),
  ).toBeVisible();
  await expect(page.getByRole("link", { name: "Add materials" })).toBeVisible();
  await expect(page.getByTestId("course-chat-route")).toHaveCount(0);
  await page.screenshot({
    path: join(evidenceDir!, "screenshots", "course-chat-zero-ready.png"),
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
