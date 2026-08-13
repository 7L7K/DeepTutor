import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const root = process.cwd();
const read = (path: string) => readFileSync(resolve(root, path), "utf8");

test("dedicated BlueWay connection routes reuse the authenticated pairing surface", () => {
  assert.match(read("app/connect/blueway/page.tsx"), /BlueWaySettingsPage mode="connect"/);
  assert.match(read("app/connect/blueway/complete/page.tsx"), /BlueWaySettingsPage mode="complete"/);
  assert.match(read("app/(utility)/settings/blueway/page.tsx"), /useSearchParams/);
  assert.match(read("app/(utility)/settings/blueway/page.tsx"), /pollBlueWayConnection/);
  assert.match(read("app/(utility)/settings/blueway/page.tsx"), /Open in BlueWay app/);
  assert.match(read("app/(utility)/settings/blueway/page.tsx"), /Use another device/);
  assert.match(read("app/(utility)/settings/blueway/page.tsx"), /This completion link is incomplete/);
});

test("connection pages are private and non-cacheable", () => {
  const proxy = read("proxy.ts");
  assert.match(proxy, /pathname === "\/connect\/blueway"/);
  assert.match(proxy, /pathname === "\/connect\/blueway\/complete"/);
  assert.match(proxy, /Cache-Control/);
});
