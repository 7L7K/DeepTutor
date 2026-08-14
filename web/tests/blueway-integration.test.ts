import test from "node:test";
import assert from "node:assert/strict";

import {
  applyBlueWayActionIfCurrent,
  assertCredentialFreePayload,
  blueWayConnectionLabel,
  blueWayPairingErrorMessage,
  blueWayIdentityIsCurrent,
  blueWayResponseIsCurrent,
  blueWaySyncIsRunning,
  safeBlueWayVerificationUri,
  safeBlueWayNativeApprovalUri,
} from "../lib/blueway-integration";

test("BlueWay status keeps connection and indexing readiness separate", () => {
  assert.equal(
    blueWayConnectionLabel({ enabled: true, connection: null, active_run: null }),
    "not_connected",
  );
  assert.equal(
    blueWayConnectionLabel({
      enabled: true,
      connection: {
        id: "bwc_1",
        state: "active",
        revision: 1,
        scope_version: "academic.read.v1",
      },
      active_run: { id: "bwr_1", state: "indexing" },
    }),
    "active",
  );
  assert.equal(blueWaySyncIsRunning({ id: "bwr_1", state: "indexing" }), true);
  assert.equal(blueWaySyncIsRunning({ id: "bwr_1", state: "completed" }), false);
  assert.equal(
    blueWayConnectionLabel({
      enabled: true,
      connection: {
        id: "bwc_1",
        state: "credential_recovery_required",
        revision: 2,
        scope_version: "academic.read.v1",
      },
      active_run: null,
    }),
    "credential_recovery_required",
  );
});

test("delayed BlueWay actions cannot mutate a replacement identity", async () => {
  let finish!: (value: string) => void;
  const delayed = new Promise<string>((resolve) => {
    finish = resolve;
  });
  let currentIdentityEpoch = 7;
  const applied: string[] = [];
  const pending = applyBlueWayActionIfCurrent(
    delayed,
    7,
    () => currentIdentityEpoch,
    (value) => {
      applied.push(value);
    },
  );
  currentIdentityEpoch = 8;
  finish("old-user-result");
  assert.equal(await pending, false);
  assert.deepEqual(applied, []);
});

test("BlueWay responses cannot cross an identity or request epoch", () => {
  assert.equal(blueWayIdentityIsCurrent(4, 4), true);
  assert.equal(blueWayIdentityIsCurrent(3, 4), false);
  assert.equal(blueWayResponseIsCurrent(4, 4, 9, 9), true);
  assert.equal(blueWayResponseIsCurrent(3, 4, 9, 9), false);
  assert.equal(blueWayResponseIsCurrent(4, 4, 8, 9), false);
});

test("pairing completion races become actionable recovery copy", () => {
  assert.equal(
    blueWayPairingErrorMessage(new Error("BlueWay pairing is already being completed")),
    "BlueWay is finishing the previous approval. Wait a moment, then try Stop pairing again.",
  );
  assert.equal(
    blueWayPairingErrorMessage(new Error("BlueWay pairing is already pending")),
    "A BlueWay pairing is already pending. Stop it before starting over.",
  );
  assert.equal(blueWayPairingErrorMessage(new Error("provider unavailable")), "provider unavailable");
});

test("BlueWay approval links require HTTPS except explicit loopback development", () => {
  assert.equal(
    safeBlueWayVerificationUri("https://blueway-teeechr-beta.expo.app/teeechr-connect?request_id=a1b2c3d4-1111-4111-8111-111111111111&user_code=user-code_123"),
    "https://blueway-teeechr-beta.expo.app/teeechr-connect?request_id=a1b2c3d4-1111-4111-8111-111111111111&user_code=user-code_123",
  );
  assert.equal(
    safeBlueWayVerificationUri("http://localhost:54321/connect"),
    "http://localhost:54321/connect",
  );
  assert.equal(safeBlueWayVerificationUri("http://blueway.example/connect"), null);
  assert.equal(safeBlueWayVerificationUri("https://attacker.example/teeechr-connect?request_id=a1b2c3d4-1111-4111-8111-111111111111&user_code=user-code_123"), null);
  assert.equal(safeBlueWayVerificationUri("javascript:alert(1)"), null);
  assert.equal(
    safeBlueWayVerificationUri("https://user:secret@blueway.example/connect"),
    null,
  );
});

test("browser integration payloads reject credential material recursively", () => {
  assert.doesNotThrow(() =>
    assertCredentialFreePayload({
      connection: { id: "bwc_1", state: "active" },
      records: [{ display_name: "Biology" }],
    }),
  );
});

