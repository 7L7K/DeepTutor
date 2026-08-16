import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

const workspace = readFileSync(
  path.join(process.cwd(), "components", "chat/home", "GeneralStudyWorkspace.tsx"),
  "utf8",
);
const history = readFileSync(
  path.join(process.cwd(), "components", "space", "ChatHistorySection.tsx"),
  "utf8",
);
const chat = readFileSync(
  path.join(process.cwd(), "components", "chat/home", "UnifiedChatPage.tsx"),
  "utf8",
);

test("General Study is a small Chat and Recent workspace", () => {
  assert.match(workspace, /General Study/);
  assert.match(workspace, /Study anything outside a class\./);
  assert.match(workspace, /href="\/home"/);
  assert.match(workspace, /href="\/home\?view=recent"/);
  assert.match(workspace, /active=\{view === "chat"\}/);
  assert.match(workspace, /active=\{view === "recent"\}/);
  assert.doesNotMatch(workspace, /Questions|Saved|Mastery Path|Personas|Skills|MCP|CLI/);
});

test("General Study Recent filters to sessions without a Course", () => {
  assert.match(workspace, /<ChatHistorySection scope="general" \/>/);
  assert.match(history, /scope === "general"/);
  assert.match(history, /session\.course_id == null/);
});

test("Empty generic chat hides inactive header actions", () => {
  assert.match(chat, /state\.messages\.length \? \(\s*<>/);
  assert.match(chat, /state\.messages\.length \|\| capabilityNeedsConfig/);
  assert.match(chat, /hideSurfaceLabel/);
});
