import { expect, test, type Browser, type BrowserContext, type Page } from "@playwright/test";
import { chmodSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const runId = process.env.D3_RUN_ID;
const evidenceDir = process.env.D3_EVIDENCE_DIR;
const frontendUrl = process.env.WEB_BASE_URL;
const backendUrl = process.env.D3_BACKEND_URL;
const learnerA = {
  actor: "learner_a" as const,
  username: process.env.D3_LEARNER_A_USERNAME,
  password: process.env.D3_LEARNER_A_PASSWORD,
};
const learnerB = {
  actor: "learner_b" as const,
  username: process.env.D3_LEARNER_B_USERNAME,
  password: process.env.D3_LEARNER_B_PASSWORD,
};

if (
  process.env.D3_HARNESS !== "1" ||
  process.env.D3_PHASE !== "post" ||
  !runId ||
  !evidenceDir ||
  !frontendUrl ||
  !backendUrl ||
  !learnerA.username ||
  !learnerA.password ||
  !learnerB.username ||
  !learnerB.password
) {
  throw new Error("Day 3 post-restart proof must run through scripts/test-day3-school-loop.");
}

type Actor = "learner_a" | "learner_b";
type JsonObject = Record<string, unknown>;
type StoredResource = {
  actor: Actor;
  username: string;
  userId: string;
  course: { id: string; title: string; writeEpoch: number };
  source: {
    id: string;
    displayName: string;
    state: string;
    revision: number;
    contentSha256: string;
    fileSha256: string;
    manifestFingerprint: string;
  };
  chat: {
    sessionId: string;
    groundedCitationSourceId: string;
    terminalProvider: "deterministic-local";
    foreignMarkerAbsent: boolean;
    foreignSourceAbsent: boolean;
    foreignCitationAbsent: boolean;
  };
  practice: {
    setId: string;
    revisionId: string;
    questionId: string;
    attemptId: string;
    state: "graded";
    answerSha256: string;
    autosaveStatus: 200;
    reloadPersisted: true;
    submitStatus: 200;
    gradeStatus: 200;
    resultsStatus: 200;
    browserResults: true;
  };
  flashcards: {
    deckId: string;
    cardId: string;
    deckRevision: number;
    cardRevision: number;
    state: "ready";
    reviewId: string;
    reviewCount: 1;
    lastReviewId: string;
    reviewedPreRestart: true;
    browserReview: true;
  };
  privateMarkerSha256: string;
};
type PreEvidence = {
  schemaVersion: 1;
  phase: "pre";
  runId: string;
  resources: Record<Actor, StoredResource>;
};
type InterruptEvidence = {
  schemaVersion: 1;
  phase: "interrupt";
  runId: string;
  sources: Record<
    Actor,
    { courseId: string; id: string; displayName: string; state: "processing"; fileSha256: string }
  >;
};
type RequestEvidence = {
  phase: "post";
  actor: Actor;
  method: string;
  path: string;
  status?: number;
  failure?: string;
};
type NetworkEvidence = {
  networkPolicy: { httpOrigins: string[]; websocketOrigins: string[] };
  networkViolations: Array<{ actor: Actor; method: string; url: string }>;
  blockedNetworkRequests: Array<{ actor: Actor; method: string; url: string; failure: string }>;
  networkFailures: Array<{ actor: Actor; method: string; url: string; failure: string }>;
  teardownCancellations: Array<{ actor: Actor; method: string; url: string; failure: string }>;
  websockets: Array<{ actor: Actor; url: string; path: string }>;
  websocketViolations: Array<{ actor: Actor; url: string }>;
  websocketErrors: Array<{ actor: Actor; url: string; error: string }>;
  websocketClosures: Array<{
    actor: Actor;
    url: string;
    code: number;
    reason: string;
    wasClean: boolean;
    intentionalShutdown: boolean;
  }>;
};

function emptyNetworkEvidence(): NetworkEvidence {
  const httpOrigins = [...new Set([new URL(frontendUrl!).origin, new URL(backendUrl!).origin])];
  return {
    networkPolicy: {
      httpOrigins,
      websocketOrigins: httpOrigins.map((origin) =>
        origin.replace(/^http:/, "ws:").replace(/^https:/, "wss:"),
      ),
    },
    networkViolations: [],
    blockedNetworkRequests: [],
    networkFailures: [],
    teardownCancellations: [],
    websockets: [],
    websocketViolations: [],
    websocketErrors: [],
    websocketClosures: [],
  };
}

function expectNetworkClean(evidence: NetworkEvidence): void {
  expect(evidence.networkViolations).toEqual([]);
  expect(evidence.blockedNetworkRequests).toEqual([]);
  expect(evidence.networkFailures).toEqual([]);
  for (const cancellation of evidence.teardownCancellations) {
    expect(cancellation.failure).toBe("net::ERR_ABORTED");
  }
  expect(evidence.websocketViolations).toEqual([]);
  expect(evidence.websocketErrors).toEqual([]);
}
type IsolationReceipt = {
  family:
    | "course"
    | "source"
    | "chat"
    | "practice"
    | "attempt"
    | "result"
    | "flashcards"
    | "card"
    | "review-operation";
  foreignPath: string;
  missingPath: string;
  foreignStatus: number;
  missingStatus: number;
  bodiesEqual: boolean;
  body: unknown;
};
type PostEvidence = NetworkEvidence & {
  schemaVersion: 1;
  phase: "post";
  runId: string;
  concurrentContexts: true;
  coldRestartProjection: true;
  requests: RequestEvidence[];
  consoleErrors: Array<{ actor: Actor; text: string }>;
  pageErrors: Array<{ actor: Actor; text: string }>;
  auth: Array<{
    actor: Actor;
    username: string;
    userId: string;
    role: string;
    isAdmin: boolean;
  }>;
  persistence: Record<
    Actor,
    {
      course: true;
      source: true;
      chat: true;
      chatForeignContentAbsent: true;
      practice: true;
      attempt: true;
      flashcards: true;
      review: true;
      interruptedSourceFailed: true;
      browserMaterials: true;
      browserOverview: true;
      browserPractice: true;
      browserResults: true;
      browserFlashcards: true;
      browserReviewReload: true;
    }
  >;
  generationOperationCounts: Record<Actor, { practice: number; flashcards: number }>;
  reviewPersistence: Record<
    Actor,
    { reviewId: string; reviewCount: number; scheduleLastReviewId: string; ownerScoped: true }
  >;
  interruptedSources: Record<
    Actor,
    { id: string; stateBeforeRestart: "processing"; stateAfterRestart: "failed"; browserFailed: true }
  >;
  reviewIdLookupBoundary: "not-externally-addressable";
  isolation: Record<Actor, IsolationReceipt[]>;
};

async function observePage(page: Page, actor: Actor, evidence: PostEvidence) {
  const allowedHttpOrigins = new Set(evidence.networkPolicy.httpOrigins);
  const allowedSocketOrigins = new Set(evidence.networkPolicy.websocketOrigins);
  const activelyBlockedRequests = new WeakSet<object>();
  const intentionalShutdownRequests = new WeakSet<object>();
  const inFlightHttpRequests = new Map<object, { method: string; url: string }>();
  let lastHttpActivityAt = Date.now();
  let intentionalShutdown = false;
  const allowedNetworkUrl = (rawUrl: string) => {
    const url = new URL(rawUrl);
    return url.protocol === "ws:" || url.protocol === "wss:"
      ? allowedSocketOrigins.has(url.origin)
      : allowedHttpOrigins.has(url.origin);
  };
  await page.route("**/*", async (route) => {
    const request = route.request();
    if (allowedNetworkUrl(request.url())) {
      await route.continue();
      return;
    }
    evidence.networkViolations.push({ actor, method: request.method(), url: request.url() });
    activelyBlockedRequests.add(request);
    await route.abort("blockedbyclient");
  });
  await page.routeWebSocket(/.*/, async (route) => {
    const url = new URL(route.url());
    if (allowedSocketOrigins.has(url.origin)) {
      route.connectToServer();
      return;
    }
    evidence.websocketViolations.push({ actor, url: route.url() });
    await route.close({ code: 1008, reason: "Day 3 local-origin policy" });
  });
  await page.exposeFunction(
    "__d3RecordWebSocketClose",
    (payload: { url: string; code: number; reason: string; wasClean: boolean }) => {
      const closure = { actor, ...payload, intentionalShutdown };
      evidence.websocketClosures.push(closure);
      if (!intentionalShutdown && !payload.wasClean && ![1000, 1001].includes(payload.code)) {
        evidence.websocketErrors.push({
          actor,
          url: payload.url,
          error: `abnormal close code=${payload.code} reason=${payload.reason}`,
        });
      }
    },
  );
  await page.addInitScript((callbackName) => {
    const NativeWebSocket = window.WebSocket;
    class ObservedWebSocket extends NativeWebSocket {
      constructor(url: string | URL, protocols?: string | string[]) {
        if (protocols === undefined) super(url);
        else super(url, protocols);
        this.addEventListener("close", (event) => {
          const callback = (window as unknown as Record<string, (value: unknown) => Promise<void>>)[
            callbackName
          ];
          void callback({
            url: this.url,
            code: event.code,
            reason: event.reason,
            wasClean: event.wasClean,
          });
        });
      }
    }
    window.WebSocket = ObservedWebSocket;
  }, "__d3RecordWebSocketClose");
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (!["http:", "https:"].includes(url.protocol) || !allowedHttpOrigins.has(url.origin)) return;
    inFlightHttpRequests.set(request, { method: request.method(), url: request.url() });
    if (intentionalShutdown) intentionalShutdownRequests.add(request);
    lastHttpActivityAt = Date.now();
  });
  page.on("requestfinished", (request) => {
    if (inFlightHttpRequests.delete(request)) lastHttpActivityAt = Date.now();
  });
  page.on("response", (response) => {
    const path = new URL(response.url()).pathname;
    if (!path.startsWith("/api/v1/")) return;
    evidence.requests.push({
      phase: "post",
      actor,
      method: response.request().method(),
      path,
      status: response.status(),
    });
  });
  page.on("requestfailed", (request) => {
    if (inFlightHttpRequests.delete(request)) lastHttpActivityAt = Date.now();
    const url = new URL(request.url());
    const failure = request.failure()?.errorText || "request failed";
    if (
      (intentionalShutdownRequests.has(request) || intentionalShutdown) &&
      failure === "net::ERR_ABORTED"
    ) {
      evidence.teardownCancellations.push({
        actor,
        method: request.method(),
        url: request.url(),
        failure,
      });
      return;
    }
    if (activelyBlockedRequests.has(request) && /blocked_by_client/i.test(failure)) {
      evidence.blockedNetworkRequests.push({
        actor,
        method: request.method(),
        url: request.url(),
        failure,
      });
      return;
    }
    evidence.networkFailures.push({
      actor,
      method: request.method(),
      url: request.url(),
      failure,
    });
    if (url.pathname.startsWith("/api/v1/")) {
      evidence.requests.push({
        phase: "post",
        actor,
        method: request.method(),
        path: url.pathname,
        failure,
      });
    }
  });
  page.on("websocket", (socket) => {
    const url = new URL(socket.url());
    evidence.websockets.push({ actor, url: socket.url(), path: url.pathname });
    if (!allowedSocketOrigins.has(url.origin)) {
      evidence.websocketViolations.push({ actor, url: socket.url() });
    }
    socket.on("socketerror", (error) => {
      evidence.websocketErrors.push({ actor, url: socket.url(), error });
    });
  });
  page.on("console", (message) => {
    if (message.type() === "error") evidence.consoleErrors.push({ actor, text: message.text() });
  });
  page.on("pageerror", (error) => evidence.pageErrors.push({ actor, text: error.message }));
  return {
    async waitForHttpQuiescence({
      quietMs = 750,
      timeoutMs = 12_000,
    }: { quietMs?: number; timeoutMs?: number } = {}) {
      const startedAt = Date.now();
      const deadline = startedAt + timeoutMs;
      while (Date.now() < deadline) {
        const now = Date.now();
        if (
          inFlightHttpRequests.size === 0 &&
          now - Math.max(startedAt, lastHttpActivityAt) >= quietMs
        ) {
          return;
        }
        await new Promise<void>((resolve) => setTimeout(resolve, 50));
      }
      const pending = [...inFlightHttpRequests.values()].sort((left, right) =>
        (left.method + " " + left.url).localeCompare(right.method + " " + right.url),
      );
      throw new Error(
        `Local HTTP did not quiesce for ${actor} within ${timeoutMs}ms; pending=${JSON.stringify(pending)}`,
      );
    },
    markIntentionalShutdown() {
      intentionalShutdown = true;
      for (const request of inFlightHttpRequests.keys()) intentionalShutdownRequests.add(request);
    },
  };
}

