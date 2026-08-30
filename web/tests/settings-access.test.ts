import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";

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
    "/settings/mcp",
    "/settings/mcp/",
  ]) {
    assert.equal(isAdminOnlySettingsRoute(pathname), false, pathname);
  }
});

test("legacy MCP settings links redirect learners to the account-safe MCP surface", () => {
  const redirectPage = readFileSync(
    path.join(process.cwd(), "app/(utility)/settings/mcp/page.tsx"),
    "utf8",
  );

  assert.equal(isAdminOnlySettingsRoute("/settings/mcp"), false);
  assert.match(redirectPage, /redirect\("\/space\/mcp"\)/);
});
