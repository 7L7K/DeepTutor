import type { DeepQuestionFormConfig } from "./quiz-types";

interface PracticeDomainBreakdownLike {
  domain: string;
  correct: number;
  total: number;
  percent: number;
}

interface PracticeStructuredResultLike {
  domain_breakdown: PracticeDomainBreakdownLike[];
}

export type PracticeQuizIntentId =
  | "quick_check"
  | "diagnostic"
  | "exam_simulation"
  | "ethics_drill";

export interface PracticeQuizIntentDefinition {
  id: PracticeQuizIntentId;
  label: string;
  description: string;
  numQuestions: number;
  difficulty: string;
  questionType: string;
  examMode: boolean;
  timerMinutes: number;
  topicSeed?: string;
  qualityNotes: string[];
}

export interface PracticeQuizIntentState {
  quizConfig: DeepQuestionFormConfig;
  examMode: boolean;
  timerMinutes: number;
}

const COMMON_QUALITY_NOTES = [
  "Avoid duplicates or near-duplicate questions.",
  "Prefer concrete scenario/application stems over vague trivia.",
  "For counseling or NCE topics, make questions feel like realistic NBCC/NCE practice: best next counselor action, ethical priority, theory distinction, assessment interpretation, group/career/development application, or diagnosis/case reasoning.",
  "For multiple-choice questions, use exactly four plausible options, one clearly best answer, and no giveaway options.",
  "Keep answer choices balanced in length and style so the correct answer is not obvious from wording alone.",
  "Explain why the correct answer is best and why a tempting distractor is not best.",
];

export const PRACTICE_QUIZ_INTENTS: PracticeQuizIntentDefinition[] = [
  {
    id: "quick_check",
    label: "Quick check",
    description: "A short untimed pulse check to see whether the fundamentals feel stable yet.",
    numQuestions: 10,
    difficulty: "easy",
    questionType: "choice",
    examMode: false,
    timerMinutes: 15,
    qualityNotes: [
      "Keep questions concise and confidence-building.",
      "Bias toward fundamentals before advanced edge cases.",
      "Even for fundamentals, use small realistic examples when that makes the question stronger.",
    ],
  },
  {
    id: "diagnostic",
    label: "Diagnostic",
    description: "A broader read on strengths and weak spots across the topic, built for review planning.",
    numQuestions: 20,
    difficulty: "medium",
    questionType: "choice",
    examMode: false,
    timerMinutes: 25,
    qualityNotes: [
      "Spread questions across multiple subtopics instead of clustering too tightly.",
      "Include enough variation to reveal weak areas, not just confirm easy wins.",
      "Use a mix of direct concept checks and applied counseling judgment questions.",
    ],
  },
  {
    id: "exam_simulation",
    label: "Exam simulation",
    description: "A tighter, timed pass meant to feel closer to a real exam block with stronger distractors.",
    numQuestions: 25,
    difficulty: "medium",
    questionType: "choice",
    examMode: true,
    timerMinutes: 30,
    qualityNotes: [
      "Use exam-style wording with realistic distractors and tighter discrimination.",
      "Include a visible mix of concept, application, and scenario-based questions.",
      "Avoid friendly coaching language inside question stems; this mode should feel closest to a formal practice block.",
    ],
  },
  {
    id: "ethics_drill",
    label: "Ethics drill",
    description: "A targeted drill on professional orientation, boundaries, and ethical decision-making scenarios.",
    numQuestions: 10,
    difficulty: "medium",
    questionType: "choice",
    examMode: false,
    timerMinutes: 20,
    topicSeed: "NBCC NCE professional orientation and ethical practice",
    qualityNotes: [
      "Stay tightly focused on ethics, boundaries, legal/ethical judgment, and professional role.",
      "Favor scenario-based decision questions over isolated terminology.",
      "Make distractors plausible but ethically or clinically less appropriate than the best response.",
    ],
  },
];