type PageObservation = Awaited<ReturnType<typeof observePage>>;

async function closeObservedContext(
  context: BrowserContext,
  observation: PageObservation,
  hadPrimaryFailure: boolean,
) {
  let cleanupFailure: unknown;
  try {
    await observation.waitForHttpQuiescence({ quietMs: 250, timeoutMs: 2_000 });
  } catch (error) {
    cleanupFailure = error;
  }
  observation.markIntentionalShutdown();
  try {
    await context.close();
  } catch (error) {
    cleanupFailure ??= error;
  }
  if (!hadPrimaryFailure && cleanupFailure) throw cleanupFailure;
}

async function signIn(page: Page, username: string, password: string) {
  const authReady = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/api/v1/auth/status" &&
      response.request().method() === "GET",
  );
  await page.goto("/login");
  expect((await authReady).status()).toBe(200);
  await page.getByLabel("Email or username").fill(username);
  await page.getByLabel("Password", { exact: true }).fill(password);
  const sessionsReady = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return (
      url.pathname === "/api/v1/sessions" &&
      url.searchParams.get("limit") === "50" &&
      url.searchParams.get("offset") === "0" &&
      response.request().method() === "GET"
    );
  });
  void sessionsReady.catch(() => undefined);
  const login = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/api/v1/auth/login" &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  expect((await login).status()).toBe(200);
  await expect
    .poll(async () =>
      (await page.context().cookies()).some((cookie) => cookie.name === "dt_token"),
    )
    .toBe(true);
  await page.waitForURL((url) => url.pathname === "/classes");
  expect((await sessionsReady).status()).toBe(200);
}

