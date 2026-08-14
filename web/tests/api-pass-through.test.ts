import test from "node:test";
import assert from "node:assert/strict";

import { apiUrl, wsUrl } from "../lib/api";

test("apiUrl preserves frontend-relative API paths for the proxy", () => {
  assert.equal(apiUrl("/api/v1/knowledge/list"), "/api/v1/knowledge/list");
});

test("wsUrl preserves frontend-relative WebSocket paths for the proxy", () => {
  assert.equal(wsUrl("/api/v1/ws"), "/api/v1/ws");
});

test("API helpers preserve arbitrary paths without host substitution", () => {
  const path = "/api/v1/courses/crs_bio/materials";
  assert.equal(apiUrl(path), path);
  assert.equal(wsUrl(path), path);
});
