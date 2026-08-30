import { expect, test, type Browser, type BrowserContext, type Page } from "@playwright/test";
import { createHash } from "node:crypto";
import { chmodSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const harnessEnabled = process.env.D3_HARNESS === "1";
const phase = process.env.D3_PHASE;
const runId = process.env.D3_RUN_ID;
const evidenceDir = process.env.D3_EVIDENCE_DIR;
const frontendUrl = process.env.WEB_BASE_URL;
const backendUrl = process.env.D3_BACKEND_URL;
const learnerA = {
  actor: "learner_a",
  username: process.env.D3_LEARNER_A_USERNAME,
  password: process.env.D3_LEARNER_A_PASSWORD,
};
const learnerB = {
  actor: "learner_b",
  username: process.env.D3_LEARNER_B_USERNAME,
  password: process.env.D3_LEARNER_B_PASSWORD,
};
const FORBIDDEN_LEARNER_NAV_PREFIXES = [
  "/admin",
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
  "/settings/agents",
  "/settings/memory",
] as const;

if (
  !harnessEnabled ||
  !["repair", "pre", "interrupt"].includes(phase || "") ||
  !runId ||
  !evidenceDir ||
  !frontendUrl ||
  !backendUrl ||
  !learnerA.username ||
  !learnerA.password ||
  !learnerB.username ||
  !learnerB.password
) {
  throw new Error("Day 3 repair/pre proof must run through scripts/test-day3-school-loop.");
}

type Actor = "learner_a" | "learner_b";
type RequestEvidence = {
  phase: "repair" | "pre" | "interrupt";
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
type ResourceState = {
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
type Evidence = NetworkEvidence & {
  schemaVersion: 1;
  phase: "pre";
  runId: string;
  concurrentContexts: true;
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
  resources: Record<Actor, ResourceState>;
  generationOperationCounts: Record<Actor, { practice: number; flashcards: number }>;
};
type RepairCheckpoint = NetworkEvidence & {
  schemaVersion: 1;
  phase: "repair";
  runId: string;
  concurrentContexts: true;
  requests: RequestEvidence[];
  consoleErrors: Array<{ actor: Actor; text: string }>;
  pageErrors: Array<{ actor: Actor; text: string }>;
  auth: Evidence["auth"];
  courses: Record<
    Actor,
    {
      id: string;
      title: string;
      initialWriteEpoch: number;
      manualPracticeSetId?: string;
      study: {
        courseWriteEpoch: number;
        practice: ResourceState["practice"];
        flashcards: ResourceState["flashcards"];
        generationCounts: { practice: number; flashcards: number };
        generationCapabilities: {
          practice_generation: false;
          flashcard_generation: false;
          grounded_generation: false;
        };
      };
    }
  >;
  uiProofs: {
    manualPracticeDraftEditor: boolean;
    nonReadyChatBanner: Record<Actor, boolean>;
    chatShellPresent: Record<Actor, boolean>;
    learnerSafeNavigation: Record<Actor, boolean>;
  };
  authoringBoundary: {
    courseCreation: "browser-ui";
    practiceDraftEntry: "browser-ui";
    practiceQuestionAuthoring: "authenticated-course-api";
    flashcardDeckCardAuthoring: "authenticated-course-api";
    practiceAttemptLifecycle: "browser-ui";
    flashcardReview: "browser-ui";
  };
};
type InterruptCheckpoint = NetworkEvidence & {
  schemaVersion: 1;
  phase: "interrupt";
  runId: string;
  concurrentContexts: true;
  requests: RequestEvidence[];
  consoleErrors: Array<{ actor: Actor; text: string }>;
  pageErrors: Array<{ actor: Actor; text: string }>;
  auth: Evidence["auth"];
  sources: Record<
    Actor,
    { courseId: string; id: string; displayName: string; state: "processing"; fileSha256: string }
  >;
};

function sha256(value: string | Buffer): string {
  return createHash("sha256").update(value).digest("hex");
}

function stableJson(value: unknown): string {
  if (Array.isArray(value)) return "[" + value.map(stableJson).join(",") + "]";
  if (value && typeof value === "object") {
    return (
      "{" +
      Object.entries(value as Record<string, unknown>)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, item]) => JSON.stringify(key) + ":" + stableJson(item))
        .join(",") +
      "}"
    );
  }
  return JSON.stringify(value);
}