type BrowserRequestInit = {
  method?: string;
  headers?: Record<string, string>;
  body?: string;
  cache?: RequestCache;
};

async function requestJson(page: Page, path: string, init?: BrowserRequestInit) {
  return page.evaluate(
    async ({ requestPath, requestInit }) => {
      const response = await fetch(requestPath, requestInit);
      const body: unknown = await response.json().catch(() => null);
      return { status: response.status, body };
    },
    { requestPath: path, requestInit: init },
  );
}

async function getOk(page: Page, path: string): Promise<JsonObject> {
  const receipt = await requestJson(page, path, { cache: "no-store" });
  expect(receipt.status, path).toBe(200);
  expect(receipt.body).not.toBeNull();
  return receipt.body as JsonObject;
}

function asObject(value: unknown, label: string): JsonObject {
  expect(value, label).toBeTruthy();
  expect(typeof value, label).toBe("object");
  expect(Array.isArray(value), label).toBe(false);
  return value as JsonObject;
}

function asArray(value: unknown, label: string): unknown[] {
  expect(Array.isArray(value), label).toBe(true);
  return value as unknown[];
}

async function isolationPair(
  page: Page,
  family: IsolationReceipt["family"],
  foreignPath: string,
  missingPath: string,
  init?: BrowserRequestInit,
): Promise<IsolationReceipt> {
  const [foreign, missing] = await Promise.all([
    requestJson(page, foreignPath, { cache: "no-store", ...init }),
    requestJson(page, missingPath, { cache: "no-store", ...init }),
  ]);
  expect(foreign.status, family + " foreign status").toBe(404);
  expect(missing.status, family + " missing status").toBe(404);
  expect(foreign.body, family + " non-oracle body").toEqual(missing.body);
  return {
    family,
    foreignPath,
    missingPath,
    foreignStatus: foreign.status,
    missingStatus: missing.status,
    bodiesEqual: true,
    body: foreign.body,
  };
}

