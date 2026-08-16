import test from "node:test";
import assert from "node:assert/strict";

import {
  isAdminOnlySettingsRoute,
  SETTINGS_CATEGORIES,
} from "../lib/settings-nav";

test("settings categories identify deployment-wide admin controls", () => {
  const adminCategories = SETTINGS_CATEGORIES.filter((category) => category.adminOnly).map(
    (category) => category.key,
  );

  assert.deepEqual(adminCategories, [
    "network",
    "models",
    "knowledge",
    "agents",
    "memory",
  ]);
});

test("admin-only settings routes cover category and privileged leaves", () => {
  for (const pathname of [
    "/settings/network",
    "/settings/models",
    "/settings/llm",
    "/settings/document-parsing",
    "/settings/capabilities",
    "/settings/attachments",
    "/settings/mcp",
    "/settings/mineru",
    "/settings/agents",
    "/settings/agents/codex",
    "/settings/memory",
  ]) {
    assert.equal(isAdminOnlySettingsRoute(pathname), true, pathname);
  }
});

test("learner settings remain available", () => {
  for (const pathname of [
    "/settings",
    "/settings/blueway",
    "/settings/appearance",
    "/settings/chat",
    "/settings/tools",
  ]) {
    assert.equal(isAdminOnlySettingsRoute(pathname), false, pathname);
  }
});