test("verification URIs cannot become arbitrary browser redirects", () => {
  assert.equal(safeBlueWayVerificationUri("https://blueway.gesahni.com/teeechr-connect?request_id=a1b2c3d4-1111-4111-8111-111111111111&user_code=user-code_123"), "https://blueway.gesahni.com/teeechr-connect?request_id=a1b2c3d4-1111-4111-8111-111111111111&user_code=user-code_123");
  assert.equal(safeBlueWayVerificationUri("https://blueway.gesahni.com/teeechr-connect?request_id=a1b2c3d4-1111-4111-8111-111111111111&return_to=https://attacker.example"), null);
  assert.equal(safeBlueWayVerificationUri("https://blueway.gesahni.com/teeechr-connect?request_id=not-a-request&user_code=user-code_123"), null);
  assert.equal(safeBlueWayVerificationUri("https://teeechr.gesahni.com/connect/blueway"), null);
  assert.equal(safeBlueWayVerificationUri("https://user:pass@teeechr.gesahni.com/connect/blueway"), null);
  assert.equal(safeBlueWayVerificationUri("file:///tmp/approval"), null);
});

test("same-phone approval links are bounded to the BlueWay deep-link contract", () => {
  assert.equal(
    safeBlueWayNativeApprovalUri({
      request_id: "a1b2c3d4-1111-4111-8111-111111111111",
      user_code: "user-code_123",
    }),
    "blueway://teeechr-connect?request_id=a1b2c3d4-1111-4111-8111-111111111111&user_code=user-code_123",
  );
  assert.equal(safeBlueWayNativeApprovalUri({ request_id: "short", user_code: "user-code_123" }), null);
  assert.equal(safeBlueWayNativeApprovalUri({ request_id: "a1b2c3d4-1111-4111-8111-111111111111", user_code: "bad code" }), null);
});

for (const [state, expected] of [
  ["queued", true],
  ["fetching", true],
  ["validating", true],
  ["staging", true],
  ["indexing", true],
  ["completed", false],
  ["failed", false],
  ["cancelled", false],
] as const) {
  test(`sync state ${state} maps to ${expected ? "active" : "terminal"}`, () => {
    assert.equal(blueWaySyncIsRunning({ id: `run-${state}`, state }), expected);
  });
}

for (const [state, expected] of [
  ["active", "active"],
  ["credential_recovery_required", "credential_recovery_required"],
  ["revocation_pending", "revocation_pending"],
  ["disconnected", "disconnected"],
  ["error", "error"],
] as const) {
  test(`connection state ${state} remains account status ${expected}`, () => {
    assert.equal(
      blueWayConnectionLabel({
        enabled: true,
        connection: {
          id: `connection-${state}`,
          state,
          revision: 1,
          scope_version: "academic.read.v1",
        },
        active_run: null,
      }),
      expected,
    );
  });
}

for (const [label, value] of [
  ["javascript scheme", "javascript:alert(1)"],
  ["file scheme", "file:///tmp/approval"],
  ["data scheme", "data:text/html,approval"],
  ["plain text", "not a URL"],
  ["credential-bearing URL", "https://user:pass@blueway.example/connect"],
  ["insecure remote URL", "http://blueway.example/connect"],
  ["empty value", ""],
] as const) {
  test(`verification URI rejects ${label}`, () => {
    assert.equal(safeBlueWayVerificationUri(value), null);
  });
}

for (const [label, input] of [
  ["missing request id", { request_id: "", user_code: "user-code_123" }],
  ["short request id", { request_id: "short", user_code: "user-code_123" }],
  ["request id with a scheme", { request_id: "https://attacker.example", user_code: "user-code_123" }],
  ["missing user code", { request_id: "a1b2c3d4-1111-4111-8111-111111111111", user_code: "" }],
  ["short user code", { request_id: "a1b2c3d4-1111-4111-8111-111111111111", user_code: "short" }],
  ["user code with an injected query", { request_id: "a1b2c3d4-1111-4111-8111-111111111111", user_code: "valid&return_to=https://attacker.example" }],
] as const) {
  test(`native approval URI rejects ${label}`, () => {
    assert.equal(safeBlueWayNativeApprovalUri(input), null);
  });
}

for (const key of [
  "access_token",
  "refresh-token",
  "client_secret",
  "master_key",
  "credential_ref",
  "key_id",
  "quarantine_path",
  "staging_path",
  "pkce_verifier",
  "device_code",
]) {
  test(`credential boundary rejects nested ${key}`, () => {
    assert.throws(
      () => assertCredentialFreePayload({ response: [{ nested: { [key]: "must-not-cross" } }] }),
      /credential material/,
    );
  });
}