async function actorFlow(
  browser: Browser,
  actor: Actor,
  username: string,
  password: string,
  own: StoredResource,
  foreign: StoredResource,
  interrupted: InterruptEvidence["sources"][Actor],
  evidence: PostEvidence,
) {
  const context = await browser.newContext();
  const page = await context.newPage();
  const observation = await observePage(page, actor, evidence);
  const navigate = async (path: string) => {
    await observation.waitForHttpQuiescence();
    await page.goto(path);
  };
  let hadPrimaryFailure = false;
  try {
    await signIn(page, username, password);
    const authReceipt = await getOk(page, "/api/v1/auth/status");
    expect(authReceipt).toEqual({
      enabled: true,
      authenticated: true,
      user_id: own.userId,
      username,
      role: "user",
      is_admin: false,
      avatar: "",
    });
    evidence.auth.push({ actor, username, userId: own.userId, role: "user", isAdmin: false });

    const root = "/api/v1/courses/" + encodeURIComponent(own.course.id);
    const courses = await getOk(page, "/api/v1/courses");
    const projectedCourses = asArray(courses.courses, "course projection").map((item) =>
      asObject(item, "projected course"),
    );
    expect(projectedCourses.some((item) => item.id === own.course.id)).toBe(true);
    expect(projectedCourses.some((item) => item.id === foreign.course.id)).toBe(false);

    const course = await getOk(page, root);
    expect(course.id).toBe(own.course.id);
    expect(course.title).toBe(own.course.title);
    const source = await getOk(page, root + "/sources/" + encodeURIComponent(own.source.id));
    expect(source).toMatchObject({
      id: own.source.id,
      display_name: own.source.displayName,
      state: "ready",
      content_sha256: own.source.contentSha256,
      revision: own.source.revision,
    });
    const manifest = asArray(source.manifest, "source manifest");
    expect(asObject(manifest[0], "source manifest entry").sha256).toBe(own.source.fileSha256);
    const chatSession = await getOk(
      page,
      "/api/v1/sessions/" + encodeURIComponent(own.chat.sessionId),
    );
    expect(chatSession.course_id).toBe(own.course.id);
    expect(JSON.stringify(chatSession)).toContain(own.chat.groundedCitationSourceId);
    expect(JSON.stringify(chatSession)).not.toContain(
      "private-" + foreign.actor + "-" + runId,
    );
    expect(JSON.stringify(chatSession)).not.toContain(foreign.source.id);

    const practice = await getOk(page, root + "/practice/" + encodeURIComponent(own.practice.setId));
    expect(practice).toMatchObject({ id: own.practice.setId, title: "Day 3 manual practice" });
    const revision = await getOk(
      page,
      root +
        "/practice/" +
        encodeURIComponent(own.practice.setId) +
        "/revisions/" +
        encodeURIComponent(own.practice.revisionId),
    );
    expect(revision).toMatchObject({ id: own.practice.revisionId, state: "ready" });
    const attempt = await getOk(
      page,
      root +
        "/practice/" +
        encodeURIComponent(own.practice.setId) +
        "/attempts/" +
        encodeURIComponent(own.practice.attemptId),
    );
    expect(asObject(attempt.attempt, "practice attempt")).toMatchObject({
      id: own.practice.attemptId,
      state: "graded",
    });
    expect(JSON.stringify(attempt)).toContain(own.practice.questionId);
    const resultsProjection = await getOk(
      page,
      root +
        "/practice/" +
        encodeURIComponent(own.practice.setId) +
        "/attempts/" +
        encodeURIComponent(own.practice.attemptId) +
        "/results",
    );
    expect(asObject(resultsProjection.attempt, "practice results attempt")).toMatchObject({
      id: own.practice.attemptId,
      state: "graded",
    });

    const deckView = await getOk(page, root + "/flashcards/" + encodeURIComponent(own.flashcards.deckId));
    const deck = asObject(deckView.deck, "flashcard deck");
    const cards = asArray(deckView.cards, "flashcards").map((item) => asObject(item, "flashcard"));
    const card = cards.find((item) => item.id === own.flashcards.cardId);
    expect(deck).toMatchObject({
      id: own.flashcards.deckId,
      title: "Day 3 manual flashcards",
      state: "ready",
      revision: own.flashcards.deckRevision,
    });
    expect(card).toMatchObject({
      id: own.flashcards.cardId,
      revision: own.flashcards.cardRevision,
    });
    const reviewProjection = await getOk(
      page,
      root + "/flashcards/" + encodeURIComponent(own.flashcards.deckId) + "/reviews",
    );
    const schedules = asArray(reviewProjection.schedules, "flashcard schedules").map((item) =>
      asObject(item, "flashcard schedule"),
    );
    const schedule = schedules.find((item) => item.card_id === own.flashcards.cardId);
    expect(schedule).toMatchObject({
      card_id: own.flashcards.cardId,
      review_count: 1,
      last_review_id: own.flashcards.reviewId,
    });
    expect(asObject(reviewProjection.review_summary, "review summary")).toMatchObject({
      completed_cards: 1,
      review_count: 1,
    });
    evidence.reviewPersistence[actor] = {
      reviewId: own.flashcards.reviewId,
      reviewCount: 1,
      scheduleLastReviewId: String(schedule!.last_review_id),
      ownerScoped: true,
    };

    const sourceProjection = await getOk(page, root + "/sources");
    const projectedSources = asArray(sourceProjection.sources, "source projection").map((item) =>
      asObject(item, "projected source"),
    );
    expect(
      projectedSources.find((item) => item.id === interrupted.id),
    ).toMatchObject({ id: interrupted.id, state: "failed" });
    evidence.interruptedSources[actor] = {
      id: interrupted.id,
      stateBeforeRestart: "processing",
      stateAfterRestart: "failed",
      browserFailed: true,
    };

    const practiceOperations = await getOk(page, root + "/practice-generation");
    const flashcardOperations = await getOk(page, root + "/flashcard-generation");
    evidence.generationOperationCounts[actor] = {
      practice: asArray(practiceOperations.operations, "practice operations").length,
      flashcards: asArray(flashcardOperations.operations, "flashcard operations").length,
    };
    expect(evidence.generationOperationCounts[actor]).toEqual({ practice: 0, flashcards: 0 });

    await navigate("/classes/" + encodeURIComponent(own.course.id));
    await expect(page.getByTestId("course-overview-dashboard")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Course Overview", exact: true })).toBeVisible();
    await navigate("/classes/" + encodeURIComponent(own.course.id) + "/materials");
    await expect(page.getByText(own.source.displayName, { exact: true })).toBeVisible();
    await expect(page.getByText("Available to Course Chat and Practice", { exact: true })).toBeVisible();
    await expect(page.getByText(interrupted.displayName, { exact: true })).toBeVisible();
    await expect(page.getByText("This material could not be processed.", { exact: true })).toBeVisible();
    await navigate(
      "/classes/" +
        encodeURIComponent(own.course.id) +
        "/chat/" +
        encodeURIComponent(own.chat.sessionId),
    );
    await expect(
      page.getByText(
        new RegExp("Deterministic course answer:.*private-" + actor + "-" + runId),
      ),
    ).toBeVisible();
    await expect(page.getByTestId("course-citation-" + own.source.id)).toBeVisible();
    await navigate("/classes/" + encodeURIComponent(own.course.id) + "/practice");
    await expect(page.getByText("Day 3 manual practice", { exact: true }).first()).toBeVisible();
    await navigate(
      "/classes/" +
        encodeURIComponent(own.course.id) +
        "/practice/" +
        encodeURIComponent(own.practice.setId) +
        "/attempts/" +
        encodeURIComponent(own.practice.attemptId),
    );
    await expect(page.getByRole("heading", { name: "Results", exact: true })).toBeVisible();
    await navigate("/classes/" + encodeURIComponent(own.course.id) + "/review");
    await page.getByText("Day 3 manual flashcards", { exact: true }).first().click();
    await expect(page.getByText("You are caught up", { exact: true })).toBeVisible();
    await observation.waitForHttpQuiescence();
    await page.reload();
    await page.getByText("Day 3 manual flashcards", { exact: true }).first().click();
    await expect(page.getByText("You are caught up", { exact: true })).toBeVisible();

    const missingCourse = "crs_missing_day3";
    const missingSource = "src_missing_day3";
    const missingSession = "session_missing_day3";
    const missingPractice = "ps_missing_day3";
    const missingAttempt = "att_missing_day3";
    const missingDeck = "fcd_missing_day3";
    const missingCard = "card_missing_day3";
    const cardMutation = {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        prompt: "Non-oracle probe",
        answer: "Non-oracle probe",
        objective_ids: [],
        expected_card_revision: own.flashcards.cardRevision,
        expected_deck_revision: own.flashcards.deckRevision,
        expected_course_write_epoch: own.course.writeEpoch,
      }),
    } satisfies BrowserRequestInit;
    const reviewMutation = {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        card_id: own.flashcards.cardId,
        rating: "good",
        idempotency_key: "d3-review-oracle-" + runId + "-" + actor,
        expected_deck_revision: own.flashcards.deckRevision,
        expected_card_revision: own.flashcards.cardRevision,
        expected_course_write_epoch: own.course.writeEpoch,
      }),
    } satisfies BrowserRequestInit;
    evidence.isolation[actor] = await Promise.all([
      isolationPair(
        page,
        "course",
        "/api/v1/courses/" + encodeURIComponent(foreign.course.id),
        "/api/v1/courses/" + missingCourse,
      ),
      isolationPair(
        page,
        "source",
        root + "/sources/" + encodeURIComponent(foreign.source.id),
        root + "/sources/" + missingSource,
      ),
      isolationPair(
        page,
        "chat",
        "/api/v1/sessions/" + encodeURIComponent(foreign.chat.sessionId),
        "/api/v1/sessions/" + missingSession,
      ),
      isolationPair(
        page,
        "practice",
        root + "/practice/" + encodeURIComponent(foreign.practice.setId),
        root + "/practice/" + missingPractice,
      ),
      isolationPair(
        page,
        "attempt",
        root +
          "/practice/" +
          encodeURIComponent(own.practice.setId) +
          "/attempts/" +
          encodeURIComponent(foreign.practice.attemptId),
        root + "/practice/" + encodeURIComponent(own.practice.setId) + "/attempts/" + missingAttempt,
      ),
      isolationPair(
        page,
        "result",
        root +
          "/practice/" +
          encodeURIComponent(own.practice.setId) +
          "/attempts/" +
          encodeURIComponent(foreign.practice.attemptId) +
          "/results",
        root +
          "/practice/" +
          encodeURIComponent(own.practice.setId) +
          "/attempts/" +
          missingAttempt +
          "/results",
      ),
      isolationPair(
        page,
        "flashcards",
        root + "/flashcards/" + encodeURIComponent(foreign.flashcards.deckId),
        root + "/flashcards/" + missingDeck,
      ),
      isolationPair(
        page,
        "card",
        root +
          "/flashcards/" +
          encodeURIComponent(own.flashcards.deckId) +
          "/cards/" +
          encodeURIComponent(foreign.flashcards.cardId),
        root +
          "/flashcards/" +
          encodeURIComponent(own.flashcards.deckId) +
          "/cards/" +
          missingCard,
        cardMutation,
      ),
      isolationPair(
        page,
        "review-operation",
        root + "/flashcards/" + encodeURIComponent(foreign.flashcards.deckId) + "/reviews",
        root + "/flashcards/" + missingDeck + "/reviews",
        reviewMutation,
      ),
    ]);
    evidence.persistence[actor] = {
      course: true,
      source: true,
      chat: true,
      chatForeignContentAbsent: true,
      practice: true,
      attempt: true,
      flashcards: true,
      review: true,
      interruptedSourceFailed: true,
      browserMaterials: true,
      browserOverview: true,
      browserPractice: true,
      browserResults: true,
      browserFlashcards: true,
      browserReviewReload: true,
    };
    await observation.waitForHttpQuiescence();
  } catch (error) {
    hadPrimaryFailure = true;
    throw error;
  } finally {
    await closeObservedContext(context, observation, hadPrimaryFailure);
  }
}

