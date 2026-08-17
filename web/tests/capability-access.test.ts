import test from "node:test";
import assert from "node:assert/strict";

import {
  adminOnlyForPath,
  capabilityForPath,
} from "../lib/capability-routes";

// ── capabilityForPath ──────────────────────────────────────────────────

test("capabilityForPath maps LLM features to llm", () => {
  assert.equal(capabilityForPath("/home"), null); // Course organization stays available.
  assert.equal(capabilityForPath("/partners"), "llm");
  assert.equal(capabilityForPath("/co-writer"), "llm");
  assert.equal(capabilityForPath("/book"), "llm");
  assert.equal(capabilityForPath("/space/learning"), null); // Model-free Course learning.
  assert.equal(capabilityForPath("/playground"), "llm");
});

test("capabilityForPath matches nested routes by prefix", () => {
  assert.equal(capabilityForPath("/home/abc-123"), null);
  assert.equal(capabilityForPath("/partners/partner-1"), "llm");
  assert.equal(capabilityForPath("/space/learning/book-1"), null);
});

test("capabilityForPath matches on a segment boundary, not a bare prefix", () => {
  // A sibling route must never be swallowed by a shorter gated prefix.
  assert.equal(capabilityForPath("/booket"), null);
  assert.equal(capabilityForPath("/homepage"), null);
  assert.equal(capabilityForPath("/playgrounds-xyz"), null);
  // The gated route itself and its children still match.
  assert.equal(capabilityForPath("/book"), "llm");
  assert.equal(capabilityForPath("/book/123"), "llm");
});

test("capabilityForPath returns null for ungated routes", () => {
  // Knowledge is ungated: embedding is shared admin infra, not per-user.
  assert.equal(capabilityForPath("/knowledge"), null);
  assert.equal(capabilityForPath("/memory"), null);
  assert.equal(capabilityForPath("/space"), null);
  assert.equal(capabilityForPath("/settings"), null);
});

test("adminOnlyForPath protects advanced workspace destinations", () => {
  assert.equal(adminOnlyForPath("/agents"), true);
  assert.equal(adminOnlyForPath("/co-writer/drafts"), true);
  assert.equal(adminOnlyForPath("/book"), true);
  assert.equal(adminOnlyForPath("/knowledge"), true);
  assert.equal(adminOnlyForPath("/memory"), true);
  assert.equal(adminOnlyForPath("/playground"), true);
  assert.equal(adminOnlyForPath("/space/cli-apps"), true);
});

test("adminOnlyForPath leaves learner destinations available", () => {
  assert.equal(adminOnlyForPath("/partners"), false);
  assert.equal(adminOnlyForPath("/practice"), false);
  assert.equal(adminOnlyForPath("/flashcards"), false);
  assert.equal(adminOnlyForPath("/space"), false);
  assert.equal(adminOnlyForPath("/space/mcp"), false);
  assert.equal(adminOnlyForPath("/knowledge-base"), false);
});

test("adminOnlyForPath matches route segments rather than bare prefixes", () => {
  assert.equal(adminOnlyForPath("/memory-bank"), false);
  assert.equal(adminOnlyForPath("/booklet"), false);
  assert.equal(adminOnlyForPath("/space/cli-appstore"), false);
  assert.equal(adminOnlyForPath("/playground-tools"), false);
  assert.equal(adminOnlyForPath("/space/cli-apps/details"), true);
});
