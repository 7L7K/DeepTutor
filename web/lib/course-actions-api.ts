import { apiFetch, apiUrl } from "./api";

export type CourseLearnerAction =
  | "quiz_me"
  | "explain_simpler"
  | "make_flashcards"
  | "review_weak_topics";

export type CourseLearnerActionDestination =
  | "practice"
  | "flashcards"
  | "chat_followup"
  | "learning";

export interface CourseLearnerActionPlan {
  action: CourseLearnerAction;
  course_id: string;
  course_revision: number;
  course_write_epoch: number;
  destination: CourseLearnerActionDestination;
  session_id: string;
  parent_message_id: number;
  objective_ids: string[];
  source_ids: string[];
  reason_code: string;
  operation_id: string | null;
  practice_set_id?: string | null;
  deck_id?: string | null;
  followup_text?: string | null;
}

export interface CourseLearnerActionScope {
  userId: string | null;
  courseId: string | null;
  sessionId: string | null;
  messageId: number | null;
  epoch: number;
}

export function isCurrentCourseLearnerAction(
  requested: CourseLearnerActionScope,
  current: CourseLearnerActionScope,
): boolean {
  return (
    requested.userId === current.userId &&
    requested.courseId === current.courseId &&
    requested.sessionId === current.sessionId &&
    requested.messageId === current.messageId &&
    requested.epoch === current.epoch
  );
}

export function canShowCourseLearnerActions(input: {
  courseActionsEnabled: boolean;
  isStreaming: boolean;
  isLastAssistant: boolean;
  role: "user" | "assistant" | "system";
  messageId?: number;
  hasVisibleContent: boolean;
}): boolean {
  return (
    input.courseActionsEnabled &&
    !input.isStreaming &&
    input.isLastAssistant &&
    input.role === "assistant" &&
    input.messageId != null &&
    input.hasVisibleContent
  );
}

async function responseJson<T>(response: Response): Promise<T> {
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(
      String(
        (body as { detail?: unknown }).detail ||
          `Request failed: ${response.status}`,
      ),
    );
  }
  return body as T;
}

export async function requestCourseLearnerAction(
  courseId: string,
  input: {
    action: CourseLearnerAction;
    sessionId: string;
    assistantMessageId: number;
    idempotencyKey: string;
    expectedCourseRevision: number;
    expectedCourseWriteEpoch: number;
  },
): Promise<CourseLearnerActionPlan> {
  return responseJson<CourseLearnerActionPlan>(
    await apiFetch(
      apiUrl(
        `/api/v1/courses/${encodeURIComponent(courseId)}/learner-actions`,
      ),
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action: input.action,
          session_id: input.sessionId,
          assistant_message_id: input.assistantMessageId,
          idempotency_key: input.idempotencyKey,
          expected_course_revision: input.expectedCourseRevision,
          expected_course_write_epoch: input.expectedCourseWriteEpoch,
        }),
      },
    ),
  );
}
