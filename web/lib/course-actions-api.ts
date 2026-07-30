import { apiFetch, apiUrl } from "./api";
import type { FlashcardGenerationBriefReceipt } from "./flashcards-api";

export type CourseLearnerAction =
  | "quiz_me"
  | "explain_simpler"
  | "make_flashcards"
  | "review_weak_topics";

/**
 * Recognize an explicit learner request to create Flashcards from a general
 * conversation. This is intentionally narrow: ordinary mentions of studying
 * or Flashcards must not trigger a provider-backed workflow.
 */
export function requestedFlashcardCount(value: string): number | null {
  if (
    !/\b(?:make|create|turn|generate)\b[\s\S]{0,100}\bflashcards?\b|\bflashcards?\b[\s\S]{0,100}\b(?:from|about|on|of)\b/i.test(
      value,
    )
  ) {
    return null;
  }
  const numeric = value.match(/\b([1-9]|[1-3][0-9]|4[0-8])\b/);
  return numeric ? Number(numeric[1]) : 8;
}

export function visibleCourseLearnerActions(
  practiceGenerationEnabled: boolean,
  flashcardGenerationEnabled: boolean,
): CourseLearnerAction[] {
  return [
    ...(practiceGenerationEnabled
      ? (["quiz_me"] as CourseLearnerAction[])
      : []),
    "explain_simpler",
    ...(flashcardGenerationEnabled
      ? (["make_flashcards"] as CourseLearnerAction[])
      : []),
    ...(practiceGenerationEnabled
      ? (["review_weak_topics"] as CourseLearnerAction[])
      : []),
  ];
}

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
  generation_brief?: FlashcardGenerationBriefReceipt | null;
  followup_text?: string | null;
}

export async function requestGeneralStudyFlashcards(input: {
  sessionId: string;
  assistantMessageId: number;
  desiredCount?: number;
  destinationCourseId?: string;
}): Promise<CourseLearnerActionPlan> {
  return responseJson<CourseLearnerActionPlan>(
    await apiFetch(apiUrl("/api/v1/courses/general-study/learner-actions"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        action: "make_flashcards",
        session_id: input.sessionId,
        assistant_message_id: input.assistantMessageId,
        desired_count: input.desiredCount ?? 8,
        ...(input.destinationCourseId
          ? { destination_course_id: input.destinationCourseId }
          : {}),
      }),
    }),
  );
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