async function observePage(
  page: Page,
  actor: Actor,
  evidence: NetworkEvidence & {
    requests: RequestEvidence[];
    consoleErrors: Array<{ actor: Actor; text: string }>;
    pageErrors: Array<{ actor: Actor; text: string }>;
  },
) {
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
    const url = new URL(response.url());
    if (!url.pathname.startsWith("/api/v1/")) return;
    evidence.requests.push({
      phase: phase as "repair" | "pre" | "interrupt",
      actor,
      method: response.request().method(),
      path: url.pathname,
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
        phase: phase as "repair" | "pre" | "interrupt",
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
    if (message.type() === "error") {
      evidence.consoleErrors.push({ actor, text: message.text() });
    }
  });
  page.on("pageerror", (error) => {
    evidence.pageErrors.push({ actor, text: error.message });
  });
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

function createObservedTransitions(page: Page, observation: PageObservation) {
  return {
    settle: observation.waitForHttpQuiescence,
    async goto(path: string) {
      await observation.waitForHttpQuiescence();
      await page.goto(path);
    },
    async reload() {
      await observation.waitForHttpQuiescence();
      await page.reload();
    },
  };
}

type ObservedTransitions = ReturnType<typeof createObservedTransitions>;

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

async function authProjection(page: Page) {
  return page.evaluate(async () => {
    const response = await fetch("/api/v1/auth/status", { cache: "no-store" });
    return {
      status: response.status,
      body: (await response.json()) as {
        enabled: boolean;
        authenticated: boolean;
        user_id: string;
        username: string;
        role: string;
        is_admin: boolean;
        avatar: string;
      },
    };
  });
}

async function proveLearnerSafeNavigation(page: Page, transitions: ObservedTransitions) {
  if (new URL(page.url()).pathname !== "/classes") {
    await transitions.goto("/classes");
  }
  await expect(page.getByRole("heading", { name: "Classes", exact: true })).toBeVisible();
  const forbiddenLinks = page.locator(
    FORBIDDEN_LEARNER_NAV_PREFIXES.map((prefix) => `a[href^="${prefix}"]`).join(","),
  );
  await expect(forbiddenLinks).toHaveCount(0);
  await expect(page.getByRole("link", { name: /Admin|User management|Deploy/i })).toHaveCount(0);
}

async function createCourseThroughUi(
  page: Page,
  title: string,
  transitions: ObservedTransitions,
) {
  if (new URL(page.url()).pathname !== "/classes") {
    await transitions.goto("/classes");
  }
  await expect(page.getByRole("heading", { name: "Classes", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Add class", exact: true }).first().click();
  await page.getByLabel("Class title").fill(title);
  const createdResponse = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/api/v1/courses" &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Add class", exact: true }).last().click();
  const response = await createdResponse;
  expect(response.status()).toBe(200);
  const course = (await response.json()) as {
    id: string;
    title: string;
    write_epoch: number;
  };
  expect(course.title).toBe(title);
  await expect(page.getByTestId("course-card-" + course.id)).toBeVisible();
  return course;
}

async function proveManualPracticeUi(
  page: Page,
  courseId: string,
  transitions: ObservedTransitions,
) {
  await transitions.goto("/classes/" + encodeURIComponent(courseId) + "/practice");
  await expect(
    page.getByRole("heading", { name: "Create a manual Practice quiz", exact: true }),
  ).toBeVisible();
  await page.getByLabel("Manual Practice title").fill("Day 3 UI-created manual practice");
  const createdSet = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname ===
        "/api/v1/courses/" + encodeURIComponent(courseId) + "/practice" &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Create manual quiz", exact: true }).click();
  const response = await createdSet;
  expect(response.status()).toBe(200);
  const practiceSet = (await response.json()) as { id: string };
  await expect(page.getByRole("heading", { name: "Continue creating", exact: true })).toBeVisible();
  await expect(page.getByText("Question prompt", { exact: true })).toBeVisible();
  await expect(
    page.getByText("Manual Practice draft created. Add your first question.", { exact: true }),
  ).toBeVisible();
  return practiceSet.id;
}

async function proveNonReadyChatUi(
  page: Page,
  courseId: string,
  transitions: ObservedTransitions,
) {
  await transitions.goto("/classes/" + encodeURIComponent(courseId) + "/chat");
  await expect(page.getByTestId("course-chat-route")).toBeVisible();
  await expect(page.getByTestId("course-chat-readiness-banner")).toBeVisible();
  await expect(page.getByTestId("course-chat-readiness-banner")).toContainText(
    /material|ground/i,
  );
  await expect(page.locator("textarea").last()).toBeVisible();
}

async function repairActorFlow(
  browser: Browser,
  actor: Actor,
  username: string,
  password: string,
  evidence: RepairCheckpoint,
) {
  const context = await browser.newContext();
  const page = await context.newPage();
  const observation = await observePage(page, actor, evidence);
  const transitions = createObservedTransitions(page, observation);
  let hadPrimaryFailure = false;
  try {
    await signIn(page, username, password);
    const auth = await authProjection(page);
    expect(auth.status).toBe(200);
    expect(auth.body.role).toBe("user");
    expect(auth.body.is_admin).toBe(false);
    evidence.auth.push({
      actor,
      username,
      userId: auth.body.user_id,
      role: auth.body.role,
      isAdmin: auth.body.is_admin,
    });
    await proveLearnerSafeNavigation(page, transitions);
    const course = await createCourseThroughUi(page, "Day 3 Shared Biology", transitions);
    await proveNonReadyChatUi(page, course.id, transitions);
    let manualPracticeSetId: string | undefined;
    if (actor === "learner_a") {
      manualPracticeSetId = await proveManualPracticeUi(page, course.id, transitions);
    }
    const marker = "private-" + actor + "-" + runId;
    const study = await createManualStudyLoop(page, course.id, marker);
    const practice = await completePracticeUi(
      page,
      course.id,
      study.practice,
      marker,
      transitions,
    );
    const flashcards = await completeFlashcardReviewUi(
      page,
      course.id,
      study.flashcards,
      transitions,
    );
    await observation.waitForHttpQuiescence();
    return {
      id: course.id,
      title: course.title,
      initialWriteEpoch: course.write_epoch,
      ...(manualPracticeSetId ? { manualPracticeSetId } : {}),
      study: {
        ...study,
        practice,
        flashcards,
      },
    };
  } catch (error) {
    hadPrimaryFailure = true;
    throw error;
  } finally {
    await closeObservedContext(context, observation, hadPrimaryFailure);
  }
}

async function uploadReadySource(
  page: Page,
  courseId: string,
  actor: Actor,
  content: string,
  transitions: ObservedTransitions,
) {
  const displayName = "shared-day3-notes.txt";
  const fileSha256 = sha256(Buffer.from(content, "utf8"));
  await transitions.goto("/classes/" + encodeURIComponent(courseId) + "/materials");
  await expect(page.getByRole("heading", { name: "Materials", exact: true })).toBeVisible();
  const uploadResponse = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname ===
        "/api/v1/courses/" + encodeURIComponent(courseId) + "/sources" &&
      response.request().method() === "POST",
  );
  await page.locator('main input[type="file"]').setInputFiles({
    name: displayName,
    mimeType: "text/plain",
    buffer: Buffer.from(content, "utf8"),
  });
  const response = await uploadResponse;
  expect(response.status()).toBe(202);
  const accepted = (await response.json()) as { id: string; state: string };
  expect(accepted.state).toBe("processing");

  let ready: {
    id: string;
    display_name: string;
    state: string;
    revision: number;
    content_sha256: string;
    manifest: Array<{ path: string; size: number; sha256: string }>;
  } | null = null;
  await expect
    .poll(
      async () => {
        ready = await page.evaluate(async (input) => {
          const item = await fetch(
            "/api/v1/courses/" +
              encodeURIComponent(input.courseId) +
              "/sources/" +
              encodeURIComponent(input.sourceId),
            { cache: "no-store" },
          );
          if (!item.ok) throw new Error("Source poll failed: " + item.status);
          return item.json();
        }, { courseId, sourceId: accepted.id });
        return ready?.state;
      },
      { timeout: 30_000 },
    )
    .toBe("ready");
  expect(ready).not.toBeNull();
  const source = ready!;
  expect(source.display_name).toBe(displayName);
  expect(source.manifest).toHaveLength(1);
  expect(source.manifest[0]?.sha256).toBe(fileSha256);
  const manifestFingerprint = sha256(stableJson(source.manifest));
  expect(source.content_sha256).toBe(manifestFingerprint);
  await transitions.reload();
  await expect(page.getByText(displayName, { exact: true })).toBeVisible();
  await expect(page.getByText("Available to Course Chat and Practice", { exact: true })).toBeVisible();
  return {
    id: source.id,
    displayName,
    state: source.state,
    revision: source.revision,
    contentSha256: source.content_sha256,
    fileSha256,
    manifestFingerprint,
    actor,
  };
}

async function proveGroundedChatUi(
  page: Page,
  courseId: string,
  sourceId: string,
  marker: string,
  transitions: ObservedTransitions,
) {
  let terminalProvider = "";
  page.on("websocket", (socket) => {
    socket.on("framereceived", ({ payload }) => {
      if (typeof payload !== "string") return;
      try {
        const event = JSON.parse(payload) as {
          type?: string;
          metadata?: { provider?: string; status?: string };
        };
        if (event.type === "done" && event.metadata?.status === "completed") {
          terminalProvider = event.metadata.provider || "";
        }
      } catch {
        // Heartbeats and non-JSON transport frames are not proof receipts.
      }
    });
  });
  await transitions.goto("/classes/" + encodeURIComponent(courseId) + "/chat");
  await expect(page.getByTestId("course-chat-route")).toBeVisible();
  const composer = page.locator("textarea").last();
  await expect(composer).toBeVisible();
  await composer.fill("Repeat the private marker from this Course material.");
  const nestedReadiness = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return (
      url.pathname ===
        "/api/v1/courses/" + encodeURIComponent(courseId) + "/chat-readiness" &&
      response.request().method() === "GET"
    );
  });
  const nestedSession = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.pathname.startsWith("/api/v1/sessions/") && response.request().method() === "GET";
  });
  void nestedReadiness.catch(() => undefined);
  void nestedSession.catch(() => undefined);
  await composer.press("Enter");
  await expect(page.getByText(new RegExp("Deterministic course answer:.*" + marker))).toBeVisible({
    timeout: 30_000,
  });
  await expect(page.getByTestId("course-citation-" + sourceId)).toBeVisible();
  await expect.poll(() => terminalProvider).toBe("deterministic-local");
  await expect(page).toHaveURL(new RegExp("/classes/" + courseId + "/chat/[^/]+$"));
  const sessionId = decodeURIComponent(new URL(page.url()).pathname.split("/").at(-1) || "");
  expect(sessionId).not.toBe("");
  const [readinessResponse, sessionResponse] = await Promise.all([
    nestedReadiness,
    nestedSession,
  ]);
  expect(readinessResponse.status()).toBe(200);
  expect(sessionResponse.status()).toBe(200);
  expect(new URL(sessionResponse.url()).pathname).toBe(
    "/api/v1/sessions/" + encodeURIComponent(sessionId),
  );
  const persisted = await page.evaluate(async (id) => {
    const response = await fetch("/api/v1/sessions/" + encodeURIComponent(id), {
      cache: "no-store",
    });
    const body: unknown = await response.json();
    return { status: response.status, body };
  }, sessionId);
  expect(persisted.status).toBe(200);
  expect(persisted.body).toMatchObject({ course_id: courseId });
  expect(JSON.stringify(persisted.body)).toContain(sourceId);
  return {
    sessionId,
    groundedCitationSourceId: sourceId,
    terminalProvider: "deterministic-local" as const,
  };
}

