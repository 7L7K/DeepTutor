import { expect, test, type Page } from "@playwright/test";
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
}

async function signIn(page: Page, username: string, password: string) {
  await page.goto("/login");
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
      (await page.context().cookies()).some((cookie) => cookie.name === "dt_token"),
    )
    .toBe(true);
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
  await expect(page.getByRole("heading", { name: `${courseTitle} learning` })).toBeVisible();

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
        throw new Error(`${path} failed: ${response.status} ${JSON.stringify(body)}`);
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
  await expect(page.getByLabel("Active course")).toHaveValue(state.aliceCourseId);
  await expect(page.getByText("Active Course: Shared Biology")).toBeVisible();
  await page.goto("/space/learning");
  await expect(page.getByText(aliceObjective, { exact: true })).toBeVisible();
  await expect(page.getByText(bobObjective, { exact: true })).toHaveCount(0);

  const restoredQuiz = await page.evaluate(async (proof) => {
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
  }, {
    courseId: state.aliceCourseId,
    practiceSetId: state.alicePracticeSetId,
    revisionId: state.aliceRevisionId,
  });
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
    const response = await fetch(`/api/v1/courses/${encodeURIComponent(courseId)}`, {
      cache: "no-store",
    });
    return response.status;
  }, state.aliceCourseId);
  expect(foreignStatus).toBe(404);

  const browserKeys = await page.evaluate(() => Object.keys(window.localStorage));
  expect(browserKeys).not.toContain(
    `dt:courses:active:${state.aliceIdentity}`,
  );
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
  // Deliberately create immediately after selection. Both dependent writes
  // must survive the Course/auth hydration race.
  await page.getByLabel("Active course").selectOption(state.aliceCourseId);

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
  await page
    .getByRole("complementary")
    .getByRole("button", { name: "Create", exact: true })
    .click();
  expect((await practiceCreateResponse).status()).toBe(200);
  expect((await revisionCreateResponse).status()).toBe(200);
  await expect(page.getByRole("status")).toContainText("Draft Practice set created.");
  await page.getByPlaceholder("What should the learner answer?").fill("What is two plus two?");
  await page.getByPlaceholder("Exact accepted answer").fill("4");
  await page.getByPlaceholder("Shown after grading").fill("Two pairs make four.");
  await page.getByPlaceholder("Comma-separated objective IDs").fill("browser_manual_math");
  await page.getByRole("button", { name: "Add question" }).click();
  await expect(page.getByRole("status")).toContainText("Question added.");
  await page.getByRole("button", { name: "Mark ready" }).click();
  await expect(page.getByRole("button", { name: "Start or resume quiz" })).toBeVisible();
  await page.getByRole("button", { name: "Start or resume quiz" }).click();
  await page.getByLabel("Answer for question 1").fill("4");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText(/Saved revision/)).toBeVisible();
  await page.getByRole("button", { name: "Submit", exact: true }).click();
  const gradeResponsePromise = page.waitForResponse(
    (response) =>
      response.url().endsWith("/grade") &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Grade", exact: true }).click();
  const gradeResponse = await gradeResponsePromise;
  expect(gradeResponse.status()).toBe(200);
  expect((await gradeResponse.json()).score).toEqual({
    correct: 1,
    total: 1,
    fraction: 1,
  });
  await expect(page.getByText(/Score: 100%/)).toBeVisible();

  await page.goto("/flashcards");
  await expect(page.getByLabel("Active course")).toHaveValue(state.aliceCourseId);
  await expect(
    page.getByText(
      "Grounded generation is not enabled on this server. Manual Flashcards remain available.",
    ),
  ).toBeVisible();
  await expect(page.getByLabel("Generated deck title")).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "Review grounded deck request" }),
  ).toBeDisabled();
  await page.getByLabel("New Flashcard deck title").fill("Visible manual deck");
  await page
    .getByRole("heading", { name: "Decks" })
    .locator("..")
    .getByRole("button", { name: "Create", exact: true })
    .click();
  await expect(page.getByRole("heading", { name: "Visible manual deck" })).toBeVisible();
  await page.getByLabel("Flashcard prompt").fill("Mitochondria");
  await page.getByLabel("Flashcard answer").fill("Produces cellular energy");
  await page.getByLabel("Flashcard objective IDs").fill("browser_manual_biology");
  await page.getByRole("button", { name: "Save card" }).click();
  await page.getByRole("button", { name: "Ready", exact: true }).click();
  await page.getByRole("button", { name: "Review due" }).click();
  await expect(page.getByText("Mitochondria", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Reveal answer" }).click();
  await expect(page.getByText("Produces cellular energy", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "good", exact: true }).click();
  await expect(
    page.getByText("Review complete. Your schedule is saved.", {
      exact: true,
    }),
  ).toBeVisible();
});

test("phase5 stages grounded candidates behind review", async ({ page }) => {
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
  await page.goto("/flashcards");
  await page.getByLabel("Active course").selectOption(state.aliceCourseId);
  await expect(page.getByLabel("Generated deck title")).toBeEnabled();
  await page.getByLabel("Generated deck title").fill("Phase 5 grounded deck");
  await page
    .getByLabel("Flashcard generation focus")
    .fill("Review cellular energy from the selected notes");
  await page.getByLabel("Generated card count").fill("3");
  await page.getByText("Phase 5 browser notes", { exact: true }).click();
  await page
    .getByRole("button", { name: "Review grounded deck request" })
    .click();
  await expect(
    page.getByRole("heading", { name: "Confirm provider use" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Confirm and generate candidates" })
    .click();
  await expect(page.getByRole("status")).toContainText(
    "Grounded Flashcard generation queued.",
  );
  await expect
    .poll(async () => {
      await page.getByRole("button", { name: "Refresh status" }).click();
      return page.getByText("awaiting_review", { exact: true }).count();
    })
    .toBe(1);
  await expect(
    page.getByText(/What bounded fact 1 is represented by source/),
  ).toBeVisible();
  await expect(page.getByText(/Source src_/).first()).toBeVisible();
});

test("phase5 publishes persisted reviewed candidates after restart", async ({
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
  await expect(page.getByText("awaiting_review", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Exclude candidate" }).first().click();
  await expect(page.getByRole("button", { name: /Include again/ })).toHaveCount(
    1,
  );
  await page.getByRole("button", { name: /Include again/ }).click();
  await page.getByRole("button", { name: "Publish selected" }).click();
  await expect(page.getByRole("status")).toContainText(
    "Selected candidates published",
  );
  await expect(
    page.getByRole("heading", { name: "Phase 5 grounded deck" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Review due" }).click();
  await expect(
    page.getByText(/What bounded fact 1 is represented by source/),
  ).toBeVisible();
});
