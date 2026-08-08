import { expect, test, type Page } from "@playwright/test";
import { join } from "node:path";

const userAPassword = process.env.B2_USER_A_PASSWORD;
const userBPassword = process.env.B2_USER_B_PASSWORD;
const userCPassword = process.env.B2_USER_C_PASSWORD;
const externalCourseId = process.env.B2_EXTERNAL_COURSE_ID;
const externalTermId = process.env.B2_EXTERNAL_TERM_ID;
const internalCourseId = process.env.B2_INTERNAL_COURSE_ID;
const evidenceDir = process.env.B2_EVIDENCE_DIR;

function launchPath(term = externalTermId ?? "") {
  return `/launch/blueway?external_course_id=${encodeURIComponent(externalCourseId ?? "")}&external_term_id=${encodeURIComponent(term)}`;
}

async function screenshot(page: Page, name: string) {
  if (evidenceDir) {
    await page.screenshot({ path: join(evidenceDir, `${name}.png`), fullPage: true });
  }
}

async function signIn(page: Page, username: string, password: string) {
  const authReady = page.waitForResponse(
    (response) => response.url().includes("/api/v1/auth/status") && response.request().method() === "GET",
  );
  await page.goto("/login");
  expect((await authReady).status()).toBe(200);
  await page.getByLabel("Email or username").fill(username);
  await page.getByLabel("Password").fill(password);
  const loginResponse = page.waitForResponse(
    (response) => response.url().includes("/api/v1/auth/login") && response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  expect((await loginResponse).status()).toBe(200);
  await page.waitForURL((url) => !url.pathname.startsWith("/login"));
}

async function requireFixture() {
  test.skip(
    !userAPassword || !userBPassword || !userCPassword || !externalCourseId || !externalTermId || !internalCourseId,
    "Run through scripts/test-blueway-launch-b2 so disposable fixtures are provided.",
  );
}

test("User A opens the exact BlueWay Course and preserves identity on repeat launch", async ({ page }) => {
  await requireFixture();
  await signIn(page, "b2_user_a", userAPassword!);

  let launchCalls = 0;
  let launchCacheControl: string | undefined;
  page.on("request", (request) => {
    if (request.url().includes("/api/v1/integrations/blueway/launch?")) launchCalls += 1;
  });
  page.on("response", (response) => {
    if (response.url().includes("/api/v1/integrations/blueway/launch?")) {
      launchCacheControl = response.headers()["cache-control"];
    }
  });

  await page.goto("/classes");
  await expect(page.getByRole("heading", { name: "Biology 101", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Psychology 201", exact: true })).toBeVisible();

  await page.goto(launchPath());
  await page.waitForURL(new RegExp(`/classes/${internalCourseId}$`));
  await expect(page.getByRole("heading", { name: "Biology 101", exact: true })).toBeVisible();
  await expect(page.getByText("Term: Fall 2026", { exact: true })).toBeVisible();
  expect(launchCacheControl).toBe("private, no-store");
  await screenshot(page, "user-a-exact-course-overview");

  const firstList = await page.evaluate(async () => (await (await fetch("/api/v1/courses", { cache: "no-store" })).json()).courses);
  expect(firstList.filter((course: { id: string }) => course.id === internalCourseId)).toHaveLength(1);
  expect(firstList).toHaveLength(2);

  await page.goto(launchPath());
  await page.waitForURL(new RegExp(`/classes/${internalCourseId}$`));
  await expect(page.getByRole("heading", { name: "Biology 101", exact: true })).toBeVisible();
  const secondList = await page.evaluate(async () => (await (await fetch("/api/v1/courses", { cache: "no-store" })).json()).courses);
  expect(secondList.filter((course: { id: string }) => course.id === internalCourseId)).toHaveLength(1);
  expect(secondList).toHaveLength(2);
  expect(launchCalls).toBe(2);
});

test("the unauthenticated launch keeps its exact intent through normal sign-in", async ({ page }) => {
  await requireFixture();
  await page.goto(launchPath());
  await expect(page).toHaveURL((url) => {
    const next = url.searchParams.get("next");
    if (url.pathname !== "/login" || !next) return false;
    const intended = new URL(next, url.origin);
    return intended.pathname === "/launch/blueway"
      && intended.searchParams.get("external_course_id") === externalCourseId
      && intended.searchParams.get("external_term_id") === externalTermId;
  });
  await page.getByLabel("Email or username").fill("b2_user_a");
  await page.getByLabel("Password").fill(userAPassword!);
  const loginResponse = page.waitForResponse(
    (response) => response.url().includes("/api/v1/auth/login") && response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  expect((await loginResponse).status()).toBe(200);
  await page.waitForURL(new RegExp(`/classes/${internalCourseId}$`));
  await expect(page.getByRole("heading", { name: "Biology 101", exact: true })).toBeVisible();
  await screenshot(page, "user-a-login-continuation");
});

test("a foreign account is denied and a zero-Course account stays truthful", async ({ page }) => {
  await requireFixture();
  await signIn(page, "b2_user_b", userBPassword!);
  await page.goto(launchPath());
  await expect(page.getByTestId("blueway-launch-status-course_not_found")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Biology 101", exact: true })).toHaveCount(0);
  await screenshot(page, "foreign-account-denied");

  await page.context().clearCookies();
  await signIn(page, "b2_user_c", userCPassword!);
  await page.goto("/classes");
  await expect(page.getByRole("heading", { name: "No Classes yet", exact: true })).toBeVisible();
  await screenshot(page, "zero-course-account");
});

test("the wrong academic term never opens the Course", async ({ page }) => {
  await requireFixture();
  await signIn(page, "b2_user_a", userAPassword!);
  await page.goto(launchPath("winter-2027"));
  await expect(page.getByTestId("blueway-launch-status-term_mismatch")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Biology 101", exact: true })).toHaveCount(0);
  await screenshot(page, "term-mismatch");
});

test("the exact Course Overview remains usable at narrow mobile width and by keyboard", async ({ page }) => {
  await requireFixture();
  await page.setViewportSize({ width: 390, height: 844 });
  await signIn(page, "b2_user_a", userAPassword!);
  await page.goto(launchPath());
  await page.waitForURL(new RegExp(`/classes/${internalCourseId}$`));
  await expect(page.getByRole("heading", { name: "Biology 101", exact: true })).toBeVisible();
  await screenshot(page, "narrow-mobile-exact-course-overview");

  const backToClasses = page.getByRole("link", { name: "Back to Classes" });
  await backToClasses.focus();
  await expect(backToClasses).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/classes$/);
});
