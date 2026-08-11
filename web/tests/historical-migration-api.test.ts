import assert from "node:assert/strict";
import test from "node:test";

import {
  createHistoricalDryRun,
  listHistoricalSources,
} from "../lib/historical-migration-api";

test("historical source discovery uses the authenticated server allowlist", async (t) => {
  const originalFetch = globalThis.fetch;
  let requestedUrl = "";
  t.after(() => {
    globalThis.fetch = originalFetch;
  });
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    requestedUrl = String(input);
    return new Response(
      JSON.stringify([
        {
          id: "hms_opaque",
          label: "Historical TEEECHR learner database",
          size_bytes: 1024,
          modified_at: 1,
          database_sha256: "a".repeat(64),
          schema_fingerprint: "b".repeat(64),
          compatible: true,
          issue_code: null,
          owners: [],
        },
      ]),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
  }) as typeof fetch;

  const sources = await listHistoricalSources();
  assert.equal(requestedUrl, "/api/v1/historical-migration/sources");
  assert.equal(sources[0].id, "hms_opaque");
});

test("dry-run transport sends only opaque authority and owned destinations", async (t) => {
  const originalFetch = globalThis.fetch;
  let requestedUrl = "";
  let requestedBody: Record<string, unknown> = {};
  t.after(() => {
    globalThis.fetch = originalFetch;
  });
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    requestedUrl = String(input);
    requestedBody = JSON.parse(String(init?.body));
    return new Response(
      JSON.stringify({
        campaign_id: "hmc_test",
        source_id: "hms_source",
        source_database_sha256: "a".repeat(64),
        source_schema_fingerprint: "b".repeat(64),
        target_owner_designation: "owner_opaque",
        legacy_owner_designation: "legacy_owner_opaque",
        destinations: {
          sessions: "course_less_archive",
          practice_course_id: "crs_practice",
          flashcard_workspace_id: "crs_general",
          mastery: "archive_only",
        },
        classifications: [],
        totals: {
          importable: 0,
          ambiguous: 0,
          orphaned: 0,
          duplicate: 0,
          rejected: 0,
        },
        required_decisions: [],
        warnings: [],
        zero_write: true,
        manifest_sha256: "c".repeat(64),
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
  }) as typeof fetch;

  const report = await createHistoricalDryRun({
    sourceId: "hms_source",
    legacyOwnerDesignation: "legacy_owner_opaque",
    practiceCourseId: "crs_practice",
    flashcardWorkspaceId: "crs_general",
  });

  assert.equal(requestedUrl, "/api/v1/historical-migration/dry-run");
  assert.deepEqual(requestedBody, {
    source_id: "hms_source",
    legacy_owner_designation: "legacy_owner_opaque",
    practice_course_id: "crs_practice",
    flashcard_workspace_id: "crs_general",
  });
  assert.equal("source_path" in requestedBody, false);
  assert.equal(report.zero_write, true);
});
