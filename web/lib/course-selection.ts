export function courseSelectionStorageKey(userId: string): string {
  return `dt:courses:active:${userId}`;
}

export function isCurrentCourseRequest(
  requestEpoch: number,
  currentEpoch: number,
  requestedUserId: string,
  currentUserId: string | null,
): boolean {
  return requestEpoch === currentEpoch && requestedUserId === currentUserId;
}

export function validatedActiveCourseId(
  courses: Array<{ id: string; state: "active" | "archived" }>,
  requestedId: string | null,
): string | null {
  return requestedId &&
    courses.some(
      (course) => course.id === requestedId && course.state === "active",
    )
    ? requestedId
    : null;
}

export function resolveSessionCourseView(
  courses: Array<{ id: string; state: "active" | "archived" }>,
  sessionCourseId: string | null,
  loading: boolean,
): { courseId: string | null; readOnly: boolean } {
  if (!sessionCourseId) return { courseId: null, readOnly: false };
  const course = courses.find((item) => item.id === sessionCourseId);
  return {
    courseId: sessionCourseId,
    readOnly: loading || course?.state !== "active",
  };
}

export function courseIdForChatSession(
  persistedSessionId: string | null,
  persistedCourseId: string | null,
  selectedCourseId: string | null,
): string | null {
  // An existing session's binding is authoritative, including an explicit
  // null for generic Chat. Only a new, unpersisted draft inherits the picker.
  return persistedSessionId
    ? persistedCourseId
    : persistedCourseId ?? selectedCourseId;
}

let runtimeActiveCourseId: string | null = null;

export function getRuntimeActiveCourseId(): string | null {
  return runtimeActiveCourseId;
}

export function setRuntimeActiveCourseId(courseId: string | null): void {
  runtimeActiveCourseId = courseId;
}