async function createManualStudyLoop(
  page: Page,
  courseId: string,
  marker: string,
) {
  return page.evaluate(async (input) => {
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
        throw new Error(path + " failed: " + response.status + " " + JSON.stringify(body));
      }
      return body as Record<string, any>;
    }
    const root = "/api/v1/courses/" + encodeURIComponent(input.courseId);
    const currentCourse = await request(root);
    const courseProjection = await request("/api/v1/courses");
    const capabilities = courseProjection.capabilities as Record<string, unknown>;
    if (
      capabilities.practice_generation !== false ||
      capabilities.flashcard_generation !== false ||
      capabilities.grounded_generation !== false
    ) {
      throw new Error("Provider-off manual study phase exposed generation capability");
    }
    const practiceSet = await request(root + "/practice", {
      method: "POST",
      body: JSON.stringify({
        title: "Day 3 manual practice",
        expected_course_write_epoch: currentCourse.write_epoch,
      }),
    });
    const revision = await request(
      root + "/practice/" + encodeURIComponent(practiceSet.id) + "/revisions",
      {
        method: "POST",
        body: JSON.stringify({ expected_course_write_epoch: currentCourse.write_epoch }),
      },
    );
    const question = await request(
      root +
        "/practice/" +
        encodeURIComponent(practiceSet.id) +
        "/revisions/" +
        encodeURIComponent(revision.id) +
        "/questions",
      {
        method: "POST",
        body: JSON.stringify({
          question_type: "short_answer",
          prompt: "Recall the private Day 3 marker.",
          options: [],
          answer_contract: { kind: "exact", answer: input.marker },
          explanation: "Manual provider-free Practice evidence.",
          objective_ids: ["day3_manual"],
          expected_course_write_epoch: currentCourse.write_epoch,
        }),
      },
    );
    await request(
      root +
        "/practice/" +
        encodeURIComponent(practiceSet.id) +
        "/revisions/" +
        encodeURIComponent(revision.id) +
        "/ready",
      {
        method: "POST",
        body: JSON.stringify({ expected_course_write_epoch: currentCourse.write_epoch }),
      },
    );
    const readySet = await request(
      root + "/practice/" + encodeURIComponent(practiceSet.id),
    );
    const attemptView = await request(
      root + "/practice/" + encodeURIComponent(practiceSet.id) + "/attempts",
      {
        method: "POST",
        body: JSON.stringify({
          practice_set_revision_id: revision.id,
          expected_course_write_epoch: currentCourse.write_epoch,
          expected_practice_set_write_epoch: readySet.write_epoch,
        }),
      },
    );

    const deck = await request(root + "/flashcards", {
      method: "POST",
      body: JSON.stringify({
        title: "Day 3 manual flashcards",
        expected_course_write_epoch: currentCourse.write_epoch,
      }),
    });
    const card = await request(
      root + "/flashcards/" + encodeURIComponent(deck.id) + "/cards",
      {
        method: "POST",
        body: JSON.stringify({
          prompt: "What is this learner's private marker?",
          answer: input.marker,
          objective_ids: ["day3_manual"],
          expected_deck_revision: deck.revision,
          expected_course_write_epoch: currentCourse.write_epoch,
        }),
      },
    );
    const deckView = await request(
      root + "/flashcards/" + encodeURIComponent(deck.id),
    );
    const readyDeck = await request(
      root + "/flashcards/" + encodeURIComponent(deck.id) + "/ready",
      {
        method: "POST",
        body: JSON.stringify({
          expected_revision: deckView.deck.revision,
          expected_course_write_epoch: currentCourse.write_epoch,
        }),
      },
    );
    const practiceOperations = await request(root + "/practice-generation");
    const flashcardOperations = await request(root + "/flashcard-generation");
    return {
      courseWriteEpoch: currentCourse.write_epoch as number,
      practice: {
        setId: practiceSet.id as string,
        revisionId: revision.id as string,
        questionId: question.id as string,
        attemptId: attemptView.attempt.id as string,
        state: attemptView.attempt.state as "in_progress",
      },
      flashcards: {
        deckId: deck.id as string,
        cardId: card.id as string,
        deckRevision: readyDeck.revision as number,
        cardRevision: card.revision as number,
        state: readyDeck.state as "ready",
      },
      generationCounts: {
        practice: (practiceOperations.operations as unknown[]).length,
        flashcards: (flashcardOperations.operations as unknown[]).length,
      },
      generationCapabilities: {
        practice_generation: false as const,
        flashcard_generation: false as const,
        grounded_generation: false as const,
      },
    };
  }, { courseId, marker });
}

