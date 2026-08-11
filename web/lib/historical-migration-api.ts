import { apiFetch, apiUrl } from "./api";

export interface LegacyOwnerSummary {
  designation: string;
  session_count: number;
  practice_attempt_count: number;
  flashcard_deck_count: number;
}

export interface HistoricalSourceSummary {
  id: string;
  label: string;
  size_bytes: number;
  modified_at: number;
  database_sha256: string;
  schema_fingerprint: string;
  compatible: boolean;
  issue_code: string | null;
  owners: LegacyOwnerSummary[];
}

export interface ClassificationCount {
  importable: number;
  ambiguous: number;
  orphaned: number;
  duplicate: number;
  rejected: number;
}

export interface TableClassification {
  table: string;
  total: number;
  counts: ClassificationCount;
  reason_codes: Record<string, number>;
}

export interface HistoricalMigrationDryRun {
  campaign_id: string;
  source_id: string;
  source_database_sha256: string;
  source_schema_fingerprint: string;
  target_owner_designation: string;
  legacy_owner_designation: string;
  destinations: {
    sessions: "course_less_archive";
    practice_course_id: string | null;
    flashcard_workspace_id: string | null;
    mastery: "archive_only";
  };
  classifications: TableClassification[];
  totals: ClassificationCount;
  required_decisions: string[];
  warnings: string[];
  zero_write: true;
  manifest_sha256: string;
}

async function json<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { detail?: string };
    throw new Error(body.detail || `Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export async function listHistoricalSources(): Promise<HistoricalSourceSummary[]> {
  return json<HistoricalSourceSummary[]>(
    await apiFetch(apiUrl("/api/v1/historical-migration/sources"), {
      cache: "no-store",
    }),
  );
}

export async function createHistoricalDryRun(input: {
  sourceId: string;
  legacyOwnerDesignation: string;
  practiceCourseId?: string | null;
  flashcardWorkspaceId?: string | null;
}): Promise<HistoricalMigrationDryRun> {
  return json<HistoricalMigrationDryRun>(
    await apiFetch(apiUrl("/api/v1/historical-migration/dry-run"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        source_id: input.sourceId,
        legacy_owner_designation: input.legacyOwnerDesignation,
        practice_course_id: input.practiceCourseId || null,
        flashcard_workspace_id: input.flashcardWorkspaceId || null,
      }),
    }),
  );
}
