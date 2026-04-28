import { apiFetch } from "@/lib/api";

export interface PracticeQuizSnapshotQuestion {
  question_id: string;
  question: string;
  question_type?: string;
  options?: Record<string, string>;
  difficulty?: string;
  concentration?: string;
}

export interface PracticeQuizSnapshot {
  title: string;
  intro?: string;
  questions: PracticeQuizSnapshotQuestion[];
  settings?: Record<string, unknown>;
}

export interface PracticeStructuredScore {
  correct: number;
  total: number;
  percent: number;
}

export interface PracticeDomainBreakdown {
  domain: string;
  correct: number;
  total: number;
  percent: number;
  question_numbers: number[];
}

export interface PracticeQuestionResult {
  question_id: string;
  display_order: number;
  question_text: string;
  question_type: string;
  options?: Record<string, string>;
  user_answer: string;
  correct_answer: string;
  is_correct: boolean;
  is_answered: boolean;
  explanation?: string;
  coaching_note?: string;
  domain?: string;
  difficulty?: string;
}

export interface PracticeStructuredResult {
  submission_state: "graded" | "incomplete";
  overall_summary?: string;
  strongest_areas?: string[];
  weakest_areas?: string[];
  recommended_next_step?: string;
  missing_question_numbers: number[];
  score: PracticeStructuredScore;
  domain_breakdown: PracticeDomainBreakdown[];
  question_results: PracticeQuestionResult[];
}

export interface PracticeAttemptItem {
  id: number;
  attempt_id: string;
  display_order: number;
  question_id: string;
  question_text: string;
  question_type: string;
  options: Record<string, string>;
  domain: string;
  difficulty: string;
  correct_answer: string;
  user_answer: string;
  is_correct: boolean;
  is_answered: boolean;
  explanation: string;
  coaching_note: string;
}

export interface PracticeAttempt {
  id: string;
  session_id: string;
  title?: string;
  topic?: string;
  source_type?: string;
  source_capability?: string;
  source_session_id?: string | null;
  status: "in_progress" | "submitted" | "timed_out";
  started_at: number;
  submitted_at?: number | null;
  duration_seconds?: number | null;
  score_correct?: number | null;
  score_total?: number | null;
  score_percent?: number | null;
  quiz_snapshot: PracticeQuizSnapshot;
  result_summary?: PracticeStructuredResult | Record<string, unknown>;
  items?: PracticeAttemptItem[];
}

export interface PracticeDomainProgressRow {
  domain: string;
  lifetime: {
    attempt_count: number;
    correct: number;
    total: number;
    percent: number;
  };
  recent: {
    attempt_count: number;
    correct: number;
    total: number;
    percent: number;
  };
  last_submitted_at?: number | null;
}

async function expectJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export async function createPracticeAttempt(payload: {
  session_id?: string | null;
  source_type?: string;
  source_session_id?: string | null;
  title?: string;
  topic?: string;
  knowledge_base?: string;
  mode?: string;
  time_limit_seconds?: number | null;
  quiz_snapshot: PracticeQuizSnapshot;
}): Promise<PracticeAttempt> {
  const response = await apiFetch("/api/v1/practice/attempts", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await expectJson<{ attempt: PracticeAttempt }>(response);
  return data.attempt;
}

export async function getPracticeAttempt(attemptId: string): Promise<PracticeAttempt> {
  const response = await apiFetch(`/api/v1/practice/attempts/${attemptId}`, {
    cache: "no-store",
  });
  const data = await expectJson<{ attempt: PracticeAttempt }>(response);
  return data.attempt;
}

export async function savePracticeAttemptResults(
  attemptId: string,
  payload: {
    submitted_at?: number;
    duration_seconds?: number;
    timed_out?: boolean;
    structured_result: PracticeStructuredResult;
  },
): Promise<PracticeAttempt> {
  const response = await apiFetch(`/api/v1/practice/attempts/${attemptId}/results`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await expectJson<{ attempt: PracticeAttempt }>(response);
  return data.attempt;
}

export async function listPracticeAttempts(limit = 12, offset = 0): Promise<PracticeAttempt[]> {
  const response = await apiFetch(`/api/v1/practice/attempts?limit=${limit}&offset=${offset}`, {
    cache: "no-store",
  });
  const data = await expectJson<{ attempts: PracticeAttempt[] }>(response);
  return data.attempts ?? [];
}

export async function getPracticeProgress(): Promise<PracticeDomainProgressRow[]> {
  const response = await apiFetch("/api/v1/practice/progress", {
    cache: "no-store",
  });
  const data = await expectJson<{ domains: PracticeDomainProgressRow[] }>(response);
  return data.domains ?? [];
}
