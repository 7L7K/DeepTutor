const LOCAL_ORIGIN = "https://teeechr.invalid";
const MAX_HINT_LENGTH = 256;

/** Keep login continuation same-origin and canonicalize the B2 launch target. */
export function normalizeAuthNext(raw: string | null | undefined): string {
  const candidate = raw?.trim() ?? "";
  if (!candidate || !candidate.startsWith("/") || candidate.startsWith("//")) {
    return "/";
  }

  let decoded: string;
  try {
    decoded = decodeURIComponent(candidate);
  } catch {
    return "/";
  }
  if (decoded.startsWith("//") || decoded.startsWith("/\\") || candidate.includes("\\")) {
    return "/";
  }

  let parsed: URL;
  try {
    parsed = new URL(candidate, LOCAL_ORIGIN);
  } catch {
    return "/";
  }
  if (parsed.origin !== LOCAL_ORIGIN || parsed.username || parsed.password) {
    return "/";
  }

  if (parsed.pathname === "/connect/blueway" || parsed.pathname === "/connect/blueway/complete") {
    const requestIds = parsed.searchParams.getAll("request_id");
    const hasOnlyConnectionKeys = [...parsed.searchParams.keys()].every((key) => key === "request_id");
    const requestId = requestIds[0]?.trim() ?? "";
    if (!hasOnlyConnectionKeys || requestIds.length > 1 || (requestId && !/^[A-Za-z0-9-]{16,128}$/.test(requestId)) || (parsed.pathname.endsWith("/complete") && !requestId)) {
      return "/";
    }
    return requestId
      ? `${parsed.pathname}?${new URLSearchParams({ request_id: requestId }).toString()}`
      : parsed.pathname;
  }

  if (parsed.pathname !== "/launch/blueway") {
    return `${parsed.pathname}${parsed.search}`;
  }

  const courseIds = parsed.searchParams.getAll("external_course_id");
  const termIds = parsed.searchParams.getAll("external_term_id");
  const hasOnlyLaunchKeys = [...parsed.searchParams.keys()].every(
    (key) => key === "external_course_id" || key === "external_term_id",
  );
  const courseId = courseIds[0]?.trim() ?? "";
  const termId = termIds[0]?.trim() ?? "";
  if (
    !hasOnlyLaunchKeys
    || courseIds.length !== 1
    || !courseId
    || courseId.length > MAX_HINT_LENGTH
    || termIds.length > 1
    || (termIds.length === 1 && (!termId || termId.length > MAX_HINT_LENGTH))
  ) {
    return "/";
  }

  const params = new URLSearchParams({ external_course_id: courseId });
  if (termIds.length === 1) params.set("external_term_id", termId);
  return `/launch/blueway?${params.toString()}`;
}
