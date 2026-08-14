import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const root = process.cwd();
const read = (path: string) => readFileSync(resolve(root, path), "utf8");

test("dedicated BlueWay connection routes reuse the authenticated pairing surface", () => {
  const route = read("app/(utility)/settings/blueway/page.tsx");
  assert.match(read("app/connect/blueway/page.tsx"), /BlueWaySettingsPage mode="connect"/);
  assert.match(read("app/connect/blueway/complete/page.tsx"), /BlueWaySettingsPage mode="complete"/);
  assert.match(route, /useSearchParams/);
  assert.match(route, /getBlueWayCurrentAttempt/);
  assert.match(route, /pollBlueWayConnection/);
  assert.match(route, /cancelBlueWayConnection/);
  assert.match(route, /Continue in BlueWay/);
  assert.match(route, /Use another device/);
  assert.match(route, /Waiting for BlueWay approval/);
  assert.match(route, /server—not this countdown—decides/);
  assert.match(route, /This connection request expired/);
  assert.match(route, /This completion link is incomplete/);
  assert.match(route, /request_id: attempt.request_id/);
  assert.match(route, /QRCode\.toDataURL/);
  assert.match(route, /Taking longer than expected/);
  assert.match(route, /no duplicate sync was started/);
  assert.match(route, /Fetching classes and academic data/);
  assert.match(route, /Making your Course materials searchable/);
  assert.doesNotMatch(route.slice(0, route.indexOf('showFallback')), /attempt\.user_code/);
});

test("connection pages are private and non-cacheable", () => {
  const proxy = read("proxy.ts");
  assert.match(proxy, /pathname === "\/connect\/blueway"/);
  assert.match(proxy, /pathname === "\/connect\/blueway\/complete"/);
  assert.match(proxy, /Cache-Control/);
});
