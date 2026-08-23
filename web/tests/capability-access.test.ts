import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import path from "node:path";

import {
  adminOnlyForPath,
  capabilityForPath,
} from "../lib/capability-routes";

// ── capabilityForPath ──────────────────────────────────────────────────

test("capabilityForPath maps LLM features to llm", () => {
  assert.equal(capabilityForPath("/home"), null); // Course organization stays available.
  assert.equal(capabilityForPath("/co-writer"), "llm");
  assert.equal(capabilityForPath("/book"), "llm");
  assert.equal(capabilityForPath("/space/learning"), null); // Model-free Course learning.
  assert.equal(capabilityForPath("/playground"), "llm");
});

test("capabilityForPath matches nested routes by prefix", () => {
  assert.equal(capabilityForPath("/home/abc-123"), null);
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
  assert.equal(capabilityForPath("/partners"), null);
  assert.equal(capabilityForPath("/partners/partner-1"), null);
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

test("adminOnlyForPath gates Partner management but not learner discovery", () => {
  // The list is a learner surface. Only a concrete management page (new or a
  // partner ID) is admin-only, so CapabilityGate prevents its effects from
  // issuing admin-only partner API requests for regular users.
  assert.equal(adminOnlyForPath("/partners"), false);
  assert.equal(adminOnlyForPath("/partners/"), false);
  assert.equal(adminOnlyForPath("/partners/new"), true);
  assert.equal(adminOnlyForPath("/partners/new/"), true);
  assert.equal(adminOnlyForPath("/partners/study-buddy"), true);
  assert.equal(adminOnlyForPath("/partners/study-buddy/"), true);
  assert.equal(adminOnlyForPath("/partners/study-buddy/channels"), true);
  assert.equal(adminOnlyForPath("/partners//"), true);
  assert.equal(adminOnlyForPath("/partnerships/new"), false);
});

test("optional admin gates never redirect learner-safe routes", () => {
  const source = readFileSync(
    path.join(process.cwd(), "components/access/AdminGate.tsx"),
    "utf8",
  );

  assert.match(
    source,
    /const denied =\s+required &&\s+known &&\s+!loading &&\s+enabled &&\s+\(!authenticated \|\| !isAdmin\);/,
  );
});

test("capability presentation fails closed and reports a recoverable probe failure", () => {
  const source = readFileSync(
    path.join(
      process.cwd(),
      "components/access/CapabilityAccessContext.tsx",
    ),
    "utf8",
  );

  assert.match(source, /isAdmin: false/);
  assert.match(source, /hasLlm: false/);
  assert.match(source, /has: \(\) => false/);
  assert.match(source, /known: false/);
  assert.match(source, /refreshing: false/);
  assert.match(source, /const isBackgroundRefresh = knownRef\.current/);
  assert.match(source, /if \(isBackgroundRefresh\) setRefreshing\(true\)/);
  assert.doesNotMatch(source, /setHasLlm\(false\)/);
  assert.match(source, /listLLMOptions\(\{ force: true \}\)/);
  assert.match(source, /setError\("Could not verify feature access\. Try again\."\)/);
  assert.match(source, /if \(!known\) return false/);
  assert.match(
    source,
    /value=\{\{ known, loading, refreshing, isAdmin, hasLlm, error, has, refresh \}\}/,
  );
});

test("adminOnlyForPath matches route segments rather than bare prefixes", () => {
  assert.equal(adminOnlyForPath("/memory-bank"), false);
  assert.equal(adminOnlyForPath("/booklet"), false);
  assert.equal(adminOnlyForPath("/space/cli-appstore"), false);
  assert.equal(adminOnlyForPath("/playground-tools"), false);
  assert.equal(adminOnlyForPath("/space/cli-apps/details"), true);
});
