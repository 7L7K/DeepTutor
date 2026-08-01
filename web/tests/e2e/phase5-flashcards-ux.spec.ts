import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";

const alicePassword = process.env.P4_ALICE_PASSWORD;
const bobPassword = process.env.P4_BOB_PASSWORD;
const stateFile = process.env.P4_STATE_FILE;

interface Phase5BrowserState {
  aliceCourseId: string;
  bobCourseId: string;
}

async function signIn(page: Page, username: string, password: string) {
  await page.context().clearCookies();
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
  await expect
    .poll(async () =>
      (await page.context().cookies()).some(
        (cookie) => cookie.name === "dt_token",
      ),
    )
    .toBe(true);
  await page.waitForURL((url) => !url.pathname.startsWith("/login"));
}

test("phase5 study-first shell keeps provider machinery out of the learner journey", async ({
  page,
}) => {
  test.skip(
    !alicePassword || !bobPassword || !stateFile,
    "Run through scripts/test-phase4-browser so disposable credentials are provided.",
  );
  const state = JSON.parse(
    readFileSync(stateFile!, "utf8"),
  ) as Phase5BrowserState;

  await signIn(page, "alice", alicePassword!);
  await page.goto("/flashcards");
  await page.getByLabel("Active course").selectOption(state.aliceCourseId);

  await expect(
    page.getByRole("button", { name: "Study", exact: true }),
  ).toHaveAttribute("aria-current", "page");
  await expect(
    page.getByRole("button", { name: "Create", exact: true }),
  ).toBeEnabled();
  await expect(
    page.getByRole("button", { name: "Activity", exact: true }),
  ).toBeEnabled();
  await expect(page.getByText(/Active Course:/)).toHaveCount(0);

  await page.getByRole("button", { name: "Create", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Create manually" }),
  ).toBeVisible();
  await expect(page.getByLabel("Generated deck title")).toHaveCount(0);
  await expect(page.getByText(/Objective IDs/)).toHaveCount(0);

  await page.getByRole("button", { name: "Activity", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Card creation activity" }),
  ).toBeVisible();
  await expect(page.getByText(/provider_failed/)).toHaveCount(0);
  await expect(page.getByText(/awaiting_review/)).toHaveCount(0);
  await expect(page.getByText(/next review/i)).toHaveCount(0);

  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "Study", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Create", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByTestId("flashcards-scroll-container"),
  ).toHaveCSS("overflow-y", "auto");

  const secondCourse = await page.evaluate(async () => {
    const response = await fetch("/api/v1/courses", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: "Race-safe Course" }),
    });
    if (!response.ok) throw new Error(`Course create failed: ${response.status}`);
    return (await response.json()) as { id: string };
  });
  await page.reload();
  await page.route(
    `**/api/v1/courses/${state.aliceCourseId}/flashcards**`,
    async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 500));
      await route.continue();
    },
  );
  await page.getByLabel("Active course").selectOption(secondCourse.id);
  await page.getByLabel("Active course").selectOption(state.aliceCourseId);
  await page.getByLabel("Active course").selectOption(secondCourse.id);
  await expect(page.getByLabel("Active course")).toHaveValue(secondCourse.id);
  await page.waitForTimeout(700);
  await expect(page.getByText("Visible manual deck", { exact: true })).toHaveCount(
    0,
  );

  await signIn(page, "bob", bobPassword!);
  await page.goto("/flashcards");
  await page.getByLabel("Active course").selectOption(state.bobCourseId);
  await expect(page.getByText("Visible manual deck", { exact: true })).toHaveCount(
    0,
  );
  await page.getByRole("button", { name: "Activity", exact: true }).click();
  await expect(
    page.getByText("Finishing your cards", { exact: true }),
  ).toHaveCount(0);
});
