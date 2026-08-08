import assert from "node:assert/strict";
import test from "node:test";

import { resolveBlueWayLaunch } from "../lib/blueway-launch-api";

test("launch API sends exact external Course and term hints", async () => {
  const original = globalThis.fetch;
  let requestUrl = "";
  (globalThis as { fetch: typeof fetch }).fetch = async (input) => {
    requestUrl = String(input);
    return new Response(JSON.stringify({
      schema_version: "teeechr.blueway.launch.v1",
      status: "ready",
      course_id: "crs_private_owner_course",
    }), { status: 200, headers: { "content-type": "application/json" } });
  };
  try {
    assert.deepEqual(
      await resolveBlueWayLaunch({ externalCourseId: "biology-101", externalTermId: "fall-2026" }),
      {
        schema_version: "teeechr.blueway.launch.v1",
        status: "ready",
        course_id: "crs_private_owner_course",
      },
    );
    assert.equal(
      requestUrl,
      "/api/v1/integrations/blueway/launch?external_course_id=biology-101&external_term_id=fall-2026",
    );
  } finally {
    (globalThis as { fetch: typeof fetch }).fetch = original;
  }
});

test("launch API exposes a bounded login-required state", async () => {
  const original = globalThis.fetch;
  (globalThis as { fetch: typeof fetch }).fetch = async () => new Response("", { status: 401 });
  try {
    assert.deepEqual(
      await resolveBlueWayLaunch({ externalCourseId: "biology-101", externalTermId: "fall-2026" }),
      { schema_version: "teeechr.blueway.launch.v1", status: "login_required" },
    );
  } finally {
    (globalThis as { fetch: typeof fetch }).fetch = original;
  }
});
