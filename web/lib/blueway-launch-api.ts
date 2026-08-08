import { apiFetch, apiUrl } from "./api";

export type BlueWayLaunchStatus =
  | "ready"
  | "stale"
  | "login_required"
  | "course_not_ready"
  | "connection_revoked"
  | "course_not_found"
  | "term_mismatch"
  | "temporarily_unavailable";

export type BlueWayLaunchResult = {
  schema_version: "teeechr.blueway.launch.v1";
  status: Exclude<BlueWayLaunchStatus, "login_required">;
  course_id?: string;
};

const VALID_STATUSES = new Set<BlueWayLaunchResult["status"]>([
  "ready",
  "stale",
  "course_not_ready",
  "connection_revoked",
  "course_not_found",
  "term_mismatch",
  "temporarily_unavailable",
]);

export async function resolveBlueWayLaunch(input: {
  externalCourseId: string;
  externalTermId: string;
}): Promise<BlueWayLaunchResult | { schema_version: "teeechr.blueway.launch.v1"; status: "login_required" }> {
  const query = new URLSearchParams({
    external_course_id: input.externalCourseId,
    external_term_id: input.externalTermId,
  });
  const response = await apiFetch(
    apiUrl(`/api/v1/integrations/blueway/launch?${query.toString()}`),
    { cache: "no-store", skipAuthRedirect: true },
  );
  if (response.status === 401) {
    return { schema_version: "teeechr.blueway.launch.v1", status: "login_required" };
  }
  if (!response.ok) {
    return {
      schema_version: "teeechr.blueway.launch.v1",
      status: response.status >= 500 ? "temporarily_unavailable" : "course_not_found",
    };
  }

  const value: unknown = await response.json().catch(() => null);
  if (!isRecord(value) || value.schema_version !== "teeechr.blueway.launch.v1" || !VALID_STATUSES.has(value.status as BlueWayLaunchResult["status"])) {
    return {
      schema_version: "teeechr.blueway.launch.v1",
      status: "temporarily_unavailable",
    };
  }
  if (((value.status === "ready" || value.status === "stale") && typeof value.course_id !== "string") || (value.course_id !== undefined && typeof value.course_id !== "string")) {
    return {
      schema_version: "teeechr.blueway.launch.v1",
      status: "temporarily_unavailable",
    };
  }
  return value as BlueWayLaunchResult;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
