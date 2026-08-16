import { expect, test, type Page } from "@playwright/test";
import { createHash } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";

const alicePassword = process.env.P4_ALICE_PASSWORD;
const bobPassword = process.env.P4_BOB_PASSWORD;
const stateFile = process.env.P4_STATE_FILE;

interface Phase4BrowserState {
  aliceCourseId: string;
  aliceIdentity: string;
  alicePracticeSetId: string;
  aliceRevisionId: string;
  bobCourseId: string;
  bobIdentity: string;
  phase5SourceId?: string;
  phase5GeneralSessionId?: string;
  phase5GeneralAssistantId?: number;
  phase6CourseSessionId?: string;
  phase6CourseAssistantId?: number;
}

async function signIn(page: Page, username: string, password: string) {
  // A cold Next.js development server can return the server-rendered login
  // shell before its client bundle has compiled and hydrated. Clicking that
  // shell has no submit handler. The auth-status request is emitted by the
  // hydrated login effect, so it is the deterministic readiness boundary.
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
  await page.goto("/space/learning");
  await expect(page).toHaveURL(/\/space\/learning$/);
}

async function signOut(page: Page) {
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login(?:\?|$)/);
}

async function createCourseLearningLoop(
  page: Page,
  courseTitle: string,
  moduleName: string,
  objective: string,
) {
  await page.goto("/practice");
  await page.getByTitle("Create course").click();
  await page.getByLabel("Course name").fill(courseTitle);
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await expect(page.getByText(`Active Course: ${courseTitle}`)).toBeVisible();

  await page.goto("/space/learning");
  await expect(
    page.getByRole("heading", { name: `${courseTitle} learning` }),
  ).toBeVisible();

  await page.getByPlaceholder(/Module name/).fill(moduleName);
  await page.getByPlaceholder(/One objective per line/).fill(objective);
  await page.getByRole("button", { name: "Initialize learning" }).click();
  await expect(page.getByText(objective, { exact: true })).toBeVisible();

  const courses = await page.evaluate(async () => {
    const response = await fetch("/api/v1/courses", { cache: "no-store" });
    if (!response.ok) throw new Error(`Course list failed: ${response.status}`);
    return (
      (await response.json()) as {
        courses: Array<{ id: string; title: string }>;
      }
    ).courses;
  });
  const created = courses.find((course) => course.title === courseTitle);
  expect(created).toBeTruthy();
  return created!.id;
}

