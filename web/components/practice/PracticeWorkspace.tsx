"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlarmClockCheck,
  ArrowLeft,
  ArrowRight,
  BrainCircuit,
  CheckCircle2,
  ClipboardCheck,
  Loader2,
  RefreshCcw,
  Send,
  Sparkles,
  TimerReset,
  TriangleAlert,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import MarkdownRenderer from "@/components/common/MarkdownRenderer";
import QuizConfigPanel from "@/components/quiz/QuizConfigPanel";
import { useUnifiedChat } from "@/context/UnifiedChatContext";
import { extractBase64FromDataUrl, readFileAsDataUrl } from "@/lib/file-attachments";
import { listKnowledgeBases, type KnowledgeBaseSummary } from "@/lib/knowledge-api";
import {
  createPracticeAttempt,
  getPracticeProgress,
  listPracticeAttempts,
  savePracticeAttemptResults,
  type PracticeAttempt,
  type PracticeDomainProgressRow,
  type PracticeQuizSnapshot,
  type PracticeStructuredResult,
} from "@/lib/practice-api";
import {
  DEFAULT_QUIZ_CONFIG,
  buildQuizWSConfig,
  extractQuizQuestions,
  getQuizQuestionIntegrityError,
  isQuizQuestionUsable,
  type DeepQuestionFormConfig,
  type QuizQuestion,
} from "@/lib/quiz-types";
import {
  PRACTICE_QUIZ_INTENTS,
  applyPracticeQuizIntent,
  buildFlashcardSeedTopic,
  buildPracticeAssessmentSummary,
  buildPracticeQuizPreference,
  buildRetryTopic,
  getPracticeQuizIntent,
  resolvePracticeAttemptSessionId,
  type PracticeQuizIntentId,
} from "@/lib/practice-quiz";
import {
  UnifiedWSClient,
  type StartTurnMessage,
  type StreamEvent,
} from "@/lib/unified-ws";

const PRACTICE_TOOLS = ["rag", "web_search", "code_execution"];

type PracticePhase = "setup" | "generating" | "taking" | "submitting" | "results";

interface PracticeQuizDefinition {
  title: string;
  intro: string;
  questions: QuizQuestion[];
}

function buildPracticeTitle(config: DeepQuestionFormConfig): string {
  if (config.mode === "mimic") {
    return "Practice quiz from paper";
  }
  const topic = config.topic.trim();
  if (!topic) return "Practice quiz";
  return `${topic} practice quiz`;
}

function buildPracticeIntro(config: DeepQuestionFormConfig, examMode: boolean, timerMinutes: number): string {
  const lines = [
    config.mode === "mimic"
      ? "Generated from the uploaded paper or parsed directory."
      : "Generated from your selected topic and quiz controls.",
    examMode
      ? `Soft timer enabled for ${timerMinutes} minute${timerMinutes === 1 ? "" : "s"}.`
      : "Untimed study mode.",
  ];
  return lines.join(" ");
}

function quizQuestionFromStreamEvent(event: StreamEvent): QuizQuestion | null {
  const directPayload = (event as StreamEvent & { question?: Record<string, unknown> }).question;
  const metadataPayload =
    event.metadata &&
    typeof event.metadata === "object" &&
    "question" in event.metadata &&
    event.metadata.question &&
    typeof event.metadata.question === "object"
      ? (event.metadata.question as Record<string, unknown>)
      : undefined;
  const payload = directPayload ?? metadataPayload;
  if (!payload || typeof payload !== "object" || !payload.question) return null;
  const question: QuizQuestion = {
    question_id: String(payload.question_id ?? `practice_q_${Date.now()}`),
    question: String(payload.question ?? ""),
    question_type: (payload.question_type as QuizQuestion["question_type"]) ?? "written",
    options: payload.options as Record<string, string> | undefined,
    correct_answer: String(payload.correct_answer ?? ""),
    explanation: String(payload.explanation ?? ""),
    difficulty: payload.difficulty ? String(payload.difficulty) : undefined,
    concentration: payload.concentration ? String(payload.concentration) : undefined,
    knowledge_context:
      payload.metadata &&
      typeof payload.metadata === "object" &&
      "knowledge_context" in payload.metadata &&
      payload.metadata.knowledge_context
        ? String(payload.metadata.knowledge_context)
        : undefined,
  };
  return isQuizQuestionUsable(question) ? question : null;
}

function practiceProgressStatusText(event: StreamEvent, requestedQuestions: number): string | null {
  const metadata = event.metadata && typeof event.metadata === "object" ? event.metadata : {};
  const updateType = String(metadata.update_type ?? "");
  const status = String(metadata.status ?? "");
  const stage = String(metadata.stage ?? event.stage ?? "");
  const total = Number(metadata.total ?? metadata.requested_total ?? requestedQuestions) || requestedQuestions;
  const batchSize = Number(metadata.batch_size ?? 0);
  const pageSize = Number(metadata.page_size ?? 0);

  if (updateType === "templates_ready") {
    return `Question plan ready. Building ${total} questions now...`;
  }
  if (stage === "ideation" && status === "retrieving_context") {
    return "Finding source context for this practice quiz...";
  }
  if (stage === "generation" && status === "building_first_questions") {
    return "Building the first practice question...";
  }
  if (stage === "generation" && status === "building_starter_page") {
    return pageSize > 0
      ? `Building the first page of ${pageSize} questions...`
      : "Building the first page of questions...";
  }
  if (stage === "generation" && status === "building_remaining_set") {
    return batchSize > 0
      ? `Building ${batchSize} questions in one fast batch...`
      : `Building ${total} questions in one fast batch...`;
  }
  if (stage === "generation" && status === "validating_set") {
    return "Checking quiz quality...";
  }

  const content = String(event.content ?? "").trim();
  if (content && content !== "progress") {
    return content;
  }
  return null;
}

function buildPracticeSnapshot(
  quiz: PracticeQuizDefinition,
  config: DeepQuestionFormConfig,
  examMode: boolean,
  timerMinutes: number,
): PracticeQuizSnapshot {
  return {
    title: quiz.title,
    intro: quiz.intro,
    questions: quiz.questions,
    settings: {
      mode: config.mode,
      topic: config.topic,
      num_questions: config.num_questions,
      difficulty: config.difficulty,
      question_type: config.question_type,
      preference: config.preference,
      paper_path: config.paper_path,
      max_questions: config.max_questions,
      exam_mode: examMode,
      timer_minutes: timerMinutes,
    },
  };
}

function quizFromPracticeAttempt(attempt: PracticeAttempt): PracticeQuizDefinition | null {
  const snapshot = attempt.quiz_snapshot;
  const questions = Array.isArray(snapshot?.questions)
    ? snapshot.questions.map((question, index) => ({
        question_id: question.question_id || `practice_q_${index + 1}`,
        question: question.question,
        question_type: (question.question_type as QuizQuestion["question_type"]) ?? "written",
        options: question.options,
        correct_answer: question.correct_answer ?? "",
        explanation: question.explanation ?? "",
        difficulty: question.difficulty,
        concentration: question.concentration,
      }))
    : [];
  const settings = snapshot?.settings ?? {};
  const rawExpectedCount =
    typeof settings.num_questions === "number" ? settings.num_questions : Number(settings.num_questions);
  const expectedCount = Number.isFinite(rawExpectedCount) && rawExpectedCount > 0
    ? rawExpectedCount
    : questions.length;
  if (getQuizQuestionIntegrityError(questions, expectedCount)) {
    return null;
  }
  return {
    title: snapshot?.title || attempt.title || "Practice quiz",
    intro: snapshot?.intro || "Restored from your saved practice attempt.",
    questions,
  };
}

