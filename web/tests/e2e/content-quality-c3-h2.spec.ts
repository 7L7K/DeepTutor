import { expect, test, type Page } from "@playwright/test";
import { chmodSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

type H2Fixture = {
  owner_identity: string;
  foreign_identity: string;
  course_id: string;
  foreign_course_id: string;
  practice_set_id: string;
  revision_id: string;
  short_question_id: string;
  choice_question_id: string;
  course_title: string;
  foreign_course_title: string;
  practice_title: string;
  source_title: string;
  short_prompt: string;
  short_canonical_answer: string;
  short_browser_answer: string;
  choice_prompt: string;
  choice_option_texts: string[];
  choice_correct_text: string;
  choice_selected_text: string;
  choice_explanation: string;
  partial_practice_title: string;
  partial_practice_set_id: string;
  partial_revision_id: string;
  partial_invalidated_question_id: string;
  partial_valid_question_id: string;
  partial_invalidated_prompt: string;
  partial_valid_prompt: string;
};

type AttemptProjection = {
  attempt: {
    id: string;
    state: string;
    course_write_epoch: number;
    practice_set_write_epoch: number;
    score: { correct: number; total: number; fraction: number } | null;
  };
  items: Array<{
    id: string;
    question_id: string;
    option_order: string[] | null;
  }>;
  answers: Array<{
    attempt_item_id: string;
    response: { answer?: string; option_id?: string } | null;
    revision: number;
  }>;
};

const fixtureFile = process.env.H2_FIXTURE_FILE;
const browserStateFile = process.env.H2_BROWSER_STATE_FILE;
const evidenceDir = process.env.H2_EVIDENCE_DIR;
const ownerPassword = process.env.H2_OWNER_PASSWORD;
const foreignPassword = process.env.H2_FOREIGN_PASSWORD;
const phase = process.env.H2_PHASE ?? "campaign";

function fixture(): H2Fixture {
  if (!fixtureFile) throw new Error("H2_FIXTURE_FILE is required");
  return JSON.parse(readFileSync(fixtureFile, "utf8")) as H2Fixture;
}

function writeState(value: Record<string, unknown>) {
  if (!browserStateFile) throw new Error("H2_BROWSER_STATE_FILE is required");
  writeFileSync(browserStateFile, `${JSON.stringify(value, null, 2)}\n`, {
    encoding: "utf8",
    mode: 0o600,
  });
  chmodSync(browserStateFile, 0o600);
}

function readState(): Record<string, unknown> {
  if (!browserStateFile) throw new Error("H2_BROWSER_STATE_FILE is required");
  return JSON.parse(readFileSync(browserStateFile, "utf8")) as Record<string, unknown>;
}

async function screenshot(page: Page, name: string) {
  if (!evidenceDir) return;
  await page.screenshot({
    path: join(evidenceDir, "screenshots", `${name}.png`),
    fullPage: true,
  });
}

async function settleClosedMobileSidebar(page: Page) {
  await expect(
    page.getByRole("button", { name: "Open navigation" }),
  ).toBeVisible();
  await page.waitForTimeout(250);
  const drawer = await page
    .getByRole("complementary")
    .filter({ has: page.getByRole("navigation") })
    .evaluate((sidebar) => ({
      right: sidebar.getBoundingClientRect().right,
      inert: sidebar.parentElement?.hasAttribute("inert") ?? false,
    }));
  expect(drawer.inert).toBe(true);
  expect(drawer.right).toBeLessThanOrEqual(1);
}

async function signIn(page: Page, username: string, password: string) {
  await page.goto("/login");
  await page.getByLabel("Email or username").fill(username);
  await page.getByLabel("Password").fill(password);
  const response = page.waitForResponse(
    (candidate) =>
      candidate.url().includes("/api/v1/auth/login") &&
      candidate.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  expect((await response).status()).toBe(200);
  await page.waitForURL((url) => !url.pathname.startsWith("/login"));
}

async function attemptProjection(
  page: Page,
  proof: H2Fixture,
  attemptId: string,
): Promise<{ status: number; body: AttemptProjection }> {
  return page.evaluate(
    async ({ courseId, practiceSetId, id }) => {
      const response = await fetch(
        `/api/v1/courses/${encodeURIComponent(courseId)}/practice/${encodeURIComponent(practiceSetId)}/attempts/${encodeURIComponent(id)}`,
        { cache: "no-store" },
      );
      return { status: response.status, body: await response.json() };
    },
    {
      courseId: proof.course_id,
      practiceSetId: proof.practice_set_id,
      id: attemptId,
    },
  );
}

function answerFor(view: AttemptProjection, questionId: string) {
  const item = view.items.find((candidate) => candidate.question_id === questionId);
  if (!item) throw new Error(`Missing attempt item for ${questionId}`);
  const answer = view.answers.find(
    (candidate) => candidate.attempt_item_id === item.id,
  );
  if (!answer) throw new Error(`Missing answer row for ${questionId}`);
  return { item, answer };
}

test.describe.configure({ mode: "serial" });

test("owner completes the hermetic bounded mixed assessment", async ({ page }) => {
  test.skip(
    phase !== "campaign" ||
      !ownerPassword ||
      !foreignPassword ||
      !browserStateFile ||
      !evidenceDir,
    "Run the campaign phase through scripts/test-content-quality-c3-h2.",
  );
  const proof = fixture();
  await signIn(page, "c3_h2_owner", ownerPassword!);

  await page.goto(`/classes/${encodeURIComponent(proof.course_id)}/practice`);
  await expect(page.getByRole("heading", { name: "Practice", exact: true })).toBeVisible();
  await expect(page.getByText(`Active Course: ${proof.course_title}`)).toBeVisible();
  await expect(page.getByRole("heading", { name: proof.practice_title })).toBeVisible();

  const preGrade = await page.evaluate(
    async ({ courseId, setId, revisionId }) => {
      const response = await fetch(
        `/api/v1/courses/${encodeURIComponent(courseId)}/practice/${encodeURIComponent(setId)}/revisions/${encodeURIComponent(revisionId)}/questions`,
        { cache: "no-store" },
      );
      return { status: response.status, body: await response.json() };
    },
    {
      courseId: proof.course_id,
      setId: proof.practice_set_id,
      revisionId: proof.revision_id,
    },
  );
  expect(preGrade.status).toBe(200);
  const serializedPreGrade = JSON.stringify(preGrade.body);
  expect(serializedPreGrade).not.toContain('"answer_contract"');
  expect(serializedPreGrade).not.toContain('"correct_option_id"');
  expect(serializedPreGrade).not.toContain('"citations"');
  expect(serializedPreGrade).not.toContain('"explanation"');
  await expect(page.getByText("Correct answer:")).toHaveCount(0);

  await page.getByRole("button", { name: "Start or resume quiz" }).click();
  await expect(page).toHaveURL(/\/attempts\/att_[^/]+$/);
  const primaryAttemptUrl = new URL(page.url()).pathname;
  const primaryAttemptId = decodeURIComponent(primaryAttemptUrl.split("/").at(-1) || "");

  const shortInput = page.getByLabel("Answer for question 1");
  await expect(shortInput).toBeFocused();
  await shortInput.fill(proof.short_browser_answer);

  // Refresh only after autosave is durably acknowledged. A keystroke that has
  // not reached the 500 ms debounce is intentionally not called saved.
  await expect(page.getByRole("status").filter({ hasText: "Saved" })).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("Answer for question 1")).toHaveValue(
    proof.short_browser_answer,
  );

  await page.getByRole("button", { name: /Go to question 2/ }).click();
  const radios = page.getByRole("radio");
  await expect(radios).toHaveCount(proof.choice_option_texts.length);
  const optionTexts = await radios.evaluateAll((nodes) =>
    nodes.map((node) => node.parentElement?.textContent?.trim() ?? ""),
  );
  expect([...optionTexts].sort()).toEqual([...proof.choice_option_texts].sort());
  const optionIds = await radios.evaluateAll((nodes) =>
    nodes.map((node) => (node as HTMLInputElement).value),
  );
  expect(new Set(optionIds).size).toBe(optionIds.length);
  for (const optionId of optionIds) {
    expect(optionId).toMatch(/^opt_[0-9a-f]{32}$/);
    expect(optionId).not.toMatch(/correct|wrong|answer|distractor/i);
  }

  const selectedIndex = optionTexts.indexOf(proof.choice_selected_text);
  expect(selectedIndex).toBeGreaterThanOrEqual(0);
  await radios.first().focus();
  await expect(radios.first()).toBeFocused();
  const choiceSave = page.waitForResponse(
    (response) =>
      response.url().includes(`/attempts/${primaryAttemptId}`) &&
      response.request().method() === "PATCH",
  );
  if (selectedIndex === 0) {
    await page.keyboard.press("Space");
  } else {
    for (let index = 0; index < selectedIndex; index += 1) {
      await page.keyboard.press("ArrowDown");
    }
  }
  expect((await choiceSave).status()).toBe(200);
  await expect(radios.nth(selectedIndex)).toBeChecked();
  await expect(page.getByRole("status").filter({ hasText: "Saved" })).toBeVisible();

  await page.reload();
  await page.getByRole("button", { name: /Go to question 2, answered/ }).click();
  const reloadedRadios = page.getByRole("radio");
  expect(
    await reloadedRadios.evaluateAll((nodes) =>
      nodes.map((node) => node.parentElement?.textContent?.trim() ?? ""),
    ),
  ).toEqual(optionTexts);
  await expect(reloadedRadios.nth(selectedIndex)).toBeChecked();

  const beforeTamper = await attemptProjection(page, proof, primaryAttemptId);
  expect(beforeTamper.status).toBe(200);
  const choice = answerFor(beforeTamper.body, proof.choice_question_id);
  const tamperedOptionId = `opt_${"f".repeat(32)}`;
  expect(optionIds).not.toContain(tamperedOptionId);
  const tamper = await page.evaluate(
    async ({ courseId, setId, attempt, itemId, revision, optionId }) => {
      const response = await fetch(
        `/api/v1/courses/${encodeURIComponent(courseId)}/practice/${encodeURIComponent(setId)}/attempts/${encodeURIComponent(attempt.id)}`,
        {
          method: "PATCH",
          headers: {
            "Content-Type": "application/json",
            "Idempotency-Key": crypto.randomUUID(),
          },
          body: JSON.stringify({
            attempt_item_id: itemId,
            response: { option_id: optionId },
            expected_answer_revision: revision,
            expected_course_write_epoch: attempt.course_write_epoch,
            expected_practice_set_write_epoch: attempt.practice_set_write_epoch,
          }),
        },
      );
      return { status: response.status, body: await response.json() };
    },
    {
      courseId: proof.course_id,
      setId: proof.practice_set_id,
      attempt: beforeTamper.body.attempt,
      itemId: choice.item.id,
      revision: choice.answer.revision,
      optionId: tamperedOptionId,
    },
  );
  expect([409, 422]).toContain(tamper.status);
  const afterTamper = await attemptProjection(page, proof, primaryAttemptId);
  expect(answerFor(afterTamper.body, proof.choice_question_id).answer.response).toEqual(
    choice.answer.response,
  );

  const submitResponse = page.waitForResponse(
    (response) =>
      response.url().endsWith(`/attempts/${primaryAttemptId}/submit`) &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Submit quiz" }).click();
  expect((await submitResponse).status()).toBe(200);
  await expect(page.getByText("Your answers are submitted and locked.")).toBeVisible();

  const submitted = await attemptProjection(page, proof, primaryAttemptId);
  const duplicateSubmitStatus = await page.evaluate(
    async ({ courseId, setId, attempt }) => {
      const response = await fetch(
        `/api/v1/courses/${encodeURIComponent(courseId)}/practice/${encodeURIComponent(setId)}/attempts/${encodeURIComponent(attempt.id)}/submit`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            expected_course_write_epoch: attempt.course_write_epoch,
            expected_practice_set_write_epoch: attempt.practice_set_write_epoch,
          }),
        },
      );
      return response.status;
    },
    {
      courseId: proof.course_id,
      setId: proof.practice_set_id,
      attempt: submitted.body.attempt,
    },
  );
  expect([200, 409]).toContain(duplicateSubmitStatus);

  const gradeResponse = page.waitForResponse(
    (response) =>
      response.url().endsWith(`/attempts/${primaryAttemptId}/grade`) &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Grade quiz" }).click();
  expect((await gradeResponse).status()).toBe(200);
  await expect(page.getByRole("heading", { name: "Quiz results" })).toBeVisible();
  await expect(page.getByText("1 correct out of 2", { exact: true })).toBeVisible();

  const shortResult = page.getByRole("article").filter({ hasText: proof.short_prompt });
  const choiceResult = page.getByRole("article").filter({ hasText: proof.choice_prompt });
  await expect(shortResult).toContainText(proof.short_browser_answer.trim());
  await expect(shortResult).toContainText(proof.short_canonical_answer);
  await expect(choiceResult).toContainText(proof.choice_selected_text);
  await expect(choiceResult).toContainText(proof.choice_correct_text);
  await expect(choiceResult).toContainText(proof.choice_explanation);
  await expect(choiceResult.getByText(proof.source_title, { exact: true })).toBeVisible();
  await expect(choiceResult.getByText("Your answer:", { exact: true })).toBeVisible();
  await expect(choiceResult.getByText("Correct answer:", { exact: true })).toBeVisible();
  await expect(choiceResult.getByText("Why:", { exact: true })).toBeVisible();
  await expect(choiceResult.getByText("Citations:", { exact: true })).toBeVisible();

  const reports: Record<string, string> = {};
  for (const [key, article] of [
    ["short", shortResult],
    ["choice", choiceResult],
  ] as const) {
    const responsePromise = page.waitForResponse(
      (response) =>
        response.url().includes("/quality-report") &&
        response.request().method() === "POST",
    );
    await article.getByRole("button", { name: "Report a problem with this question" }).click();
    const response = await responsePromise;
    expect(response.status()).toBe(201);
    reports[key] = (await response.json()).id as string;
  }
  await screenshot(page, "desktop-graded-results");

  await page.goto(primaryAttemptUrl);
  await expect(page.getByRole("heading", { name: "Quiz results" })).toBeVisible();
  await expect(page.getByText("1 correct out of 2", { exact: true })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await settleClosedMobileSidebar(page);
  await screenshot(page, "narrow-mobile-graded-results");

  // A second attempt proves an acknowledged save survives unmount and remains
  // durable when the attempt is later abandoned.
  await page.getByRole("button", { name: "Try quiz again" }).click();
  await page.waitForURL(
    (url) =>
      /\/attempts\/att_[^/]+$/.test(url.pathname) &&
      url.pathname !== primaryAttemptUrl,
  );
  const cleanupAttemptUrl = new URL(page.url()).pathname;
  const cleanupAttemptId = decodeURIComponent(cleanupAttemptUrl.split("/").at(-1) || "");
  expect(cleanupAttemptId).not.toBe(primaryAttemptId);
  const cleanupInput = page.getByLabel("Answer for question 1");
  await cleanupInput.fill(proof.short_browser_answer);
  await expect(page.getByRole("status").filter({ hasText: "Saved" })).toBeVisible();
  await page.goto(`/classes/${encodeURIComponent(proof.course_id)}`);
  await page.goto(cleanupAttemptUrl);
  await expect(page.getByLabel("Answer for question 1")).toHaveValue(
    proof.short_browser_answer,
  );
  await page.getByLabel("Answer for question 1").fill("Conversion of pyruvate to acetyl-CoA.");
  await expect(page.getByRole("status").filter({ hasText: "Saved" })).toBeVisible();
  await page.getByRole("button", { name: "Leave this attempt" }).click();
  const abandonResponse = page.waitForResponse(
    (response) =>
      response.url().endsWith(`/attempts/${cleanupAttemptId}/abandon`) &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Yes, abandon" }).click();
  expect((await abandonResponse).status()).toBe(200);
  const abandoned = await attemptProjection(page, proof, cleanupAttemptId);
  expect(abandoned.body.attempt.state).toBe("abandoned");
  expect(answerFor(abandoned.body, proof.short_question_id).answer.response).toEqual({
    answer: "Conversion of pyruvate to acetyl-CoA.",
  });

  const graded = await attemptProjection(page, proof, primaryAttemptId);
  writeState({
    primaryAttemptId,
    primaryAttemptUrl,
    cleanupAttemptId,
    reportIds: reports,
    optionOrder: optionIds,
    selectedOptionId: (choice.answer.response as { option_id: string }).option_id,
    duplicateSubmitStatus,
    rawScore: graded.body.attempt.score,
    mainPhase: "complete",
  });
});

test("foreign account cannot open the owner Course or attempt", async ({ page }) => {
  test.skip(
    phase !== "campaign" || !foreignPassword || !browserStateFile || !evidenceDir,
    "Run the campaign phase through scripts/test-content-quality-c3-h2.",
  );
  const proof = fixture();
  const state = readState();
  await signIn(page, "c3_h2_foreign", foreignPassword!);
  await page.goto(String(state.primaryAttemptUrl));
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(page.getByText(proof.course_title, { exact: true })).toHaveCount(0);
  const apiStatus = await page.evaluate(async (courseId) => {
    const response = await fetch(`/api/v1/courses/${encodeURIComponent(courseId)}`, {
      cache: "no-store",
    });
    return response.status;
  }, proof.course_id);
  expect(apiStatus).toBe(404);
  await page.goto(`/classes/${encodeURIComponent(proof.foreign_course_id)}`);
  await expect(page.getByRole("heading", { name: proof.foreign_course_title })).toBeVisible();
  await screenshot(page, "foreign-course-denial");
  writeState({ ...state, foreignCourseStatus: apiStatus });
});

test("invalidated Results withdraw all learner answer authority and handle zero-of-zero", async ({
  page,
}) => {
  test.skip(
    phase !== "corrected" || !ownerPassword || !browserStateFile || !evidenceDir,
    "Run the corrected phase through scripts/test-content-quality-c3-h2.",
  );
  const proof = fixture();
  const state = readState();
  await signIn(page, "c3_h2_owner", ownerPassword!);
  await page.goto(String(state.primaryAttemptUrl));
  await expect(page.getByRole("heading", { name: "Quiz results" })).toBeVisible();
  await expect(
    page.getByText("No scored questions remain after review", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("You got every question correct.", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("article")).toHaveCount(2);
  await expect(page.getByText("Your answer:", { exact: true })).toHaveCount(2);
  await expect(page.getByText("Correct answer:", { exact: true })).toHaveCount(0);
  await expect(page.getByText("Why:", { exact: true })).toHaveCount(0);
  await expect(page.getByText("Citations:", { exact: true })).toHaveCount(0);
  await expect(page.getByText(/invalidated|withdrawn|excluded/i).first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Reported and withdrawn" })).toHaveCount(2);
  await expect(page.getByRole("button", { name: "Reported and withdrawn" }).first()).toBeDisabled();
  await expect(page.getByRole("button", { name: "Try quiz again" })).toHaveCount(0);

  const projection = await page.evaluate(
    async ({ courseId, setId, attemptId }) => {
      const response = await fetch(
        `/api/v1/courses/${encodeURIComponent(courseId)}/practice/${encodeURIComponent(setId)}/attempts/${encodeURIComponent(attemptId)}/results`,
        { cache: "no-store" },
      );
      return { status: response.status, body: await response.json() };
    },
    {
      courseId: proof.course_id,
      setId: proof.practice_set_id,
      attemptId: String(state.primaryAttemptId),
    },
  );
  expect(projection.status).toBe(200);
  expect(projection.body.effective_score).toEqual({ correct: 0, total: 0, fraction: 0 });
  expect(projection.body.attempt.score).toBeNull();
  expect(projection.body.items).toHaveLength(2);
  expect(projection.body.answers).toHaveLength(2);
  expect(projection.body.questions).toHaveLength(2);
  for (const item of projection.body.items) {
    expect(item.content_quality).toBe("invalidated");
    expect(item.grading).toBeNull();
    expect(item.error_type).toBeNull();
  }
  for (const question of projection.body.questions) {
    expect(question.content_quality).toBe("invalidated");
    expect(question).not.toHaveProperty("answer_contract");
    expect(question).not.toHaveProperty("explanation");
    expect(question).not.toHaveProperty("citations");
  }
  expect(projection.body.content_quality.invalidated_question_ids.sort()).toEqual(
    [proof.short_question_id, proof.choice_question_id].sort(),
  );
  await screenshot(page, "desktop-withdrawn-zero-of-zero-results");
  await page.setViewportSize({ width: 390, height: 844 });
  await settleClosedMobileSidebar(page);
  await screenshot(page, "narrow-mobile-withdrawn-zero-of-zero-results");
  writeState({ ...state, correctedProjectionStatus: projection.status });
});

test("invalidated revisions admit only trustworthy questions and fail closed at zero", async ({
  page,
}) => {
  test.skip(
    phase !== "admission" || !ownerPassword || !browserStateFile || !evidenceDir,
    "Run the admission phase through scripts/test-content-quality-c3-h2.",
  );
  const proof = fixture();
  const state = readState();
  await signIn(page, "c3_h2_owner", ownerPassword!);
  await page.goto(`/classes/${encodeURIComponent(proof.course_id)}/practice`);

  await page.getByRole("button", { name: new RegExp(proof.partial_practice_title) }).click();
  await expect(page.getByRole("heading", { name: proof.partial_practice_title })).toBeVisible();
  await expect(page.getByText("Ready for quiz attempts", { exact: true })).toBeVisible();
  await expect(
    page.getByRole("listitem").filter({ hasText: proof.partial_invalidated_prompt }),
  ).toBeVisible();
  await expect(
    page.getByRole("listitem").filter({ hasText: proof.partial_valid_prompt }),
  ).toBeVisible();
  await expect(page.getByText("Withdrawn after review", { exact: true })).toHaveCount(1);

  await page.getByRole("button", { name: "Start or resume quiz" }).click();
  await expect(page).toHaveURL(/\/attempts\/att_[^/]+$/);
  const partialAttemptId = decodeURIComponent(new URL(page.url()).pathname.split("/").at(-1) || "");
  const partialProjection = await attemptProjection(page, {
    ...proof,
    practice_set_id: proof.partial_practice_set_id,
  }, partialAttemptId);
  expect(partialProjection.status).toBe(200);
  expect(partialProjection.body.items.map((item) => item.question_id)).toEqual([
    proof.partial_valid_question_id,
  ]);
  expect(partialProjection.body.items.map((item) => item.question_id)).not.toContain(
    proof.partial_invalidated_question_id,
  );
  await expect(page.getByText(proof.partial_valid_prompt, { exact: true })).toBeVisible();
  await expect(page.getByText(proof.partial_invalidated_prompt, { exact: true })).toHaveCount(0);
  await screenshot(page, "desktop-partial-invalidation-admission");

  await page.getByRole("button", { name: "Leave this attempt" }).click();
  await page.getByRole("button", { name: "Yes, abandon" }).click();
  await expect(page.getByText("Quiz abandoned.", { exact: true })).toBeVisible();

  await page.goto(`/classes/${encodeURIComponent(proof.course_id)}/practice`);
  await page.getByRole("button", { name: new RegExp(proof.practice_title) }).click();
  await expect(page.getByRole("heading", { name: proof.practice_title })).toBeVisible();
  await expect(page.getByText("No trustworthy questions remain", { exact: true })).toBeVisible();
  await expect(page.getByText("Ready for quiz attempts", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Start or resume quiz" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Create successor revision" })).toBeVisible();

  const rejected = await page.evaluate(
    async ({ courseId, setId, revisionId }) => {
      const [courseResponse, setResponse] = await Promise.all([
        fetch(`/api/v1/courses/${encodeURIComponent(courseId)}`, { cache: "no-store" }),
        fetch(
          `/api/v1/courses/${encodeURIComponent(courseId)}/practice/${encodeURIComponent(setId)}`,
          { cache: "no-store" },
        ),
      ]);
      const course = await courseResponse.json();
      const practiceSet = await setResponse.json();
      const response = await fetch(
        `/api/v1/courses/${encodeURIComponent(courseId)}/practice/${encodeURIComponent(setId)}/attempts`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            practice_set_revision_id: revisionId,
            expected_course_write_epoch: course.write_epoch,
            expected_practice_set_write_epoch: practiceSet.write_epoch,
          }),
        },
      );
      return { status: response.status, body: await response.json() };
    },
    {
      courseId: proof.course_id,
      setId: proof.practice_set_id,
      revisionId: proof.revision_id,
    },
  );
  expect(rejected).toEqual({ status: 409, body: { detail: "no_valid_questions" } });
  await screenshot(page, "desktop-no-trustworthy-questions");
  await page.setViewportSize({ width: 390, height: 844 });
  await settleClosedMobileSidebar(page);
  await screenshot(page, "narrow-mobile-no-trustworthy-questions");
  writeState({
    ...state,
    partialAttemptId,
    partialAdmissionItemCount: partialProjection.body.items.length,
    fullAdmissionStatus: rejected.status,
    fullAdmissionReason: rejected.body.detail,
  });
});