async function completePracticeUi(
  page: Page,
  courseId: string,
  practice: { setId: string; revisionId: string; questionId: string; attemptId: string },
  marker: string,
  transitions: ObservedTransitions,
): Promise<ResourceState["practice"]> {
  const attemptPath =
    "/classes/" +
    encodeURIComponent(courseId) +
    "/practice/" +
    encodeURIComponent(practice.setId) +
    "/attempts/" +
    encodeURIComponent(practice.attemptId);
  await transitions.goto(attemptPath);
  const answer = page.getByLabel("Answer for question 1");
  await expect(answer).toBeVisible();
  const savedResponse = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname.endsWith("/attempts/" + practice.attemptId) &&
      response.request().method() === "PATCH",
  );
  await answer.fill(marker);
  // Reload immediately, before the 500 ms debounce can fire. React cleanup
  // must dispatch the final idempotent keepalive PATCH rather than losing the
  // learner's last keystroke.
  await transitions.reload();
  const saved = await savedResponse;
  expect(saved.status()).toBe(200);
  await expect(page.getByLabel("Answer for question 1")).toHaveValue(marker);
  const submit = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname.endsWith("/attempts/" + practice.attemptId + "/submit") &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Submit quiz", exact: true }).click();
  expect((await submit).status()).toBe(200);
  await expect(page.getByText("Your answers are submitted and locked.", { exact: true })).toBeVisible();
  const grade = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname.endsWith("/attempts/" + practice.attemptId + "/grade") &&
      response.request().method() === "POST",
  );
  const results = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname.endsWith("/attempts/" + practice.attemptId + "/results") &&
      response.request().method() === "GET",
  );
  await page.getByRole("button", { name: "Grade quiz", exact: true }).click();
  expect((await grade).status()).toBe(200);
  expect((await results).status()).toBe(200);
  await expect(page.getByRole("heading", { name: "Results", exact: true })).toBeVisible();
  const resultArticle = page.getByRole("article").filter({
    hasText: "Recall the private Day 3 marker.",
  });
  await expect(resultArticle.getByText("Your answer:", { exact: true })).toBeVisible();
  await expect(resultArticle.getByText("Correct answer:", { exact: true })).toBeVisible();
  await expect(resultArticle).toContainText(marker);
  await transitions.reload();
  await expect(page.getByRole("heading", { name: "Results", exact: true })).toBeVisible();
  return {
    ...practice,
    state: "graded",
    answerSha256: sha256(marker),
    autosaveStatus: 200,
    reloadPersisted: true,
    submitStatus: 200,
    gradeStatus: 200,
    resultsStatus: 200,
    browserResults: true,
  };
}