function restoreConfigFromAttempt(
  current: DeepQuestionFormConfig,
  attempt: PracticeAttempt,
): DeepQuestionFormConfig {
  const settings = attempt.quiz_snapshot?.settings ?? {};
  return {
    ...current,
    mode: settings.mode === "mimic" ? "mimic" : "custom",
    topic: String(settings.topic ?? attempt.topic ?? current.topic),
    num_questions: Number(settings.num_questions) || attempt.quiz_snapshot?.questions?.length || current.num_questions,
    difficulty: String(settings.difficulty ?? current.difficulty),
    question_type: String(settings.question_type ?? current.question_type),
    preference: String(settings.preference ?? current.preference ?? ""),
    paper_path: String(settings.paper_path ?? current.paper_path ?? ""),
    max_questions: Number(settings.max_questions) || current.max_questions,
  };
}

function formatAnswerSummary(index: number, answer: string, question: QuizQuestion): string {
  const cleaned = answer.trim();
  if (!cleaned) return "";
  if (question.question_type === "choice") {
    return `${index}${cleaned.toUpperCase().slice(0, 1)}`;
  }
  const compact = cleaned.replace(/\s+/g, " ").slice(0, 48);
  return `${index}:${compact}`;
}

function buildPracticeSubmissionMessage(
  quiz: PracticeQuizDefinition,
  answers: Record<string, string>,
  knowledgeBases: string[],
  language: string,
): StartTurnMessage {
  const answerMap = quiz.questions
    .map((question, questionIndex) => ({
      index: questionIndex + 1,
      question_id: question.question_id,
      answer: (answers[question.question_id] ?? "").trim(),
    }))
    .filter((item) => item.answer);

  const answerSummary = quiz.questions
    .map((question, questionIndex) =>
      formatAnswerSummary(questionIndex + 1, answers[question.question_id] ?? "", question),
    )
    .filter(Boolean)
    .join(" ");

  return {
    type: "start_turn",
    content: answerSummary || "Practice quiz submission",
    capability: "deep_question",
    tools: [],
    knowledge_bases: knowledgeBases,
    language,
    config: {
      quiz_submission_context: {
        title: quiz.title,
        intro: quiz.intro,
        answers: answerSummary,
        answer_map: answerMap,
        allow_incomplete: true,
        questions: quiz.questions.map((question) => ({
          question_id: question.question_id,
          question: question.question,
          question_type: question.question_type,
          options: question.options ?? {},
        })),
      },
    },
  };
}

function normalizePercent(value: number | null | undefined): number {
  return Number.isFinite(value) ? Number(value) : 0;
}

function formatDuration(seconds: number | null | undefined): string {
  if (!seconds || seconds <= 0) return "0m";
  const wholeSeconds = Math.round(seconds);
  const minutes = Math.floor(wholeSeconds / 60);
  const remainder = wholeSeconds % 60;
  if (minutes <= 0) return `${remainder}s`;
  return remainder ? `${minutes}m ${remainder}s` : `${minutes}m`;
}

function formatTimer(seconds: number): string {
  const safe = Math.max(0, seconds);
  const minutes = Math.floor(safe / 60);
  const remainder = safe % 60;
  return `${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`;
}

function getAttemptPercent(attempt: PracticeAttempt): number {
  return normalizePercent(attempt.score_percent);
}

async function runPracticeTurn(
  message: StartTurnMessage,
  onEvent?: (event: StreamEvent) => void,
): Promise<StreamEvent> {
  return new Promise((resolve, reject) => {
    let resultEvent: StreamEvent | null = null;
    let settled = false;
    let sendAttempts = 0;

    const finalize = (callback: () => void) => {
      if (settled) return;
      settled = true;
      client.disconnect();
      callback();
    };

    const client = new UnifiedWSClient(
      (event) => {
        onEvent?.(event);
        if (event.type === "result") {
          resultEvent = event;
        }
        if (event.type === "error") {
          finalize(() => reject(new Error(event.content || "Turn failed.")));
          return;
        }
        if (event.type === "done") {
          if (resultEvent) {
            finalize(() => resolve(resultEvent as StreamEvent));
          } else {
            finalize(() => reject(new Error("Turn finished without a result payload.")));
          }
        }
      },
      () => {
        finalize(() => reject(new Error("WebSocket connection closed unexpectedly.")));
      },
    );

    const sendWhenReady = () => {
      if (settled) return;
      if (client.connected) {
        client.send(message);
        return;
      }
      sendAttempts += 1;
      if (sendAttempts > 80) {
        finalize(() => reject(new Error("Timed out waiting for the practice connection.")));
        return;
      }
      window.setTimeout(sendWhenReady, 50);
    };

    client.connect();
    sendWhenReady();
  });
}

