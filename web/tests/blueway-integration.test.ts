import test from "node:test";
import assert from "node:assert/strict";

import {
  applyBlueWayActionIfCurrent,
  assertCredentialFreePayload,
  blueWayConnectionLabel,
  blueWayIdentityIsCurrent,
  blueWayResponseIsCurrent,
  blueWaySyncIsRunning,
  safeBlueWayVerificationUri,
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

test("BlueWay approval links require HTTPS except explicit loopback development", () => {
  assert.equal(
    safeBlueWayVerificationUri("https://blueway.example/connect?code=ABC"),
    "https://blueway.example/connect?code=ABC",
  );
  assert.equal(
    safeBlueWayVerificationUri("http://localhost:54321/connect"),
    "http://localhost:54321/connect",
  );
  assert.equal(safeBlueWayVerificationUri("http://blueway.example/connect"), null);
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
  for (const key of [
    "access_token",
    "refresh-token",
    "client_secret",
    "pkce_verifier",
    "device_code",
  ]) {
    assert.throws(
      () => assertCredentialFreePayload({ nested: { [key]: "secret" } }),
      /credential material/,
    );
  }
});
