import type { QuizQuestion } from "./quiz-types";

interface QuizSubmissionRequestSnapshot {
  content: string;
  capability: string;
  enabledTools: string[];
  knowledgeBases: string[];
  language: string;
}

export interface InteractiveQuizSubmissionPayload {
  content: string;
  config: {
    quiz_submission_context: {
      title: string;
      intro: string;
      answers: string;
      answer_map: Array<{
        index: number;
        question_id: string;
        answer: string;
      }>;
      questions: Array<{
        question_id: string;
        question: string;
        question_type: QuizQuestion["question_type"];
        options: Record<string, string>;
      }>;
    };
  };
  requestSnapshotOverride: QuizSubmissionRequestSnapshot;
}

export function buildInteractiveQuizSubmission(
  questions: QuizQuestion[],
  answers: Record<number, string>,
  options: {
    intro?: string;
    enabledTools: string[];
    knowledgeBases: string[];
    language: string;
  },
): InteractiveQuizSubmissionPayload {
  const answerMap = questions
    .map((question, questionIndex) => ({
      index: questionIndex + 1,
      question_id: question.question_id,
      answer: answers[questionIndex] ?? "",
    }))
    .filter((item) => item.answer);

  const content = answerMap
    .map((item) => `${item.index}${item.answer}`)
    .join(" ");

  return {
    content,
    config: {
      quiz_submission_context: {
        title: "Interactive quiz submission",
        intro: options.intro ?? "",
        answers: content,
        answer_map: answerMap,
        questions: questions.map((question) => ({
          question_id: question.question_id,
          question: question.question,
          question_type: question.question_type,
          options: question.options ?? {},
        })),
      },
    },
    requestSnapshotOverride: {
      content,
      capability: "deep_question",
      enabledTools: [...options.enabledTools],
      knowledgeBases: [...options.knowledgeBases],
      language: options.language,
    },
  };
}