export default function PracticeWorkspace() {
  const { t } = useTranslation();
  const { state: chatState, selectedSessionId } = useUnifiedChat();

  const [phase, setPhase] = useState<PracticePhase>("setup");
  const [activeIntent, setActiveIntent] = useState<PracticeQuizIntentId>("diagnostic");
  const [quizConfig, setQuizConfig] = useState<DeepQuestionFormConfig>({
    ...DEFAULT_QUIZ_CONFIG,
    topic: "NBCC NCE diagnostic",
    num_questions: 10,
    difficulty: "medium",
    question_type: "choice",
  });
  const [quizSettingsCollapsed, setQuizSettingsCollapsed] = useState(false);
  const [quizPdf, setQuizPdf] = useState<File | null>(null);
  const [examMode, setExamMode] = useState(false);
  const [timerMinutes, setTimerMinutes] = useState(20);
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBaseSummary[]>([]);
  const [selectedKnowledgeBases, setSelectedKnowledgeBases] = useState<string[]>([]);
  const [progressRows, setProgressRows] = useState<PracticeDomainProgressRow[]>([]);
  const [recentAttempts, setRecentAttempts] = useState<PracticeAttempt[]>([]);
  const [activeQuiz, setActiveQuiz] = useState<PracticeQuizDefinition | null>(null);
  const [activeAttempt, setActiveAttempt] = useState<PracticeAttempt | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [currentQuestionIndex, setCurrentQuestionIndex] = useState(0);
  const [resultsFilter, setResultsFilter] = useState<"all" | "wrong">("wrong");
  const [statusText, setStatusText] = useState("");
  const [errorText, setErrorText] = useState("");
  const [startedAtMs, setStartedAtMs] = useState<number | null>(null);
  const [currentTimeMs, setCurrentTimeMs] = useState(Date.now());
  const autoSubmittedRef = useRef(false);
  const restoredAttemptRef = useRef(false);

  useEffect(() => {
    let cancelled = false;

    async function loadSidebarData() {
      try {
        const [kbs, progress, attempts] = await Promise.all([
          listKnowledgeBases({ force: true }),
          getPracticeProgress(),
          listPracticeAttempts(6, 0),
        ]);
        if (cancelled) return;
        setKnowledgeBases(kbs);
        setProgressRows(progress);
        setRecentAttempts(attempts);
        const defaults = kbs.filter((item) => item.is_default).map((item) => item.name);
        const restorableAttempt = attempts.find((attempt) => attempt.status === "in_progress");
        const restoredQuiz = restorableAttempt ? quizFromPracticeAttempt(restorableAttempt) : null;
        setSelectedKnowledgeBases((current) =>
          current.length > 0
            ? current
            : restorableAttempt?.knowledge_base
              ? [restorableAttempt.knowledge_base]
              : defaults.length > 0 ? defaults : kbs.slice(0, 1).map((item) => item.name),
        );
        if (restorableAttempt && restoredQuiz && !restoredAttemptRef.current) {
          restoredAttemptRef.current = true;
          setQuizConfig((current) => restoreConfigFromAttempt(current, restorableAttempt));
          setExamMode(restorableAttempt.mode === "exam");
          const restoredTimerMinutes = restorableAttempt.time_limit_seconds
            ? Math.max(5, Math.round(restorableAttempt.time_limit_seconds / 60))
            : Number(restorableAttempt.quiz_snapshot?.settings?.timer_minutes) || 20;
          setTimerMinutes(restoredTimerMinutes);
          setActiveQuiz(restoredQuiz);
          setActiveAttempt(restorableAttempt);
          setCurrentQuestionIndex(0);
          setAnswers({});
          setStartedAtMs(null);
          setCurrentTimeMs(Date.now());
          setPhase("taking");
        }
      } catch (error) {
        if (!cancelled) {
          console.error("Failed to load practice sidebar data", error);
        }
      }
    }

    void loadSidebarData();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (phase !== "taking" || !examMode || !startedAtMs) return;
    const timer = window.setInterval(() => {
      setCurrentTimeMs(Date.now());
    }, 1000);
    return () => window.clearInterval(timer);
  }, [examMode, phase, startedAtMs]);

  const questionList = useMemo(() => activeQuiz?.questions ?? [], [activeQuiz]);
  const currentQuestion = questionList[currentQuestionIndex] ?? null;
  const answeredCount = useMemo(
    () => questionList.filter((question) => (answers[question.question_id] ?? "").trim()).length,
    [answers, questionList],
  );
  const timeLimitSeconds = examMode ? timerMinutes * 60 : null;
  const elapsedSeconds = startedAtMs ? Math.max(0, Math.round((currentTimeMs - startedAtMs) / 1000)) : 0;
  const remainingSeconds = timeLimitSeconds !== null ? Math.max(0, timeLimitSeconds - elapsedSeconds) : null;

  const filteredResultItems = useMemo(() => {
    const items = activeAttempt?.items ?? [];
    if (resultsFilter === "wrong") {
      return items.filter((item) => !item.is_correct);
    }
    return items;
  }, [activeAttempt?.items, resultsFilter]);

  async function refreshProgressPanels() {
    try {
      const [progress, attempts] = await Promise.all([
        getPracticeProgress(),
        listPracticeAttempts(6, 0),
      ]);
      setProgressRows(progress);
      setRecentAttempts(attempts);
    } catch (error) {
      console.error("Failed to refresh practice progress", error);
    }
  }

  function markStarted() {
    if (!startedAtMs) {
      setStartedAtMs(Date.now());
      setCurrentTimeMs(Date.now());
    }
  }

  function updateAnswer(questionId: string, nextValue: string) {
    markStarted();
    setAnswers((current) => ({ ...current, [questionId]: nextValue }));
  }

  function toggleKnowledgeBase(name: string) {
    setSelectedKnowledgeBases((current) =>
      current.includes(name)
        ? current.filter((item) => item !== name)
        : [...current, name],
    );
  }

  function handleSelectIntent(intentId: PracticeQuizIntentId) {
    setActiveIntent(intentId);
    const nextState = applyPracticeQuizIntent(quizConfig, intentId);
    setQuizConfig(nextState.quizConfig);
    setExamMode(nextState.examMode);
    setTimerMinutes(nextState.timerMinutes);
  }

  async function handleGenerateQuiz() {
    setErrorText("");
    setStatusText("Generating practice quiz...");
    setPhase("generating");
    autoSubmittedRef.current = false;
    setActiveQuiz(null);
    setActiveAttempt(null);
    setAnswers({});
    setCurrentQuestionIndex(0);
    setStartedAtMs(null);
    setCurrentTimeMs(Date.now());

    try {
      const config = buildQuizWSConfig({
        ...quizConfig,
        preference: buildPracticeQuizPreference(quizConfig, activeIntent),
      });
      const attachments =
        quizConfig.mode === "mimic" && quizPdf
          ? [
              {
                type: "pdf",
                filename: quizPdf.name,
                base64: extractBase64FromDataUrl(await readFileAsDataUrl(quizPdf)),
              },
            ]
          : [];
      let readyQuestionCount = 0;
      const streamingQuestions: QuizQuestion[] = [];
      const streamingQuestionIds = new Set<string>();

      const resultEvent = await runPracticeTurn(
        {
          type: "start_turn",
          content: quizConfig.mode === "mimic" ? "Generate practice quiz from paper" : quizConfig.topic.trim(),
          capability: "deep_question",
          tools: PRACTICE_TOOLS,
          knowledge_bases: selectedKnowledgeBases,
          attachments,
          language: chatState.language,
          config,
        },
        (event) => {
          const streamedQuestion = quizQuestionFromStreamEvent(event);
          if (streamedQuestion) {
            readyQuestionCount += 1;
            if (!streamingQuestionIds.has(streamedQuestion.question_id)) {
              streamingQuestionIds.add(streamedQuestion.question_id);
              streamingQuestions.push(streamedQuestion);
              setActiveQuiz({
                title: buildPracticeTitle(quizConfig),
                intro: `${buildPracticeIntro(quizConfig, examMode, timerMinutes)} ${streamingQuestions.length}/${quizConfig.num_questions} ready. You can start now; submit unlocks when the full quiz is saved.`,
                questions: [...streamingQuestions],
              });
              setPhase("taking");
            }
            setStatusText(
              readyQuestionCount === 1
                ? "First question ready. Building the rest..."
                : `${readyQuestionCount} questions ready. Building the rest...`,
            );
            return;
          }
          if (event.type === "thinking" || event.type === "progress" || event.type === "observation") {
            setStatusText(
              practiceProgressStatusText(event, quizConfig.num_questions) || "Generating practice quiz...",
            );
          }
        },
      );

      const parsedQuestions = extractQuizQuestions(resultEvent.metadata);
      if (!parsedQuestions || parsedQuestions.length === 0) {
        throw new Error("The quiz generator finished without usable questions.");
      }
      const expectedQuestionCount =
        quizConfig.mode === "mimic" ? quizConfig.max_questions : quizConfig.num_questions;
      const integrityError = getQuizQuestionIntegrityError(
        parsedQuestions,
        expectedQuestionCount,
      );
      if (integrityError) {
        throw new Error(`The quiz generator returned an incomplete quiz. ${integrityError}`);
      }
      const normalizedQuestions = parsedQuestions.map((question, index) => ({
        ...question,
        question_id: question.question_id || `practice_q_${index + 1}`,
      }));

      const quiz: PracticeQuizDefinition = {
        title: buildPracticeTitle(quizConfig),
        intro: buildPracticeIntro(quizConfig, examMode, timerMinutes),
        questions: normalizedQuestions,
      };
      const attemptSessionId = resolvePracticeAttemptSessionId({
        turnSessionId: resultEvent.session_id ?? null,
        selectedSessionId,
        chatSessionId: chatState.sessionId,
      });
      if (!attemptSessionId) {
        throw new Error("Practice quiz generated, but no session id was available for saving the attempt.");
      }
      const attempt = await createPracticeAttempt({
        session_id: attemptSessionId,
        source_type: "practice",
        source_session_id: resultEvent.session_id ?? null,
        title: quiz.title,
        topic: quizConfig.topic.trim(),
        knowledge_base: selectedKnowledgeBases[0] ?? "",
        mode: examMode ? "exam" : "untimed",
        time_limit_seconds: examMode ? timerMinutes * 60 : null,
        quiz_snapshot: buildPracticeSnapshot(quiz, quizConfig, examMode, timerMinutes),
      });

      setActiveQuiz(quiz);
      setActiveAttempt(attempt);
      setCurrentQuestionIndex((value) => Math.min(value, Math.max(0, quiz.questions.length - 1)));
      setCurrentTimeMs(Date.now());
      setResultsFilter("wrong");
      setPhase("taking");
      setStatusText("");
      void refreshProgressPanels();
    } catch (error) {
      console.error("Failed to generate practice quiz", error);
      setErrorText(error instanceof Error ? error.message : "Failed to generate practice quiz.");
      setPhase("setup");
    }
  }

  const handleSubmitQuiz = useCallback(async (timedOut = false) => {
    if (!activeQuiz || !activeAttempt) return;

    setErrorText("");
    setStatusText(timedOut ? "Time is up. Grading your practice set..." : "Grading your practice set...");
    setPhase("submitting");

    try {
      const resultEvent = await runPracticeTurn(
        buildPracticeSubmissionMessage(
          activeQuiz,
          answers,
          selectedKnowledgeBases,
          chatState.language,
        ),
        (event) => {
          if (event.type === "thinking" || event.type === "progress" || event.type === "observation") {
            setStatusText(event.content || "Grading your practice set...");
          }
        },
      );

      const structuredResult = resultEvent.metadata.structured_result as PracticeStructuredResult | undefined;
      if (!structuredResult) {
        throw new Error("The grader finished without structured quiz results.");
      }

      const savedAttempt = await savePracticeAttemptResults(activeAttempt.id, {
        submitted_at: Date.now() / 1000,
        duration_seconds: startedAtMs ? (Date.now() - startedAtMs) / 1000 : 0,
        timed_out: timedOut,
        structured_result: structuredResult,
      });

      setActiveAttempt(savedAttempt);
      setResultsFilter("wrong");
      setPhase("results");
      setStatusText("");
      void refreshProgressPanels();
    } catch (error) {
      console.error("Failed to submit practice quiz", error);
      setErrorText(error instanceof Error ? error.message : "Failed to submit practice quiz.");
      setPhase("taking");
    }
  }, [activeAttempt, activeQuiz, answers, chatState.language, selectedKnowledgeBases, startedAtMs]);

  useEffect(() => {
    if (
      phase !== "taking" ||
      !examMode ||
      remainingSeconds === null ||
      remainingSeconds > 0 ||
      autoSubmittedRef.current
    ) {
      return;
    }
    autoSubmittedRef.current = true;
    void handleSubmitQuiz(true);
  }, [examMode, handleSubmitQuiz, phase, remainingSeconds]);

  function resetToSetup() {
    setPhase("setup");
    setActiveQuiz(null);
    setActiveAttempt(null);
    setAnswers({});
    setCurrentQuestionIndex(0);
    setStartedAtMs(null);
    setCurrentTimeMs(Date.now());
    setStatusText("");
    setErrorText("");
    autoSubmittedRef.current = false;
  }

  function prepareRetryFromWeakDomains() {
    if (!attemptResult) return;
    setQuizConfig((current) => ({
      ...current,
      mode: "custom",
      topic: buildRetryTopic(activeAttempt?.topic || current.topic, attemptResult),
      num_questions: Math.min(12, Math.max(6, weakDomains.length * 4 || 8)),
      difficulty: "medium",
      question_type: "choice",
    }));
    setActiveIntent("diagnostic");
    setExamMode(false);
    setTimerMinutes(20);
    setResultsFilter("wrong");
    setPhase("setup");
  }

  const attemptResult = activeAttempt?.result_summary as PracticeStructuredResult | undefined;
  const weakDomains = useMemo(
    () => (attemptResult ? attemptResult.weakest_areas ?? [] : []),
    [attemptResult],
  );
  const strongestAreas = useMemo(
    () => (attemptResult ? attemptResult.strongest_areas ?? [] : []),
    [attemptResult],
  );
  const assessmentSummary = useMemo(
    () =>
      buildPracticeAssessmentSummary(
        quizConfig,
        activeIntent,
        examMode,
        timerMinutes,
        selectedKnowledgeBases.length,
      ),
    [activeIntent, examMode, quizConfig, selectedKnowledgeBases.length, timerMinutes],
  );

  return (
    <div className="h-full overflow-y-auto bg-[radial-gradient(circle_at_top_left,rgba(67,56,202,0.08),transparent_28%),radial-gradient(circle_at_top_right,rgba(14,165,233,0.08),transparent_22%),var(--background)]">
      <div className="mx-auto flex max-w-[1440px] gap-6 px-6 py-6">
        <section className="min-w-0 flex-1 space-y-5">
          <div className="rounded-[28px] border border-[var(--border)] bg-[var(--card)]/95 p-6 shadow-[0_20px_70px_rgba(15,23,42,0.08)]">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div className="max-w-2xl space-y-2">
                <div className="inline-flex items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--background)] px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-[var(--muted-foreground)]">
                  <ClipboardCheck size={13} />
                  {t("Practice Mode")}
                </div>
                <h1 className="text-[28px] font-semibold tracking-tight text-[var(--foreground)]">
                  {t("Study in a dedicated test flow, not in chat bubbles.")}
                </h1>
                <p className="max-w-[760px] text-[14px] leading-7 text-[var(--muted-foreground)]">
                  {t(
                    "Generate a targeted quiz, take it with optional exam timing, submit once, and get inline scoring, domain feedback, and wrong-answer review without leaving the page.",
                  )}
                </p>
                <div className="flex flex-wrap gap-2">
                  <span className="rounded-full bg-[var(--primary)] px-3 py-1.5 text-[12px] font-semibold text-white">
                    {t("Quiz")}
                  </span>
                  <Link
                    href="/practice/flashcards"
                    className="inline-flex items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--background)] px-3 py-1.5 text-[12px] font-medium text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)]"
                  >
                    <Sparkles size={13} />
                    {t("Flashcards preview")}
                  </Link>
                </div>
              </div>

              <div className="grid min-w-[240px] grid-cols-2 gap-3">
                <div className="rounded-2xl border border-[var(--border)] bg-[var(--background)]/70 p-4">
                  <div className="text-[11px] uppercase tracking-[0.18em] text-[var(--muted-foreground)]">
                    {t("Recent attempts")}
                  </div>
                  <div className="mt-2 text-[26px] font-semibold text-[var(--foreground)]">
                    {recentAttempts.length}
                  </div>
                </div>
                <div className="rounded-2xl border border-[var(--border)] bg-[var(--background)]/70 p-4">
                  <div className="text-[11px] uppercase tracking-[0.18em] text-[var(--muted-foreground)]">
                    {t("Tracked domains")}
                  </div>
                  <div className="mt-2 text-[26px] font-semibold text-[var(--foreground)]">
                    {progressRows.length}
                  </div>
                </div>
              </div>
            </div>
          </div>

          {errorText ? (
            <div className="flex items-start gap-3 rounded-2xl border border-amber-300/40 bg-amber-100/60 px-4 py-3 text-[13px] text-amber-950 dark:border-amber-700/40 dark:bg-amber-950/20 dark:text-amber-100">
              <TriangleAlert size={16} className="mt-0.5 shrink-0" />
              <div>{errorText}</div>
            </div>
          ) : null}

          {(phase === "generating" || phase === "submitting") ? (
            <div className="rounded-[28px] border border-[var(--border)] bg-[var(--card)] p-8">
              <div className="flex items-center gap-3 text-[14px] text-[var(--muted-foreground)]">
                <Loader2 className="animate-spin" size={18} />
                <span>{statusText || (phase === "generating" ? t("Generating practice quiz...") : t("Scoring your quiz..."))}</span>
              </div>
            </div>
          ) : null}

          {phase === "setup" ? (
            <div className="rounded-[28px] border border-[var(--border)] bg-[var(--card)] p-6 shadow-[0_16px_50px_rgba(15,23,42,0.06)]">
              <div className="space-y-5">
                <div className="space-y-2">
                  <div className="text-[12px] font-semibold uppercase tracking-[0.18em] text-[var(--muted-foreground)]">
                    {t("Assessment Intent")}
                  </div>
                  <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                    {PRACTICE_QUIZ_INTENTS.map((intent) => {
                      const active = activeIntent === intent.id;
                      return (
                        <button
                          key={intent.id}
                          type="button"
                          onClick={() => handleSelectIntent(intent.id)}
                          className={`rounded-2xl border px-4 py-4 text-left transition-colors ${
                            active
                              ? "border-[var(--primary)] bg-[var(--primary)]/8"
                              : "border-[var(--border)] bg-[var(--background)] hover:border-[var(--primary)]/30"
                          }`}
                        >
                          <div className="flex items-center justify-between gap-3">
                            <div className="text-[14px] font-semibold text-[var(--foreground)]">
                              {t(intent.label)}
                            </div>
                            {active ? (
                              <span className="rounded-full bg-[var(--primary)] px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] text-white">
                                {t("Selected")}
                              </span>
                            ) : null}
                          </div>
                          <div className="mt-2 text-[13px] leading-6 text-[var(--muted-foreground)]">
                            {t(intent.description)}
                          </div>
                          <div className="mt-3 flex flex-wrap gap-2">
                            <span className="rounded-full border border-[var(--border)] bg-[var(--card)] px-2.5 py-1 text-[11px] font-medium text-[var(--muted-foreground)]">
                              {intent.numQuestions} {t("questions")}
                            </span>
                            <span className="rounded-full border border-[var(--border)] bg-[var(--card)] px-2.5 py-1 text-[11px] font-medium text-[var(--muted-foreground)]">
                              {t(intent.examMode ? "Timed" : "Untimed")}
                            </span>
                          </div>
                        </button>
                      );
                    })}
                  </div>
                </div>

                <div className="grid gap-4 lg:grid-cols-[1.25fr_0.75fr]">
                  <div className="space-y-3">
                    <label className="block">
                      <div className="mb-2 text-[12px] font-semibold uppercase tracking-[0.18em] text-[var(--muted-foreground)]">
                        {t("Topic")}
                      </div>
                      <textarea
                        value={quizConfig.topic}
                        onChange={(event) =>
                          setQuizConfig((current) => ({ ...current, topic: event.target.value }))
                        }
                        rows={3}
                        className="w-full rounded-2xl border border-[var(--border)] bg-[var(--background)] px-4 py-3 text-[14px] text-[var(--foreground)] outline-none transition-colors focus:border-[var(--primary)]/40"
                        placeholder={t("Examples: NCE helping relationships, ethics traps, career development case vignettes")}
                      />
                    </label>

                    <div className="rounded-2xl border border-[var(--border)] bg-[var(--background)]/70">
                      <QuizConfigPanel
                        value={quizConfig}
                        onChange={setQuizConfig}
                        uploadedPdf={quizPdf}
                        onUploadPdf={setQuizPdf}
                        collapsed={quizSettingsCollapsed}
                        onToggleCollapsed={() => setQuizSettingsCollapsed((current) => !current)}
                      />
                    </div>
                  </div>

                  <div className="space-y-4 rounded-2xl border border-[var(--border)] bg-[var(--background)]/70 p-4">
                    <div className="rounded-2xl border border-[var(--border)] bg-[var(--card)] px-4 py-4">
                      <div className="text-[12px] font-semibold uppercase tracking-[0.18em] text-[var(--muted-foreground)]">
                        {t("Assessment summary")}
                      </div>
                      <div className="mt-2 text-[14px] font-medium text-[var(--foreground)]">
                        {assessmentSummary}
                      </div>
                      <ul className="mt-3 space-y-2 text-[13px] leading-6 text-[var(--muted-foreground)]">
                        {getPracticeQuizIntent(activeIntent).qualityNotes.slice(0, 2).map((note) => (
                          <li key={note}>{t(note)}</li>
                        ))}
                      </ul>
                    </div>

                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <div className="text-[12px] font-semibold uppercase tracking-[0.18em] text-[var(--muted-foreground)]">
                          {t("Exam Timer")}
                        </div>
                        <div className="mt-1 text-[13px] text-[var(--muted-foreground)]">
                          {t("Soft timer only. Results still submit automatically when time runs out.")}
                        </div>
                      </div>
                      <button
                        type="button"
                        onClick={() => setExamMode((current) => !current)}
                        className={`inline-flex h-7 w-14 items-center rounded-full border px-1 transition-colors ${
                          examMode
                            ? "border-[var(--primary)] bg-[var(--primary)]/15"
                            : "border-[var(--border)] bg-[var(--muted)]"
                        }`}
                      >
                        <span
                          className={`h-5 w-5 rounded-full bg-white shadow-sm transition-transform ${
                            examMode ? "translate-x-7" : "translate-x-0"
                          }`}
                        />
                      </button>
                    </div>

                    <label className="block">
                      <div className="mb-2 text-[12px] font-semibold uppercase tracking-[0.18em] text-[var(--muted-foreground)]">
                        {t("Minutes")}
                      </div>
                      <input
                        type="number"
                        min={5}
                        max={180}
                        value={timerMinutes}
                        onChange={(event) => setTimerMinutes(Math.max(5, Number(event.target.value) || 5))}
                        disabled={!examMode}
                        className="w-full rounded-xl border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-[14px] text-[var(--foreground)] outline-none disabled:opacity-50"
                      />
                    </label>

                    <div>
                      <div className="mb-2 text-[12px] font-semibold uppercase tracking-[0.18em] text-[var(--muted-foreground)]">
                        {t("Knowledge Bases")}
                      </div>
                      <div className="flex flex-wrap gap-2">
                        {knowledgeBases.length > 0 ? (
                          knowledgeBases.map((kb) => {
                            const active = selectedKnowledgeBases.includes(kb.name);
                            return (
                              <button
                                key={kb.name}
                                type="button"
                                onClick={() => toggleKnowledgeBase(kb.name)}
                                className={`rounded-full border px-3 py-1.5 text-[12px] font-medium transition-colors ${
                                  active
                                    ? "border-[var(--primary)] bg-[var(--primary)]/10 text-[var(--foreground)]"
                                    : "border-[var(--border)] bg-[var(--background)] text-[var(--muted-foreground)]"
                                }`}
                              >
                                {kb.name}
                              </button>
                            );
                          })
                        ) : (
                          <div className="text-[13px] text-[var(--muted-foreground)]">{t("No knowledge bases loaded.")}</div>
                        )}
                      </div>
                    </div>

                    <button
                      type="button"
                      onClick={() => void handleGenerateQuiz()}
                      disabled={!quizConfig.topic.trim() && quizConfig.mode === "custom"}
                      className="inline-flex w-full items-center justify-center gap-2 rounded-2xl bg-[var(--primary)] px-4 py-3 text-[14px] font-semibold text-white transition-opacity disabled:opacity-40"
                    >
                      <BrainCircuit size={16} />
                      {t(`Generate ${getPracticeQuizIntent(activeIntent).label.toLowerCase()}`)}
                    </button>
                  </div>
                </div>
              </div>
            </div>
          ) : null}

          {phase === "taking" && activeQuiz && currentQuestion ? (
            <div className="space-y-4">
              <div className="rounded-[28px] border border-[var(--border)] bg-[var(--card)] p-5 shadow-[0_16px_50px_rgba(15,23,42,0.06)]">
                <div className="flex flex-wrap items-center justify-between gap-4">
                  <div>
                    <div className="text-[12px] font-semibold uppercase tracking-[0.18em] text-[var(--muted-foreground)]">
                      {t("Active quiz")}
                    </div>
                    <div className="mt-1 text-[24px] font-semibold text-[var(--foreground)]">{activeQuiz.title}</div>
                    <div className="mt-2 text-[13px] text-[var(--muted-foreground)]">{activeQuiz.intro}</div>
                  </div>

                  <div className="flex flex-wrap items-center gap-3">
                    <div className="rounded-2xl border border-[var(--border)] bg-[var(--background)] px-4 py-3 text-[13px] text-[var(--muted-foreground)]">
                      {answeredCount}/{activeQuiz.questions.length} {t("answered")}
                    </div>
                    {examMode && remainingSeconds !== null ? (
                      <div className={`rounded-2xl border px-4 py-3 text-[13px] font-semibold ${
                        remainingSeconds <= 60
                          ? "border-rose-400/50 bg-rose-500/10 text-rose-700 dark:text-rose-200"
                          : "border-[var(--border)] bg-[var(--background)] text-[var(--foreground)]"
                      }`}>
                        <div className="flex items-center gap-2">
                          <AlarmClockCheck size={15} />
                          {formatTimer(remainingSeconds)}
                        </div>
                      </div>
                    ) : (
                      <div className="rounded-2xl border border-[var(--border)] bg-[var(--background)] px-4 py-3 text-[13px] text-[var(--muted-foreground)]">
                        {t("Untimed")}
                      </div>
                    )}
                  </div>
                </div>
              </div>

              <div className="rounded-[28px] border border-[var(--border)] bg-[var(--card)] p-6 shadow-[0_16px_50px_rgba(15,23,42,0.06)]">
                <div className="flex flex-wrap gap-2">
                  {activeQuiz.questions.map((question, index) => {
                    const value = (answers[question.question_id] ?? "").trim();
                    const isCurrent = index === currentQuestionIndex;
                    return (
                      <button
                        key={question.question_id}
                        type="button"
                        onClick={() => setCurrentQuestionIndex(index)}
                        className={`h-8 min-w-8 rounded-full px-3 text-[12px] font-semibold transition-colors ${
                          isCurrent
                            ? "bg-[var(--primary)] text-white"
                            : value
                              ? "bg-[var(--primary)]/12 text-[var(--foreground)]"
                              : "bg-[var(--muted)] text-[var(--muted-foreground)]"
                        }`}
                      >
                        {index + 1}
                      </button>
                    );
                  })}
                </div>

                <div className="mt-6 space-y-5">
                  <div className="flex items-center gap-2 text-[12px] font-semibold uppercase tracking-[0.18em] text-[var(--muted-foreground)]">
                    <span className="rounded-full border border-[var(--border)] bg-[var(--background)] px-2 py-1">
                      {t("Question")} {currentQuestionIndex + 1}
                    </span>
                    <span className="rounded-full border border-[var(--border)] bg-[var(--background)] px-2 py-1">
                      {currentQuestion.question_type === "choice" ? t("Multiple choice") : t("Written")}
                    </span>
                  </div>

                  <div className="text-[15px] leading-7 text-[var(--foreground)]">
                    <MarkdownRenderer content={currentQuestion.question} variant="prose" />
                  </div>

                  {currentQuestion.question_type === "choice" && currentQuestion.options ? (
                    <div className="space-y-3">
                      {Object.entries(currentQuestion.options).map(([key, value]) => {
                        const selected = (answers[currentQuestion.question_id] ?? "") === key;
                        return (
                          <button
                            key={key}
                            type="button"
                            onClick={() => updateAnswer(currentQuestion.question_id, key)}
                            className={`flex w-full items-start gap-3 rounded-2xl border px-4 py-3 text-left transition-colors ${
                              selected
                                ? "border-[var(--primary)] bg-[var(--primary)]/8"
                                : "border-[var(--border)] bg-[var(--background)] hover:border-[var(--primary)]/30"
                            }`}
                          >
                            <span className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border text-[12px] font-semibold ${
                              selected
                                ? "border-[var(--primary)] bg-[var(--primary)] text-white"
                                : "border-[var(--border)] text-[var(--muted-foreground)]"
                            }`}>
                              {key}
                            </span>
                            <span className="text-[14px] leading-6 text-[var(--foreground)]">{value}</span>
                          </button>
                        );
                      })}
                    </div>
                  ) : (
                    <textarea
                      value={answers[currentQuestion.question_id] ?? ""}
                      onChange={(event) => updateAnswer(currentQuestion.question_id, event.target.value)}
                      rows={6}
                      className="w-full rounded-2xl border border-[var(--border)] bg-[var(--background)] px-4 py-3 text-[14px] leading-6 text-[var(--foreground)] outline-none transition-colors focus:border-[var(--primary)]/40"
                      placeholder={t("Write your answer here")}
                    />
                  )}
                </div>

                <div className="mt-6 flex flex-wrap items-center justify-between gap-3 border-t border-[var(--border)] pt-4">
                  <div className="text-[12px] text-[var(--muted-foreground)]">
                    {examMode
                      ? t("The timer starts on your first answer and auto-submits whatever is complete.")
                      : t("You can submit anytime. Unanswered questions will be scored as no answer.")}
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <button
                      type="button"
                      onClick={() => setCurrentQuestionIndex((value) => Math.max(0, value - 1))}
                      disabled={currentQuestionIndex === 0}
                      className="inline-flex items-center gap-1 rounded-xl border border-[var(--border)] px-3 py-2 text-[13px] text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)] disabled:opacity-40"
                    >
                      <ArrowLeft size={14} />
                      {t("Previous")}
                    </button>
                    <button
                      type="button"
                      onClick={() => setCurrentQuestionIndex((value) => Math.min(questionList.length - 1, value + 1))}
                      disabled={currentQuestionIndex === questionList.length - 1}
                      className="inline-flex items-center gap-1 rounded-xl border border-[var(--border)] px-3 py-2 text-[13px] text-[var(--muted-foreground)] transition-colors hover:text-[var(--foreground)] disabled:opacity-40"
                    >
                      {t("Next")}
                      <ArrowRight size={14} />
                    </button>
                    <button
                      type="button"
                      onClick={() => void handleSubmitQuiz(false)}
                      disabled={!activeAttempt}
                      className="inline-flex items-center gap-2 rounded-xl bg-[var(--primary)] px-4 py-2 text-[13px] font-semibold text-white transition-opacity disabled:opacity-50"
                    >
                      <Send size={14} />
                      {activeAttempt ? t("Submit quiz") : t("Finalizing quiz...")}
                    </button>
                  </div>
                </div>
              </div>
            </div>
          ) : null}

          {phase === "results" && activeAttempt && attemptResult ? (
            <div className="space-y-4">
              <div className="rounded-[28px] border border-[var(--border)] bg-[var(--card)] p-6 shadow-[0_16px_50px_rgba(15,23,42,0.06)]">
                <div className="flex flex-wrap items-start justify-between gap-4">
                  <div>
                    <div className="text-[12px] font-semibold uppercase tracking-[0.18em] text-[var(--muted-foreground)]">
                      {t("Results")}
                    </div>
                    <div className="mt-1 text-[30px] font-semibold text-[var(--foreground)]">
                      {activeAttempt.score_correct ?? attemptResult.score.correct}/{activeAttempt.score_total ?? attemptResult.score.total}
                    </div>
                    <div className="mt-2 text-[14px] text-[var(--muted-foreground)]">
                      {attemptResult.overall_summary || t("Detailed quiz results are ready below.")}
                    </div>
                  </div>

                  <div className="grid min-w-[280px] grid-cols-3 gap-3">
                    <div className="rounded-2xl border border-[var(--border)] bg-[var(--background)] px-4 py-3">
                      <div className="text-[11px] uppercase tracking-[0.18em] text-[var(--muted-foreground)]">{t("Percent")}</div>
                      <div className="mt-2 text-[24px] font-semibold text-[var(--foreground)]">
                        {normalizePercent(activeAttempt.score_percent ?? attemptResult.score.percent).toFixed(0)}%
                      </div>
                    </div>
                    <div className="rounded-2xl border border-[var(--border)] bg-[var(--background)] px-4 py-3">
                      <div className="text-[11px] uppercase tracking-[0.18em] text-[var(--muted-foreground)]">{t("Time")}</div>
                      <div className="mt-2 text-[24px] font-semibold text-[var(--foreground)]">
                        {formatDuration(activeAttempt.duration_seconds)}
                      </div>
                    </div>
                    <div className="rounded-2xl border border-[var(--border)] bg-[var(--background)] px-4 py-3">
                      <div className="text-[11px] uppercase tracking-[0.18em] text-[var(--muted-foreground)]">{t("Missed")}</div>
                      <div className="mt-2 text-[24px] font-semibold text-[var(--foreground)]">
                        {(activeAttempt.items ?? []).filter((item) => !item.is_correct).length}
                      </div>
                    </div>
                  </div>
                </div>

                <div className="mt-5 flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => setResultsFilter("wrong")}
                    className={`rounded-full px-3 py-1.5 text-[12px] font-semibold ${
                      resultsFilter === "wrong"
                        ? "bg-[var(--primary)] text-white"
                        : "border border-[var(--border)] text-[var(--muted-foreground)]"
                    }`}
                  >
                    {t("Review weak spots")}
                  </button>
                  <button
                    type="button"
                    onClick={() => setResultsFilter("all")}
                    className={`rounded-full px-3 py-1.5 text-[12px] font-semibold ${
                      resultsFilter === "all"
                        ? "bg-[var(--primary)] text-white"
                        : "border border-[var(--border)] text-[var(--muted-foreground)]"
                    }`}
                  >
                    {t("Show all questions")}
                  </button>
                  <button
                    type="button"
                    onClick={prepareRetryFromWeakDomains}
                    className="rounded-full border border-[var(--border)] px-3 py-1.5 text-[12px] font-semibold text-[var(--muted-foreground)]"
                  >
                    {t("Retry missed domains")}
                  </button>
                  <Link
                    href={`/practice/flashcards?topic=${encodeURIComponent(buildFlashcardSeedTopic(activeAttempt.topic || "", attemptResult))}`}
                    className="rounded-full border border-[var(--border)] px-3 py-1.5 text-[12px] font-semibold text-[var(--muted-foreground)]"
                  >
                    {t("Make flashcards from this")}
                  </Link>
                  <button
                    type="button"
                    onClick={resetToSetup}
                    className="inline-flex items-center gap-1 rounded-full border border-[var(--border)] px-3 py-1.5 text-[12px] font-semibold text-[var(--muted-foreground)]"
                  >
                    <RefreshCcw size={13} />
                    {t("New quiz")}
                  </button>
                  <Link
                    href="/chat"
                    className="inline-flex items-center gap-1 rounded-full border border-[var(--border)] px-3 py-1.5 text-[12px] font-semibold text-[var(--muted-foreground)]"
                  >
                    <ArrowLeft size={13} />
                    {t("Review misses in chat")}
                  </Link>
                </div>
              </div>

              <div className="grid gap-4 lg:grid-cols-3">
                <div className="rounded-[28px] border border-[var(--border)] bg-[var(--card)] p-5 shadow-[0_16px_50px_rgba(15,23,42,0.06)]">
                  <div className="text-[12px] font-semibold uppercase tracking-[0.18em] text-[var(--muted-foreground)]">
                    {t("Next study move")}
                  </div>
                  <div className="mt-3 text-[14px] leading-7 text-[var(--foreground)]">
                    {attemptResult.recommended_next_step || t("Review the misses first, then make a short flashcard deck from the weakest domains.")}
                  </div>
                  <div className="mt-4 text-[12px] leading-5 text-[var(--muted-foreground)]">
                    {t("This result can become a retry quiz, a focused flashcard deck, or a chat review instead of ending as a score.")}
                  </div>
                </div>
                <div className="rounded-[28px] border border-[var(--border)] bg-[var(--card)] p-5 shadow-[0_16px_50px_rgba(15,23,42,0.06)]">
                  <div className="text-[12px] font-semibold uppercase tracking-[0.18em] text-[var(--muted-foreground)]">
                    {t("Coach read")}
                  </div>
                  <div className="mt-3 text-[14px] leading-7 text-[var(--foreground)]">
                    {attemptResult.overall_summary || t("Detailed quiz results are ready below.")}
                  </div>
                  {attemptResult.recommended_next_step ? (
                    <div className="mt-4 rounded-2xl border border-[var(--border)] bg-[var(--background)] px-4 py-3 text-[13px] text-[var(--muted-foreground)]">
                      {attemptResult.recommended_next_step}
                    </div>
                  ) : null}
                </div>

                <div className="rounded-[28px] border border-[var(--border)] bg-[var(--card)] p-5 shadow-[0_16px_50px_rgba(15,23,42,0.06)]">
                  <div className="text-[12px] font-semibold uppercase tracking-[0.18em] text-[var(--muted-foreground)]">
                    {t("Strongest areas")}
                  </div>
                  <div className="mt-4 flex flex-wrap gap-2">
                    {strongestAreas.length > 0 ? (
                      strongestAreas.map((area) => (
                        <span
                          key={area}
                          className="rounded-full bg-emerald-500/12 px-3 py-1 text-[12px] font-medium text-emerald-700 dark:text-emerald-300"
                        >
                          {area}
                        </span>
                      ))
                    ) : (
                      <div className="text-[13px] text-[var(--muted-foreground)]">
                        {t("Strong areas will show up here once the grader can distinguish them clearly.")}
                      </div>
                    )}
                  </div>
                </div>

                <div className="rounded-[28px] border border-[var(--border)] bg-[var(--card)] p-5 shadow-[0_16px_50px_rgba(15,23,42,0.06)]">
                  <div className="text-[12px] font-semibold uppercase tracking-[0.18em] text-[var(--muted-foreground)]">
                    {t("Weak spots")}
                  </div>
                  <div className="mt-4 flex flex-wrap gap-2">
                    {weakDomains.length > 0 ? (
                      weakDomains.map((area) => (
                        <span
                          key={area}
                          className="rounded-full bg-rose-500/12 px-3 py-1 text-[12px] font-medium text-rose-700 dark:text-rose-300"
                        >
                          {area}
                        </span>
                      ))
                    ) : (
                      <div className="text-[13px] text-[var(--muted-foreground)]">
                        {t("Weak spots will appear here when the results surface can confidently name them.")}
                      </div>
                    )}
                  </div>
                </div>
              </div>

              <div className="rounded-[28px] border border-[var(--border)] bg-[var(--card)] p-6 shadow-[0_16px_50px_rgba(15,23,42,0.06)]">
                <div className="mb-4 text-[12px] font-semibold uppercase tracking-[0.18em] text-[var(--muted-foreground)]">
                  {t("Domain breakdown")}
                </div>
                <div className="grid gap-3 lg:grid-cols-2">
                  {attemptResult.domain_breakdown.map((item) => (
                    <div key={item.domain} className="rounded-2xl border border-[var(--border)] bg-[var(--background)] p-4">
                      <div className="flex items-center justify-between gap-3">
                        <div className="text-[14px] font-medium text-[var(--foreground)]">{item.domain}</div>
                        <div className="text-[13px] text-[var(--muted-foreground)]">
                          {item.correct}/{item.total}
                        </div>
                      </div>
                      <div className="mt-3 h-2 overflow-hidden rounded-full bg-[var(--muted)]">
                        <div
                          className="h-full rounded-full bg-[linear-gradient(90deg,var(--primary),rgba(59,130,246,0.75))]"
                          style={{ width: `${item.percent}%` }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div className="rounded-[28px] border border-[var(--border)] bg-[var(--card)] p-6 shadow-[0_16px_50px_rgba(15,23,42,0.06)]">
                <div className="mb-4 text-[12px] font-semibold uppercase tracking-[0.18em] text-[var(--muted-foreground)]">
                  {resultsFilter === "wrong" ? t("Missed questions") : t("Question review")}
                </div>
                <div className="space-y-3">
                  {filteredResultItems.map((item) => (
                    <div key={`${item.attempt_id}-${item.question_id}`} className="rounded-2xl border border-[var(--border)] bg-[var(--background)] p-4">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="rounded-full bg-[var(--muted)] px-2 py-1 text-[11px] font-semibold text-[var(--muted-foreground)]">
                          {t("Q")} {item.display_order}
                        </span>
                        {item.domain ? (
                          <span className="rounded-full border border-[var(--border)] px-2 py-1 text-[11px] font-medium text-[var(--muted-foreground)]">
                            {item.domain}
                          </span>
                        ) : null}
                        <span className={`rounded-full px-2 py-1 text-[11px] font-semibold ${
                          item.is_correct
                            ? "bg-emerald-500/12 text-emerald-700 dark:text-emerald-300"
                            : "bg-rose-500/12 text-rose-700 dark:text-rose-300"
                        }`}>
                          {item.is_correct ? t("Correct") : t("Incorrect")}
                        </span>
                      </div>
                      <div className="mt-3 text-[14px] leading-7 text-[var(--foreground)]">
                        <MarkdownRenderer content={item.question_text} variant="prose" />
                      </div>
                      <div className="mt-4 grid gap-3 md:grid-cols-2">
                        <div className="rounded-2xl border border-[var(--border)] bg-[var(--card)] px-4 py-3">
                          <div className="text-[11px] uppercase tracking-[0.18em] text-[var(--muted-foreground)]">{t("Your answer")}</div>
                          <div className="mt-2 text-[14px] text-[var(--foreground)]">{item.user_answer || t("No answer")}</div>
                        </div>
                        <div className="rounded-2xl border border-[var(--border)] bg-[var(--card)] px-4 py-3">
                          <div className="text-[11px] uppercase tracking-[0.18em] text-[var(--muted-foreground)]">{t("Correct answer")}</div>
                          <div className="mt-2 text-[14px] text-[var(--foreground)]">{item.correct_answer || t("Not provided")}</div>
                        </div>
                      </div>
                      {item.explanation ? (
                        <div className="mt-4 rounded-2xl border border-[var(--border)] bg-[var(--card)] px-4 py-3">
                          <div className="text-[11px] uppercase tracking-[0.18em] text-[var(--muted-foreground)]">{t("Explanation")}</div>
                          <div className="mt-2 text-[14px] leading-7 text-[var(--foreground)]">{item.explanation}</div>
                        </div>
                      ) : null}
                      {item.coaching_note ? (
                        <div className="mt-3 flex items-start gap-2 rounded-2xl border border-[var(--border)] bg-[var(--card)] px-4 py-3 text-[13px] text-[var(--muted-foreground)]">
                          <CheckCircle2 size={15} className="mt-0.5 shrink-0" />
                          <div>{item.coaching_note}</div>
                        </div>
                      ) : null}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          ) : null}
        </section>

        <aside className="hidden w-[340px] shrink-0 space-y-4 xl:block">
          <div className="rounded-[28px] border border-[var(--border)] bg-[var(--card)] p-5 shadow-[0_16px_50px_rgba(15,23,42,0.06)]">
            <div className="mb-4 flex items-center gap-2 text-[12px] font-semibold uppercase tracking-[0.18em] text-[var(--muted-foreground)]">
              <TimerReset size={14} />
              {t("Domain progress")}
            </div>
            <div className="space-y-3">
              {progressRows.length > 0 ? (
                progressRows.map((row) => (
                  <div key={row.domain} className="rounded-2xl border border-[var(--border)] bg-[var(--background)] p-4">
                    <div className="flex items-center justify-between gap-3">
                      <div className="text-[14px] font-medium text-[var(--foreground)]">{row.domain}</div>
                      <div className="text-[12px] text-[var(--muted-foreground)]">
                        {row.recent.percent.toFixed(0)}%
                      </div>
                    </div>
                    <div className="mt-3 h-2 overflow-hidden rounded-full bg-[var(--muted)]">
                      <div
                        className="h-full rounded-full bg-[linear-gradient(90deg,var(--primary),rgba(56,189,248,0.8))]"
                        style={{ width: `${row.recent.percent}%` }}
                      />
                    </div>
                    <div className="mt-3 flex items-center justify-between text-[12px] text-[var(--muted-foreground)]">
                      <span>{t("Recent")} {row.recent.correct}/{row.recent.total}</span>
                      <span>{t("Lifetime")} {row.lifetime.correct}/{row.lifetime.total}</span>
                    </div>
                  </div>
                ))
              ) : (
                <div className="rounded-2xl border border-dashed border-[var(--border)] bg-[var(--background)] px-4 py-5 text-[13px] text-[var(--muted-foreground)]">
                  {t("Finish a quiz and your domain trends will appear here.")}
                </div>
              )}
            </div>
          </div>

          <div className="rounded-[28px] border border-[var(--border)] bg-[var(--card)] p-5 shadow-[0_16px_50px_rgba(15,23,42,0.06)]">
            <div className="mb-4 text-[12px] font-semibold uppercase tracking-[0.18em] text-[var(--muted-foreground)]">
              {t("Recent attempts")}
            </div>
            <div className="space-y-3">
              {recentAttempts.length > 0 ? (
                recentAttempts.map((attempt) => (
                  <div key={attempt.id} className="rounded-2xl border border-[var(--border)] bg-[var(--background)] p-4">
                    <div className="flex items-center justify-between gap-3">
                      <div className="text-[13px] font-medium text-[var(--foreground)]">
                        {attempt.quiz_snapshot?.title || t("Practice quiz")}
                      </div>
                      <div className="text-[12px] text-[var(--muted-foreground)]">
                        {attempt.score_total ? `${attempt.score_correct}/${attempt.score_total}` : t("In progress")}
                      </div>
                    </div>
                    <div className="mt-2 text-[12px] text-[var(--muted-foreground)]">
                      {attempt.status === "timed_out" ? t("Timed out") : attempt.status === "submitted" ? t("Submitted") : t("Started")}
                      {" • "}
                      {attempt.score_total ? `${getAttemptPercent(attempt).toFixed(0)}%` : t("No grade yet")}
                    </div>
                  </div>
                ))
              ) : (
                <div className="rounded-2xl border border-dashed border-[var(--border)] bg-[var(--background)] px-4 py-5 text-[13px] text-[var(--muted-foreground)]">
                  {t("No saved practice attempts yet.")}
                </div>
              )}
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}