async function completeFlashcardReviewUi(
  page: Page,
  courseId: string,
  flashcards: {
    deckId: string;
    cardId: string;
    deckRevision: number;
    cardRevision: number;
    state: "ready";
  },
  transitions: ObservedTransitions,
): Promise<ResourceState["flashcards"]> {
  await transitions.goto("/classes/" + encodeURIComponent(courseId) + "/review");
  await page.getByText("Day 3 manual flashcards", { exact: true }).first().click();
  await expect(page.getByRole("heading", { name: "Day 3 manual flashcards", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Start studying", exact: true }).click();
  await page.getByRole("button", { name: "Reveal answer", exact: true }).click();
  const reviewResponse = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname.endsWith(
        "/flashcards/" + flashcards.deckId + "/reviews",
      ) && response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "I knew it", exact: true }).click();
  const response = await reviewResponse;
  expect(response.status()).toBe(200);
  const receipt = (await response.json()) as {
    review: { id: string; review_count: number };
    schedule: { last_review_id: string };
  };
  expect(receipt.review.review_count).toBe(1);
  expect(receipt.schedule.last_review_id).toBe(receipt.review.id);
  await expect(page.getByRole("heading", { name: "Flashcards complete", exact: true })).toBeVisible();
  return {
    ...flashcards,
    reviewId: receipt.review.id,
    reviewCount: 1,
    lastReviewId: receipt.schedule.last_review_id,
    reviewedPreRestart: true,
    browserReview: true,
  };
}

async function actorFlow(
  browser: Browser,
  actor: Actor,
  username: string,
  password: string,
  seededCourse: RepairCheckpoint["courses"][Actor],
  evidence: Evidence,
) {
  const context: BrowserContext = await browser.newContext();
  const page = await context.newPage();
  const observation = await observePage(page, actor, evidence);
  const transitions = createObservedTransitions(page, observation);
  let hadPrimaryFailure = false;
  try {
    await signIn(page, username, password);
    const auth = await authProjection(page);
    expect(auth.status).toBe(200);
    expect(auth.body).toEqual({
      enabled: true,
      authenticated: true,
      user_id: expect.any(String),
      username,
      role: "user",
      is_admin: false,
      avatar: "",
    });
    evidence.auth.push({
      actor,
      username,
      userId: auth.body.user_id,
      role: auth.body.role,
      isAdmin: auth.body.is_admin,
    });

    await transitions.settle();
    const marker = "private-" + actor + "-" + runId;
    const source = await uploadReadySource(
      page,
      seededCourse.id,
      actor,
      "Synthetic Day 3 material for " + marker + ".\n",
      transitions,
    );
    await transitions.settle({ quietMs: 2_500 });
    const chat = await proveGroundedChatUi(
      page,
      seededCourse.id,
      source.id,
      marker,
      transitions,
    );
    await transitions.settle();
    const study = seededCourse.study;
    expect(study.generationCounts).toEqual({ practice: 0, flashcards: 0 });
    return {
      actor,
      username,
      userId: auth.body.user_id,
      course: {
        id: seededCourse.id,
        title: seededCourse.title,
        writeEpoch: study.courseWriteEpoch,
      },
      source,
      chat: {
        ...chat,
        foreignMarkerAbsent: false,
        foreignSourceAbsent: false,
        foreignCitationAbsent: false,
      },
      practice: study.practice,
      flashcards: study.flashcards,
      privateMarkerSha256: sha256(marker),
    } satisfies ResourceState;
  } catch (error) {
    hadPrimaryFailure = true;
    throw error;
  } finally {
    await closeObservedContext(context, observation, hadPrimaryFailure);
  }
}

async function verifyChatIsolation(
  browser: Browser,
  actor: Actor,
  username: string,
  password: string,
  own: ResourceState,
  foreign: ResourceState,
  evidence: Evidence,
) {
  const context = await browser.newContext();
  const page = await context.newPage();
  const observation = await observePage(page, actor, evidence);
  const transitions = createObservedTransitions(page, observation);
  let hadPrimaryFailure = false;
  try {
    await signIn(page, username, password);
    const session = await page.evaluate(async (sessionId) => {
      const response = await fetch("/api/v1/sessions/" + encodeURIComponent(sessionId), {
        cache: "no-store",
      });
      return { status: response.status, body: await response.json() };
    }, own.chat.sessionId);
    expect(session.status).toBe(200);
    const serialized = JSON.stringify(session.body);
    expect(serialized).not.toContain("private-" + foreign.actor + "-" + runId);
    expect(serialized).not.toContain(foreign.source.id);
    own.chat.foreignMarkerAbsent = true;
    own.chat.foreignSourceAbsent = true;
    own.chat.foreignCitationAbsent = true;
    if (new URL(page.url()).pathname !== "/classes") {
      await transitions.goto("/classes");
    }
    await expect(page.getByRole("heading", { name: "Classes", exact: true })).toBeVisible();
    await transitions.settle();
  } catch (error) {
    hadPrimaryFailure = true;
    throw error;
  } finally {
    await closeObservedContext(context, observation, hadPrimaryFailure);
  }
}

if (phase === "repair") {
  test("provider-off UI repairs are visible in two private empty Courses", async ({ browser }) => {
    test.setTimeout(180_000);
    const evidence: RepairCheckpoint = {
      ...emptyNetworkEvidence(),
      schemaVersion: 1,
      phase: "repair",
      runId: runId!,
      concurrentContexts: true,
      requests: [],
      consoleErrors: [],
      pageErrors: [],
      auth: [],
      courses: {} as RepairCheckpoint["courses"],
      uiProofs: {
        manualPracticeDraftEditor: false,
        nonReadyChatBanner: { learner_a: false, learner_b: false },
        chatShellPresent: { learner_a: false, learner_b: false },
        learnerSafeNavigation: { learner_a: false, learner_b: false },
      },
      authoringBoundary: {
        courseCreation: "browser-ui",
        practiceDraftEntry: "browser-ui",
        practiceQuestionAuthoring: "authenticated-course-api",
        flashcardDeckCardAuthoring: "authenticated-course-api",
        practiceAttemptLifecycle: "browser-ui",
        flashcardReview: "browser-ui",
      },
    };
    const [courseA, courseB] = await Promise.all([
      repairActorFlow(
        browser,
        "learner_a",
        learnerA.username!,
        learnerA.password!,
        evidence,
      ),
      repairActorFlow(
        browser,
        "learner_b",
        learnerB.username!,
        learnerB.password!,
        evidence,
      ),
    ]);
    expect(courseA.id).not.toBe(courseB.id);
    expect(courseA.manualPracticeSetId).toEqual(expect.any(String));
    expect(courseA.study.practice.state).toBe("graded");
    expect(courseB.study.practice.state).toBe("graded");
    expect(courseA.study.flashcards.reviewedPreRestart).toBe(true);
    expect(courseB.study.flashcards.reviewedPreRestart).toBe(true);
    expect(courseA.study.generationCapabilities).toEqual({
      practice_generation: false,
      flashcard_generation: false,
      grounded_generation: false,
    });
    expect(courseB.study.generationCapabilities).toEqual(courseA.study.generationCapabilities);
    evidence.courses = { learner_a: courseA, learner_b: courseB };
    evidence.uiProofs.manualPracticeDraftEditor = true;
    evidence.uiProofs.nonReadyChatBanner = { learner_a: true, learner_b: true };
    evidence.uiProofs.chatShellPresent = { learner_a: true, learner_b: true };
    evidence.uiProofs.learnerSafeNavigation = { learner_a: true, learner_b: true };
    expectNetworkClean(evidence);
    expect(evidence.requests.filter((item) => item.failure)).toEqual([]);
    expect(evidence.consoleErrors).toEqual([]);
    expect(evidence.pageErrors).toEqual([]);
    const path = join(evidenceDir!, "day3-school-loop.repair.json");
    writeFileSync(path, JSON.stringify(evidence, null, 2), {
      encoding: "utf8",
      mode: 0o600,
    });
    chmodSync(path, 0o600);
  });
} else if (phase === "pre") {
  test("two learners concurrently complete private school loops before cold restart", async ({
    browser,
  }) => {
    test.setTimeout(120_000);
    const repair = JSON.parse(
      readFileSync(join(evidenceDir!, "day3-school-loop.repair.json"), "utf8"),
    ) as RepairCheckpoint;
    expect(repair.schemaVersion).toBe(1);
    expect(repair.phase).toBe("repair");
    expect(repair.runId).toBe(runId);
    expect(repair.uiProofs).toEqual({
      manualPracticeDraftEditor: true,
      nonReadyChatBanner: { learner_a: true, learner_b: true },
      chatShellPresent: { learner_a: true, learner_b: true },
      learnerSafeNavigation: { learner_a: true, learner_b: true },
    });
    expect(repair.authoringBoundary).toEqual({
      courseCreation: "browser-ui",
      practiceDraftEntry: "browser-ui",
      practiceQuestionAuthoring: "authenticated-course-api",
      flashcardDeckCardAuthoring: "authenticated-course-api",
      practiceAttemptLifecycle: "browser-ui",
      flashcardReview: "browser-ui",
    });
    const evidence: Evidence = {
      ...emptyNetworkEvidence(),
      schemaVersion: 1,
      phase: "pre",
      runId: runId!,
      concurrentContexts: true,
      requests: [],
      consoleErrors: [],
      pageErrors: [],
      auth: [],
      resources: {} as Record<Actor, ResourceState>,
      generationOperationCounts: {
        learner_a: { practice: -1, flashcards: -1 },
        learner_b: { practice: -1, flashcards: -1 },
      },
    };
    const [resourceA, resourceB] = await Promise.all([
      actorFlow(
        browser,
        "learner_a",
        learnerA.username!,
        learnerA.password!,
        repair.courses.learner_a,
        evidence,
      ),
      actorFlow(
        browser,
        "learner_b",
        learnerB.username!,
        learnerB.password!,
        repair.courses.learner_b,
        evidence,
      ),
    ]);
    expect(resourceA.userId).not.toBe(resourceB.userId);
    expect(resourceA.course.id).not.toBe(resourceB.course.id);
    expect(resourceA.source.id).not.toBe(resourceB.source.id);
    expect(resourceA.practice.setId).not.toBe(resourceB.practice.setId);
    expect(resourceA.flashcards.deckId).not.toBe(resourceB.flashcards.deckId);
    expect(resourceA.privateMarkerSha256).not.toBe(resourceB.privateMarkerSha256);
    expect(resourceA.source.fileSha256).not.toBe(resourceB.source.fileSha256);
    expect(resourceA.source.contentSha256).not.toBe(resourceB.source.contentSha256);
    await Promise.all([
      verifyChatIsolation(
        browser,
        "learner_a",
        learnerA.username!,
        learnerA.password!,
        resourceA,
        resourceB,
        evidence,
      ),
      verifyChatIsolation(
        browser,
        "learner_b",
        learnerB.username!,
        learnerB.password!,
        resourceB,
        resourceA,
        evidence,
      ),
    ]);
    evidence.resources.learner_a = resourceA;
    evidence.resources.learner_b = resourceB;
    evidence.generationOperationCounts.learner_a = { practice: 0, flashcards: 0 };
    evidence.generationOperationCounts.learner_b = { practice: 0, flashcards: 0 };
    expectNetworkClean(evidence);
    expect(evidence.requests.filter((item) => item.failure)).toEqual([]);
    expect(evidence.consoleErrors).toEqual([]);
    expect(evidence.pageErrors).toEqual([]);
    for (const actor of ["learner_a", "learner_b"] as const) {
      expect(
        evidence.websockets.some((socket) => socket.actor === actor && socket.path === "/api/v1/ws"),
      ).toBe(true);
    }

    const path = join(evidenceDir!, "day3-school-loop.pre.json");
    writeFileSync(path, JSON.stringify(evidence, null, 2), {
      encoding: "utf8",
      mode: 0o600,
    });
    chmodSync(path, 0o600);
  });
} else {
  test("two live source operations are captured before a controlled cold restart", async ({
    browser,
  }) => {
    test.setTimeout(120_000);
    const pre = JSON.parse(
      readFileSync(join(evidenceDir!, "day3-school-loop.pre.json"), "utf8"),
    ) as Evidence;
    expect(pre).toMatchObject({ schemaVersion: 1, phase: "pre", runId });
    const evidence: InterruptCheckpoint = {
      ...emptyNetworkEvidence(),
      schemaVersion: 1,
      phase: "interrupt",
      runId: runId!,
      concurrentContexts: true,
      requests: [],
      consoleErrors: [],
      pageErrors: [],
      auth: [],
      sources: {} as InterruptCheckpoint["sources"],
    };
    async function capture(
      actor: Actor,
      username: string,
      password: string,
      courseId: string,
    ) {
      const context = await browser.newContext();
      const page = await context.newPage();
      const observation = await observePage(page, actor, evidence);
      const transitions = createObservedTransitions(page, observation);
      let hadPrimaryFailure = false;
      try {
        await signIn(page, username, password);
        const auth = await authProjection(page);
        expect(auth.status).toBe(200);
        evidence.auth.push({
          actor,
          username,
          userId: auth.body.user_id,
          role: auth.body.role,
          isAdmin: auth.body.is_admin,
        });
        const displayName = "interrupted-day3-notes.txt";
        const content = "Interrupted synthetic material for " + actor + " " + runId + ".\n";
        const receipt = await page.evaluate(
          async ({ requestedCourseId, name, body, key }) => {
            const data = new FormData();
            data.append("files", new File([body], name, { type: "text/plain" }));
            data.append("kind", "document");
            data.append("display_name", name);
            const response = await fetch(
              "/api/v1/courses/" + encodeURIComponent(requestedCourseId) + "/sources",
              { method: "POST", headers: { "Idempotency-Key": key }, body: data },
            );
            return { status: response.status, body: await response.json() };
          },
          {
            requestedCourseId: courseId,
            name: displayName,
            body: content,
            key: "d3-interrupt-" + runId + "-" + actor,
          },
        );
        expect(receipt.status).toBe(202);
        expect(receipt.body).toMatchObject({ id: expect.any(String), state: "processing" });
        await transitions.settle();
        return {
          courseId,
          id: String((receipt.body as { id: string }).id),
          displayName,
          state: "processing" as const,
          fileSha256: sha256(content),
        };
      } catch (error) {
        hadPrimaryFailure = true;
        throw error;
      } finally {
        await closeObservedContext(context, observation, hadPrimaryFailure);
      }
    }
    const [sourceA, sourceB] = await Promise.all([
      capture(
        "learner_a",
        learnerA.username!,
        learnerA.password!,
        pre.resources.learner_a.course.id,
      ),
      capture(
        "learner_b",
        learnerB.username!,
        learnerB.password!,
        pre.resources.learner_b.course.id,
      ),
    ]);
    expect(sourceA.id).not.toBe(sourceB.id);
    expect(sourceA.fileSha256).not.toBe(sourceB.fileSha256);
    evidence.sources = { learner_a: sourceA, learner_b: sourceB };
    expectNetworkClean(evidence);
    expect(evidence.requests.filter((item) => item.failure)).toEqual([]);
    expect(evidence.consoleErrors).toEqual([]);
    expect(evidence.pageErrors).toEqual([]);
    const path = join(evidenceDir!, "day3-school-loop.interrupt.json");
    writeFileSync(path, JSON.stringify(evidence, null, 2), { encoding: "utf8", mode: 0o600 });
    chmodSync(path, 0o600);
  });
}