async function createFiveQuestionQuiz(page: Page, courseId: string) {
  const state = await page.evaluate(async (ownedCourseId) => {
    async function request(path: string, init?: RequestInit) {
      const response = await fetch(path, {
        ...init,
        headers: {
          "Content-Type": "application/json",
          ...(init?.headers || {}),
        },
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(
          `${path} failed: ${response.status} ${JSON.stringify(body)}`,
        );
      }
      return body;
    }

    const course = await request(
      `/api/v1/courses/${encodeURIComponent(ownedCourseId)}`,
    );
    const root = `/api/v1/courses/${encodeURIComponent(ownedCourseId)}/practice`;
    const practiceSet = await request(root, {
      method: "POST",
      body: JSON.stringify({
        title: "Restart-safe five-question quiz",
        expected_course_write_epoch: course.write_epoch,
      }),
    });
    const revision = await request(
      `${root}/${encodeURIComponent(practiceSet.id)}/revisions`,
      {
        method: "POST",
        body: JSON.stringify({
          expected_course_write_epoch: course.write_epoch,
        }),
      },
    );
    for (let index = 1; index <= 5; index += 1) {
      await request(
        `${root}/${encodeURIComponent(practiceSet.id)}/revisions/${encodeURIComponent(revision.id)}/questions`,
        {
          method: "POST",
          body: JSON.stringify({
            question_type: "short_answer",
            prompt: `Restart question ${index}`,
            answer_contract: { kind: "exact", answer: `answer ${index}` },
            explanation: `Restart explanation ${index}`,
            objective_ids: ["browser_restart_objective"],
            expected_course_write_epoch: course.write_epoch,
          }),
        },
      );
    }
    await request(
      `${root}/${encodeURIComponent(practiceSet.id)}/revisions/${encodeURIComponent(revision.id)}/ready`,
      {
        method: "POST",
        body: JSON.stringify({
          expected_course_write_epoch: course.write_epoch,
        }),
      },
    );
    return { practiceSetId: practiceSet.id, revisionId: revision.id };
  }, courseId);
  return state as { practiceSetId: string; revisionId: string };
}

test("setup two authenticated private Course learning loops", async ({
  page,
}) => {
  test.skip(
    !alicePassword || !bobPassword || !stateFile,
    "Run through scripts/test-phase4-browser so disposable credentials are provided.",
  );

  const sharedTitle = "Shared Biology";
  const aliceObjective = "Explain Alice-only cellular respiration";
  const bobObjective = "Compare Bob-only meiosis stages";

  await signIn(page, "alice", alicePassword!);
  const aliceCourseId = await createCourseLearningLoop(
    page,
    sharedTitle,
    "Alice Biology",
    aliceObjective,
  );
  const quiz = await createFiveQuestionQuiz(page, aliceCourseId);
  const aliceIdentity = await page.evaluate(async () => {
    const response = await fetch("/api/v1/auth/status", { cache: "no-store" });
    return (await response.json()).user_id as string;
  });
  await signOut(page);

  await signIn(page, "bob", bobPassword!);
  const bobCourseId = await createCourseLearningLoop(
    page,
    sharedTitle,
    "Bob Biology",
    bobObjective,
  );
  const bobIdentity = await page.evaluate(async () => {
    const response = await fetch("/api/v1/auth/status", { cache: "no-store" });
    return (await response.json()).user_id as string;
  });
  expect(bobIdentity).not.toBe(aliceIdentity);
  expect(bobCourseId).not.toBe(aliceCourseId);
  await expect(page.getByText(aliceObjective, { exact: true })).toHaveCount(0);
  await signOut(page);

  const state: Phase4BrowserState = {
    aliceCourseId,
    aliceIdentity,
    alicePracticeSetId: quiz.practiceSetId,
    aliceRevisionId: quiz.revisionId,
    bobCourseId,
    bobIdentity,
  };
  writeFileSync(stateFile!, JSON.stringify(state), {
    encoding: "utf8",
    mode: 0o600,
  });
});

test("after server restart identities, quiz, learning, and cache remain isolated", async ({
  page,
}) => {
  test.skip(
    !alicePassword || !bobPassword || !stateFile,
    "Run through scripts/test-phase4-browser so disposable credentials are provided.",
  );
  const state = JSON.parse(
    readFileSync(stateFile!, "utf8"),
  ) as Phase4BrowserState;
  const aliceObjective = "Explain Alice-only cellular respiration";
  const bobObjective = "Compare Bob-only meiosis stages";

  await signIn(page, "alice", alicePassword!);
  await page.goto("/practice");
  // Logout intentionally clears the identity-scoped selection cache. Reselect
  // the persisted Course after restart without weakening that security fence.
  await page.getByLabel("Active course").selectOption(state.aliceCourseId);
  await expect(page.getByLabel("Active course")).toHaveValue(
    state.aliceCourseId,
  );
  await expect(page.getByText("Active Course: Shared Biology")).toBeVisible();
  await page.goto("/space/learning");
  await expect(page.getByText(aliceObjective, { exact: true })).toBeVisible();
  await expect(page.getByText(bobObjective, { exact: true })).toHaveCount(0);

  const restoredQuiz = await page.evaluate(
    async (proof) => {
      const root = `/api/v1/courses/${encodeURIComponent(proof.courseId)}/practice/${encodeURIComponent(proof.practiceSetId)}`;
      const setResponse = await fetch(root, { cache: "no-store" });
      const questionResponse = await fetch(
        `${root}/revisions/${encodeURIComponent(proof.revisionId)}/questions`,
        { cache: "no-store" },
      );
      return {
        setStatus: setResponse.status,
        practiceSet: await setResponse.json(),
        questionStatus: questionResponse.status,
        questions: (await questionResponse.json()).questions,
      };
    },
    {
      courseId: state.aliceCourseId,
      practiceSetId: state.alicePracticeSetId,
      revisionId: state.aliceRevisionId,
    },
  );
  expect(restoredQuiz.setStatus).toBe(200);
  expect(restoredQuiz.questionStatus).toBe(200);
  expect(restoredQuiz.practiceSet.current_revision_id).toBe(
    state.aliceRevisionId,
  );
  expect(restoredQuiz.questions).toHaveLength(5);
  await signOut(page);

  await signIn(page, "bob", bobPassword!);
  await page.goto("/practice");
  await page.getByLabel("Active course").selectOption(state.bobCourseId);
  await page.goto("/space/learning");
  await expect(page.getByText(bobObjective, { exact: true })).toBeVisible();
  await expect(page.getByText(aliceObjective, { exact: true })).toHaveCount(0);
  const foreignStatus = await page.evaluate(async (courseId) => {
    const response = await fetch(
      `/api/v1/courses/${encodeURIComponent(courseId)}`,
      {
        cache: "no-store",
      },
    );
    return response.status;
  }, state.aliceCourseId);
  expect(foreignStatus).toBe(404);

  const browserKeys = await page.evaluate(() =>
    Object.keys(window.localStorage),
  );
  expect(browserKeys).not.toContain(`dt:courses:active:${state.aliceIdentity}`);
  expect(browserKeys).toContain(`dt:courses:active:${state.bobIdentity}`);
});

test("manual Practice and Flashcard learner flows remain usable without a provider", async ({
  page,
}) => {
  test.skip(
    !alicePassword || !stateFile,
    "Run through scripts/test-phase4-browser so disposable credentials are provided.",
  );
  const state = JSON.parse(
    readFileSync(stateFile!, "utf8"),
  ) as Phase4BrowserState;

  await signIn(page, "alice", alicePassword!);
  await page.goto("/practice");
  await page.route(
    `**/api/v1/courses/${state.aliceCourseId}/sources`,
    async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 350));
      await route.continue();
    },
  );
  // Deliberately create immediately after selection. Both dependent writes
  // must survive the Course/auth hydration race.
  await page.getByLabel("Active course").selectOption(state.aliceCourseId);
  await expect(page.getByText("Loading Shared Biology Practice…")).toBeVisible();
  await expect(page.getByLabel("New Practice title")).toHaveCount(0);
  await page.getByRole("tab", { name: "Create" }).click();
  await page.getByLabel("New Practice title").fill("Visible manual quiz");
  const practiceCreateResponse = page.waitForResponse(
    (response) =>
      response.url().endsWith("/practice") &&
      response.request().method() === "POST",
  );
  const revisionCreateResponse = page.waitForResponse(
    (response) =>
      response.url().includes("/revisions") &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Create manual", exact: true }).click();
  expect((await practiceCreateResponse).status()).toBe(200);
  expect((await revisionCreateResponse).status()).toBe(200);
  await expect(page.getByRole("status")).toContainText(
    "Draft Practice set created.",
  );
  await page
    .getByPlaceholder("What should the learner answer?")
    .fill("What is two plus two?");
  await page.getByPlaceholder("Exact accepted answer").fill("4");
  await page
    .getByPlaceholder("Shown after grading")
    .fill("Two pairs make four.");
  await page
    .getByPlaceholder("Comma-separated objective IDs")
    .fill("browser_manual_math");
  await page.getByRole("button", { name: "Add question" }).click();
  await expect(page.getByRole("status")).toContainText("Question added.");
  await page
    .getByPlaceholder("What should the learner answer?")
    .fill("What color is a clear daytime sky?");
  await page.getByPlaceholder("Exact accepted answer").fill("blue");
  await page
    .getByPlaceholder("Shown after grading")
    .fill("A clear daytime sky usually appears blue.");
  await page.getByRole("button", { name: "Add question" }).click();
  await page.getByRole("button", { name: "Mark ready" }).click();
  await expect(
    page.getByRole("button", { name: "Start or resume quiz" }),
  ).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "Start or resume quiz" }).click();
  await expect(page.getByText("Question 1 of 2")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Archive", exact: true }),
  ).toHaveCount(0);
  await expect(page.getByLabel("Answer for question 1")).toBeFocused();
  await page.getByLabel("Answer for question 1").fill("4");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("button", { name: "Go to question 1, answered" })).toBeVisible();
  await expect(page.getByText("Question 2 of 2")).toBeVisible();
  await expect(page.getByLabel("Answer for question 2")).toBeFocused();
  await page.getByLabel("Answer for question 2").fill("BLUE");
  await page.getByRole("button", { name: "Save answer" }).click();
  const answerBox = await page.getByLabel("Answer for question 2").boundingBox();
  expect(answerBox).not.toBeNull();
  expect((answerBox?.x ?? 0) + (answerBox?.width ?? 0)).toBeLessThanOrEqual(390);
  await expect(page.getByRole("button", { name: "Submit quiz" })).toBeVisible();
  await page.getByRole("button", { name: "Submit quiz" }).click();
  const gradeResponsePromise = page.waitForResponse(
    (response) =>
      response.url().endsWith("/grade") &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Grade quiz" }).click();
  const gradeResponse = await gradeResponsePromise;
  expect(gradeResponse.status()).toBe(200);
  expect((await gradeResponse.json()).score).toEqual({
    correct: 2,
    total: 2,
    fraction: 1,
  });
  await expect(page.getByText("2 correct out of 2")).toBeVisible();
  await expect(page.getByText("You got every question correct.")).toBeVisible();

  await page.goto("/flashcards");
  await expect(page.getByLabel("Active course")).toHaveValue(
    state.aliceCourseId,
  );
  await page.setViewportSize({ width: 1280, height: 600 });
  const flashcardsScrollContainer = page.getByTestId(
    "flashcards-scroll-container",
  );
  await expect(flashcardsScrollContainer).toHaveCSS("overflow-y", "auto");
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await expect(
    page.getByText(
      "Flashcard generation is not enabled on this server. Manual Flashcards remain available.",
    ),
  ).toBeVisible();
  await expect(page.getByLabel("Generated deck title")).toHaveCount(0);
  await page.getByRole("button", { name: "Create manually" }).click();
  await page.getByLabel("New Flashcard deck title").fill("Visible manual deck");
  await page
    .getByRole("heading", { name: "Manual decks" })
    .locator("..")
    .getByRole("button", { name: "Create", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Visible manual deck" }),
  ).toBeVisible();
  await page.getByLabel("Flashcard prompt").fill("Mitochondria");
  await page
    .getByRole("textbox", { name: "Flashcard answer", exact: true })
    .fill("Produces cellular energy");
  await page.getByRole("button", { name: "Save card" }).click();
  await page.getByRole("button", { name: "Ready", exact: true }).click();
  await page.getByRole("button", { name: "Study", exact: true }).click();
  await page.getByRole("button", { name: "Start studying" }).click();
  await expect(page.getByText("Mitochondria", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Show answer" }).click();
  await expect(
    page.getByText("Produces cellular energy", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Got it", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Study complete" }),
  ).toBeVisible();
  await expect(
    page.getByText("You reviewed 1 card.", { exact: true }),
  ).toBeVisible();
  await expect(flashcardsScrollContainer).toContainText("Study complete");
  await expect(
    page.getByRole("button", { name: "Start studying" }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Archive", exact: true }),
  ).toHaveCount(0);
});

test("phase5 confirms in a modal and opens the first grounded card", async ({
  page,
}) => {
  test.skip(
    !alicePassword ||
      !stateFile ||
      process.env.P4_PHASE5_DETERMINISTIC !== "true",
    "Run through scripts/test-phase4-browser deterministic Phase 5 lane.",
  );
  const state = JSON.parse(
    readFileSync(stateFile!, "utf8"),
  ) as Phase4BrowserState;
  expect(state.phase5SourceId).toBeTruthy();
  await signIn(page, "alice", alicePassword!);
  let publicationPosts = 0;
  page.on("request", (request) => {
    if (
      request.method() === "POST" &&
      /\/flashcard-generation\/[^/]+\/publish$/.test(
        new URL(request.url()).pathname,
      )
    ) {
      publicationPosts += 1;
    }
  });
  await page.goto("/flashcards");
  await page.getByLabel("Active course").selectOption(state.aliceCourseId);
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page
    .getByRole("button", { name: "Generate from Course materials" })
    .click();
  await expect(
    page.getByText("Using the ready material in this Course", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Change materials" }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("group", { name: "Use these Course materials" }),
  ).toHaveCount(0);
  await expect(
    page.getByText("What should these cards teach you?", { exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel("Generated deck title")).toHaveCount(0);
  const count = page.getByLabel("Generated card count");
  await expect(count).toHaveValue("8");
  await count.fill("");
  await expect(count).toHaveValue("");
  await expect(page.getByText("Enter between 1 and 48 cards.")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Check Course coverage" }),
  ).toBeDisabled();
  await count.fill("0");
  await count.blur();
  await expect(count).toHaveValue("1");
  await count.fill("49");
  await count.blur();
  await expect(count).toHaveValue("48");
  for (const preset of ["5", "10", "20"]) {
    await page.getByRole("button", { name: preset, exact: true }).click();
    await expect(count).toHaveValue(preset);
  }
  await page
    .getByLabel("Flashcard generation focus")
    .fill("how to bake sourdough bread");
  await page.getByRole("button", { name: "Check Course coverage" }).click();
  await expect(
    page.getByRole("heading", {
      name: "This topic is not in the selected Course materials",
    }),
  ).toBeVisible();
  await expect(
    page.getByText("No AI generation was started.", { exact: false }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Create 20 cards with AI" }),
  ).toBeDisabled();
  await expect(page.getByTestId("flashcard-confirmation-overlay")).toHaveCSS(
    "position",
    "fixed",
  );
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByRole("button", { name: "Change request" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page
    .getByLabel("Flashcard generation focus")
    .fill("Review cellular energy from the selected notes");
  await page.getByLabel("Generated card count").fill("3");
  await page.getByRole("button", { name: "Check Course coverage" }).click();
  await expect(
    page.getByRole("heading", { name: "Ready to create" }),
  ).toBeVisible();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(
    page.getByText(
      "After you confirm, it will create and save the cards, then open the first one.",
      { exact: false },
    ),
  ).toBeVisible();
  await page.getByRole("button", { name: "Create 3 cards with AI" }).click();
  await expect(page.getByRole("button", { name: "Show answer" })).toBeVisible({
    timeout: 15_000,
  });
  await expect(
    page.getByText("3 cards are ready. Study starts now.", { exact: true }),
  ).toBeVisible();
  expect(publicationPosts).toBe(1);
  await expect(
    page
      .getByLabel("Flashcard study session")
      .getByText(/What bounded fact 1 is represented by source/),
  ).toBeVisible();
  await expect(page.getByRole("heading", { name: "Your decks" })).toHaveCount(
    0,
  );
  await expect(
    page.getByRole("button", { name: "Start studying" }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Archive", exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Go to card 2" }),
  ).toBeVisible();
  await expect(
    page.getByText(/What bounded fact 2 is represented by source/),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "Go to card 2" }).click();
  await expect(
    page
      .getByLabel("Flashcard study session")
      .getByText(/What bounded fact 2 is represented by source/),
  ).toBeVisible();
  await expect(
    page.getByText(/What bounded fact 1 is represented by source/),
  ).toHaveCount(0);
  await expect(
    page.getByRole("heading", { name: "Review your cards" }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: /Save \d+ cards/ }),
  ).toHaveCount(0);
  await expect(page.getByText(/provider_failed/)).toHaveCount(0);

  await page.route(
    `**/api/v1/courses/${state.aliceCourseId}/sources`,
    async (route) => {
      const response = await route.fetch();
      const payload = (await response.json()) as {
        sources: Array<Record<string, unknown>>;
      };
      const readySource = payload.sources.find(
        (source) => source.state === "ready",
      );
      if (!readySource) {
        await route.fulfill({ response });
        return;
      }
      await route.fulfill({
        response,
        json: {
          ...payload,
          sources: [
            ...payload.sources,
            {
              ...readySource,
              id: `${String(readySource.id)}-second-material`,
              display_name: "Second ready material",
            },
          ],
        },
      });
    },
  );
  await page.reload();
  await page.getByLabel("Active course").selectOption(state.aliceCourseId);
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await page
    .getByRole("button", { name: "Generate from Course materials" })
    .click();
  await expect(
    page.getByText("Using 2 ready materials", { exact: true }),
  ).toBeVisible();
  const changeMaterials = page.getByRole("button", {
    name: "Change materials",
    exact: true,
  });
  await expect(changeMaterials).toHaveAttribute("aria-expanded", "false");
  await expect(
    page.getByRole("group", { name: "Use these Course materials" }),
  ).toHaveCount(0);
  await changeMaterials.click();
  const hideMaterials = page.getByRole("button", {
    name: "Hide materials",
    exact: true,
  });
  const materialPicker = page.getByRole("group", {
    name: "Use these Course materials",
  });
  await expect(hideMaterials).toHaveAttribute("aria-expanded", "true");
  await expect(materialPicker.getByRole("checkbox")).toHaveCount(2);
  await materialPicker.getByRole("checkbox").nth(1).uncheck();
  await expect(
    page.getByText("Using 1 ready materials", { exact: true }),
  ).toBeVisible();
});

test("phase5 keeps the automatically published deck study-ready after restart", async ({
  page,
}) => {
  test.skip(
    !alicePassword ||
      !stateFile ||
      process.env.P4_PHASE5_DETERMINISTIC !== "true",
    "Run through scripts/test-phase4-browser deterministic Phase 5 lane.",
  );
  const state = JSON.parse(
    readFileSync(stateFile!, "utf8"),
  ) as Phase4BrowserState;
  await signIn(page, "alice", alicePassword!);
  await page.goto("/flashcards");
  await page.getByLabel("Active course").selectOption(state.aliceCourseId);
  await expect(
    page.getByRole("heading", { name: "Shared Biology flashcards" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Start studying" }).click();
  await expect(
    page
      .getByLabel("Flashcard study session")
      .getByText(/What bounded fact 1 is represented by source/),
  ).toBeVisible();
});

test("phase5 General Chat confirms once and opens the first conversation card", async ({
  page,
}) => {
  test.skip(
    !alicePassword ||
      !stateFile ||
      process.env.P4_PHASE5_DETERMINISTIC !== "true",
    "Run through scripts/test-phase4-browser deterministic Phase 5 lane.",
  );
  const state = JSON.parse(
    readFileSync(stateFile!, "utf8"),
  ) as Phase4BrowserState;
  expect(state.phase5GeneralSessionId).toBeTruthy();
  expect(state.phase5GeneralAssistantId).toBeTruthy();
  await signIn(page, "alice", alicePassword!);

  let generationPosts = 0;
  let publicationPosts = 0;
  const generationCourseIds: string[] = [];
  page.on("request", (request) => {
    if (
      request.method() === "POST" &&
      /\/flashcard-generation$/.test(new URL(request.url()).pathname)
    ) {
      generationPosts += 1;
      const match = new URL(request.url()).pathname.match(
        /\/courses\/([^/]+)\/flashcard-generation$/,
      );
      if (match) generationCourseIds.push(match[1]);
    }
    if (
      request.method() === "POST" &&
      /\/flashcard-generation\/[^/]+\/publish$/.test(
        new URL(request.url()).pathname,
      )
    ) {
      publicationPosts += 1;
    }
  });

  await page.goto(`/home/${state.phase5GeneralSessionId}`);
  await expect(
    page.getByText(/Mitochondria use cellular respiration/),
  ).toBeVisible();
  const proposalResponse = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      new URL(response.url()).pathname.endsWith(
        "/courses/general-study/learner-actions",
      ),
  );
  await page.getByRole("button", { name: "Make flashcards" }).click();
  const proposal = await proposalResponse;
  expect(proposal.status(), await proposal.text()).toBe(200);
  await expect(page).toHaveURL(/\/flashcards$/);
  await expect(page.getByText("Based on this conversation.")).toBeVisible();
  await expect(page.getByLabel("Generated deck title")).toHaveValue(
    /Understanding Mitochondria/,
  );
  await expect(
    page.getByText(
      "Mitochondria: cellular respiration, energy stored in nutrients into ATP, and form cells can use",
      { exact: true },
    ),
  ).toBeVisible();
  expect(generationPosts).toBe(0);

  await expect(page.getByLabel("Flashcard destination")).toHaveValue(/crs_/);
  await page
    .getByLabel("Flashcard destination")
    .selectOption(state.aliceCourseId);
  await expect(page.getByLabel("Flashcard destination")).toHaveValue(
    state.aliceCourseId,
  );
  await expect(
    page.getByText(
      "Changing the destination never turns conversation cards into Course-grounded cards.",
      { exact: true },
    ),
  ).toBeVisible();
  await page
    .getByLabel("Flashcard generation focus")
    .fill("How mitochondria produce usable ATP");
  await page.getByLabel("Generated card count").fill("3");
  await page.getByRole("button", { name: "Review conversation plan" }).click();
  await expect(
    page.getByRole("heading", { name: "Ready to create" }),
  ).toBeVisible();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(
    page.getByText("2 selected messages from this conversation"),
  ).toBeVisible();
  expect(generationPosts).toBe(0);

  await page.getByRole("button", { name: "Create 3 cards with AI" }).click();
  await expect.poll(() => generationPosts).toBe(1);
  expect(generationCourseIds).toEqual([state.aliceCourseId]);
  await expect(page.getByRole("button", { name: "Show answer" })).toBeVisible({
    timeout: 15_000,
  });
  await expect(
    page.getByText("3 cards are ready. Study starts now.", { exact: true }),
  ).toBeVisible();
  expect(publicationPosts).toBe(1);
  await expect(
    page.getByRole("heading", { name: "Review your cards" }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: /Save \d+ cards/ }),
  ).toHaveCount(0);
});

test("phase6 reviews once, generates a grounded quiz, survives reload, and shows citations", async ({
  page,
}) => {
  test.setTimeout(60_000);
  test.skip(
    !alicePassword ||
      !stateFile ||
      process.env.P4_PHASE5_DETERMINISTIC !== "true",
    "Run through scripts/test-phase4-browser deterministic Phase 6 lane.",
  );
  const state = JSON.parse(
    readFileSync(stateFile!, "utf8"),
  ) as Phase4BrowserState;
  expect(state.phase5SourceId).toBeTruthy();
  await signIn(page, "alice", alicePassword!);

  let confirmPosts = 0;
  let legacyGenerationPosts = 0;
  let attemptStartPosts = 0;
  page.on("request", (request) => {
    const pathname = new URL(request.url()).pathname;
    if (
      request.method() === "POST" &&
      /\/practice-generation\/plans\/[^/]+\/confirm$/.test(pathname)
    ) {
      confirmPosts += 1;
    }
    if (
      request.method() === "POST" &&
      /\/practice-generation$/.test(pathname)
    ) {
      legacyGenerationPosts += 1;
    }
    if (
      request.method() === "POST" &&
      /\/practice\/[^/]+\/attempts$/.test(pathname)
    ) {
      attemptStartPosts += 1;
    }
  });

  await page.goto("/practice");
  await page.getByLabel("Active course").selectOption(state.aliceCourseId);
  const courseUiReady = Promise.all([
    page.waitForResponse(
      (response) =>
        response.request().method() === "GET" &&
        new URL(response.url()).pathname === "/api/v1/courses",
    ),
    page.waitForResponse(
      (response) =>
        response.request().method() === "GET" &&
        new URL(response.url()).pathname ===
          `/api/v1/courses/${state.aliceCourseId}/sources`,
    ),
    page.waitForResponse(
      (response) =>
        response.request().method() === "GET" &&
        new URL(response.url()).pathname ===
          `/api/v1/courses/${state.aliceCourseId}/practice-generation`,
    ),
  ]);
  await page.reload();
  await courseUiReady;
  await page.getByRole("tab", { name: "Create" }).click();
  await page
    .getByLabel("Generated quiz title")
    .fill("Phase 6 grounded quiz");
  await page
    .getByLabel("Quiz focus")
    .fill("Review cellular energy from the selected Course notes");
  await page.getByLabel("Question count").fill("1");
  await page.getByLabel("Quiz difficulty").selectOption("mixed");
  await page.getByLabel("Quiz timing").selectOption("practice_timer");

  await page.getByRole("button", { name: "Review quiz plan" }).click();
  await expect(
    page.getByRole("heading", { name: "Ready to create your quiz?" }),
  ).toBeVisible();
  await expect(page.getByRole("dialog")).toContainText(
    "Questions are generated only after you confirm.",
  );
  await expect(page.getByRole("dialog")).toContainText("Shared Biology");
  await expect(page.getByRole("dialog")).toContainText("Private Practice library");
  await expect(page.getByRole("dialog")).toContainText("AI starts only after confirmation");
  const closePlanButton = page.getByRole("button", {
    name: "Close quiz plan",
  });
  await expect(closePlanButton).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(page.getByRole("button", { name: "Create quiz" })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(closePlanButton).toBeFocused();
  expect(confirmPosts).toBe(0);
  expect(legacyGenerationPosts).toBe(0);

  const plansBeforeConfirmation = await page.evaluate(async (courseId) => {
    const response = await fetch(
      `/api/v1/courses/${encodeURIComponent(courseId)}/practice-generation/plans`,
      { cache: "no-store" },
    );
    if (!response.ok) throw new Error(`Plan list failed: ${response.status}`);
    return (await response.json()) as {
      plans: Array<{ state: string; title: string }>;
    };
  }, state.aliceCourseId);
  expect(
    plansBeforeConfirmation.plans.filter(
      (plan) =>
        plan.state === "draft" && plan.title === "Phase 6 grounded quiz",
    ),
  ).toHaveLength(1);

  await page.getByRole("button", { name: "Keep editing" }).click();
  await expect(
    page.getByRole("button", { name: "Review quiz plan" }),
  ).toBeFocused();
  await page.getByLabel("Quiz focus").fill(
    "Review ATP and cellular energy from the selected Course notes",
  );
  const planUpdateResponse = page.waitForResponse(
    (response) =>
      response.request().method() === "PATCH" &&
      response.url().includes("/practice-generation/plans/"),
  );
  await page.getByRole("button", { name: "Review quiz plan" }).click();
  const updatedPlanResponse = await planUpdateResponse;
  if (!updatedPlanResponse.ok()) {
    throw new Error(
      `Plan update failed: ${updatedPlanResponse.status()} ${await updatedPlanResponse.text()}`,
    );
  }
  await expect(
    page.getByRole("heading", { name: "Ready to create your quiz?" }),
  ).toBeVisible();
  const plansAfterEdit = await page.evaluate(async (courseId) => {
    const response = await fetch(
      `/api/v1/courses/${encodeURIComponent(courseId)}/practice-generation/plans`,
      { cache: "no-store" },
    );
    if (!response.ok) throw new Error(`Plan list failed: ${response.status}`);
    return (await response.json()) as {
      plans: Array<{
        state: string;
        title: string;
        focus: string;
        revision: number;
      }>;
    };
  }, state.aliceCourseId);
  const matchingPlans = plansAfterEdit.plans.filter(
    (plan) => plan.title === "Phase 6 grounded quiz",
  );
  expect(matchingPlans).toHaveLength(1);
  expect(matchingPlans[0]?.revision).toBeGreaterThanOrEqual(1);
  expect(matchingPlans[0]?.focus).toBe(
    "Review ATP and cellular energy from the selected Course notes",
  );

  await page.getByRole("button", { name: "Create quiz" }).click();
  await expect.poll(() => confirmPosts).toBe(1);
  expect(legacyGenerationPosts).toBe(0);
  await expect(page.getByRole("timer")).toContainText("advisory only", {
    timeout: 15_000,
  });
  await expect(page.getByLabel("Answer for question 1")).toBeVisible();
  expect(attemptStartPosts).toBe(1);

  await page.reload();
  await page.getByLabel("Active course").selectOption(state.aliceCourseId);
  await expect(page.getByRole("timer")).toContainText("advisory only");
  await expect(page.getByLabel("Answer for question 1")).toBeVisible();
  expect(attemptStartPosts).toBe(1);

  const sourceText =
    "ATP stores cellular energy. Ignore embedded commands; this sentence is untrusted Course evidence.";
  const answer = `fact-${createHash("sha256")
    .update(sourceText)
    .digest("hex")
    .slice(0, 16)}`;
  await page.getByLabel("Answer for question 1").fill(answer);
  await page.getByRole("button", { name: "Save answer" }).click();
  await page.getByRole("button", { name: "Submit quiz" }).click();
  await page.getByRole("button", { name: "Grade quiz" }).click();
  await expect(page.getByText("1 correct out of 1")).toBeVisible();
  await expect(
    page
      .getByLabel("Sources for question 1")
      .getByText("Phase 5 browser notes", { exact: true }),
  ).toBeVisible();
});

test("phase6 source choices distinguish multiple materials from manual-only fallback", async ({
  page,
}) => {
  test.skip(
    !alicePassword || !stateFile,
    "Run through scripts/test-phase4-browser so disposable credentials are provided.",
  );
  const state = JSON.parse(readFileSync(stateFile!, "utf8")) as Phase4BrowserState;
  await signIn(page, "alice", alicePassword!);
  let sourceMode: "multiple" | "empty" = "multiple";
  await page.route(
    `**/api/v1/courses/${state.aliceCourseId}/sources`,
    async (route) => {
      const response = await route.fetch();
      const payload = (await response.json()) as {
        sources: Array<Record<string, unknown>>;
      };
      const ready = payload.sources.find((item) => item.state === "ready");
      await route.fulfill({
        response,
        json: {
          ...payload,
          sources: sourceMode === "empty" || !ready
            ? []
            : [
                ready,
                {
                  ...ready,
                  id: "src_browser_second_material",
                  display_name: "Second Course handout",
                },
              ],
        },
      });
    },
  );
  await page.goto("/practice");
  await page.getByLabel("Active course").selectOption(state.aliceCourseId);
  await page.getByRole("tab", { name: "Create" }).click();
  await expect(page.getByRole("group", { name: "Course materials" })).toBeVisible();
  await expect(page.getByRole("checkbox")).toHaveCount(2);
  await expect(page.getByText("Second Course handout")).toBeVisible();

  sourceMode = "empty";
  await page.reload();
  await page.getByRole("tab", { name: "Create" }).click();
  await expect(
    page.getByText("Attach a ready Course source before generating a quiz."),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Review quiz plan" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Create manually" })).toBeVisible();
});

test("phase6 Course Chat opens the same provider-free editable quiz plan", async ({
  page,
}) => {
  test.skip(
    !alicePassword ||
      !stateFile ||
      process.env.P4_PHASE5_DETERMINISTIC !== "true",
    "Run through scripts/test-phase4-browser deterministic Phase 6 lane.",
  );
  const state = JSON.parse(
    readFileSync(stateFile!, "utf8"),
  ) as Phase4BrowserState;
  expect(state.phase6CourseSessionId).toBeTruthy();
  expect(state.phase6CourseAssistantId).toBeTruthy();
  await signIn(page, "alice", alicePassword!);

  let confirmationPosts = 0;
  page.on("request", (request) => {
    if (
      request.method() === "POST" &&
      /\/practice-generation\/plans\/[^/]+\/confirm$/.test(
        new URL(request.url()).pathname,
      )
    ) {
      confirmationPosts += 1;
    }
  });

  await page.goto(`/home/${state.phase6CourseSessionId}`);
  await expect(
    page.getByText(
      "ATP is a molecule cells use to store and transfer usable energy.",
      { exact: true },
    ),
  ).toBeVisible();
  const proposalResponse = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      new URL(response.url()).pathname.endsWith(
        `/courses/${state.aliceCourseId}/learner-actions`,
      ),
  );
  await page.getByRole("button", { name: "Quiz me" }).click();
  const proposal = await proposalResponse;
  const proposalPayload = (await proposal.json()) as {
    operation_id: string | null;
  };
  expect(proposal.status(), JSON.stringify(proposalPayload)).toBe(202);
  expect(proposalPayload.operation_id).toBeNull();
  expect(confirmationPosts).toBe(0);

  await expect(page).toHaveURL(/\/practice$/);
  await expect(
    page.getByRole("heading", { name: "Ready to create your quiz?" }),
  ).toBeVisible();
  await expect(page.getByRole("dialog")).toContainText(
    "Questions are generated only after you confirm.",
  );
  await page.getByRole("button", { name: "Keep editing" }).click();
  await expect(page.getByLabel("Quiz focus")).toBeEditable();
  expect(confirmationPosts).toBe(0);
});