export function getPracticeQuizIntent(intentId: PracticeQuizIntentId): PracticeQuizIntentDefinition {
  return (
    PRACTICE_QUIZ_INTENTS.find((intent) => intent.id === intentId) ??
    PRACTICE_QUIZ_INTENTS[0]
  );
}

export function applyPracticeQuizIntent(
  currentConfig: DeepQuestionFormConfig,
  intentId: PracticeQuizIntentId,
): PracticeQuizIntentState {
  const intent = getPracticeQuizIntent(intentId);
  const nextTopic = currentConfig.topic.trim() || intent.topicSeed || "";
  return {
    quizConfig: {
      ...currentConfig,
      mode: "custom",
      topic: intent.topicSeed ?? nextTopic,
      num_questions: intent.numQuestions,
      difficulty: intent.difficulty,
      question_type: intent.questionType,
    },
    examMode: intent.examMode,
    timerMinutes: intent.timerMinutes,
  };
}

export function buildPracticeQuizPreference(
  config: DeepQuestionFormConfig,
  intentId: PracticeQuizIntentId,
): string {
  const intent = getPracticeQuizIntent(intentId);
  const lines = [
    `Assessment intent: ${intent.label}.`,
    ...COMMON_QUALITY_NOTES,
    ...intent.qualityNotes,
  ];

  if (config.preference.trim()) {
    lines.unshift(`User preference: ${config.preference.trim()}`);
  }

  return lines.join("\n");
}

export function buildPracticeAssessmentSummary(
  config: DeepQuestionFormConfig,
  intentId: PracticeQuizIntentId,
  examMode: boolean,
  timerMinutes: number,
  knowledgeBaseCount: number,
): string {
  const intent = getPracticeQuizIntent(intentId);
  const grounding =
    knowledgeBaseCount > 0
      ? `Grounded with ${knowledgeBaseCount} knowledge base${knowledgeBaseCount === 1 ? "" : "s"}`
      : "AI-generated from topic";
  return [
    intent.label,
    `${config.num_questions} questions`,
    config.difficulty || "auto difficulty",
    examMode ? `${timerMinutes}m soft timer` : "untimed",
    grounding,
  ].join(" · ");
}

export function resolvePracticeAttemptSessionId(input: {
  turnSessionId?: string | null;
  selectedSessionId?: string | null;
  chatSessionId?: string | null;
}): string | null {
  return input.turnSessionId || input.selectedSessionId || input.chatSessionId || null;
}

function sortedWeakDomains(
  domainBreakdown: PracticeDomainBreakdownLike[],
): PracticeDomainBreakdownLike[] {
  return [...domainBreakdown]
    .filter((item) => item.total > 0)
    .sort((left, right) => {
      if (left.percent !== right.percent) return left.percent - right.percent;
      if (left.correct !== right.correct) return left.correct - right.correct;
      return right.total - left.total;
    });
}

export function deriveWeakDomainLabels(
  domainBreakdown: PracticeDomainBreakdownLike[],
  limit = 2,
): string[] {
  return sortedWeakDomains(domainBreakdown)
    .map((item) => item.domain)
    .filter(Boolean)
    .slice(0, limit);
}

export function buildRetryTopic(
  topic: string,
  structuredResult: PracticeStructuredResultLike,
): string {
  const weakDomains = deriveWeakDomainLabels(structuredResult.domain_breakdown, 3);
  const trimmedTopic = topic.trim();
  if (weakDomains.length === 0) {
    return trimmedTopic || "Targeted quiz review";
  }
  const focus = weakDomains.join(", ");
  return trimmedTopic
    ? `${trimmedTopic} — focus on ${focus}`
    : `Targeted quiz review on ${focus}`;
}

export function buildFlashcardSeedTopic(
  topic: string,
  structuredResult: PracticeStructuredResultLike,
): string {
  const weakDomains = deriveWeakDomainLabels(structuredResult.domain_breakdown, 2);
  const weakText = weakDomains.length > 0 ? weakDomains.join(" and ") : "missed quiz topics";
  return topic.trim()
    ? `${topic.trim()} flashcards focused on ${weakText}`
    : `Flashcards focused on ${weakText}`;
}