test("cold restart preserves two private learner loops without an ID oracle", async ({ browser }) => {
  test.setTimeout(120_000);
  const pre = JSON.parse(
    readFileSync(join(evidenceDir!, "day3-school-loop.pre.json"), "utf8"),
  ) as PreEvidence;
  expect(pre).toMatchObject({ schemaVersion: 1, phase: "pre", runId });
  const interrupted = JSON.parse(
    readFileSync(join(evidenceDir!, "day3-school-loop.interrupt.json"), "utf8"),
  ) as InterruptEvidence;
  expect(interrupted).toMatchObject({ schemaVersion: 1, phase: "interrupt", runId });
  const evidence: PostEvidence = {
    ...emptyNetworkEvidence(),
    schemaVersion: 1,
    phase: "post",
    runId: runId!,
    concurrentContexts: true,
    coldRestartProjection: true,
    requests: [],
    consoleErrors: [],
    pageErrors: [],
    auth: [],
    persistence: {} as PostEvidence["persistence"],
    generationOperationCounts: {
      learner_a: { practice: -1, flashcards: -1 },
      learner_b: { practice: -1, flashcards: -1 },
    },
    reviewPersistence: {} as PostEvidence["reviewPersistence"],
    interruptedSources: {} as PostEvidence["interruptedSources"],
    reviewIdLookupBoundary: "not-externally-addressable",
    isolation: {} as PostEvidence["isolation"],
  };
  await Promise.all([
    actorFlow(
      browser,
      "learner_a",
      learnerA.username!,
      learnerA.password!,
      pre.resources.learner_a,
      pre.resources.learner_b,
      interrupted.sources.learner_a,
      evidence,
    ),
    actorFlow(
      browser,
      "learner_b",
      learnerB.username!,
      learnerB.password!,
      pre.resources.learner_b,
      pre.resources.learner_a,
      interrupted.sources.learner_b,
      evidence,
    ),
  ]);
  expectNetworkClean(evidence);
  expect(evidence.requests.filter((item) => item.failure)).toEqual([]);
  expect(evidence.consoleErrors).toEqual([]);
  expect(evidence.pageErrors).toEqual([]);
  const path = join(evidenceDir!, "day3-school-loop.post.json");
  writeFileSync(path, JSON.stringify(evidence, null, 2), { encoding: "utf8", mode: 0o600 });
  chmodSync(path, 0o600);
});
