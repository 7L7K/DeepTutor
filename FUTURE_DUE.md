# Future Due

## Future Due

- [ ] Revisit the superseded question-agent, solve-agent, EnvStore, MemoryService, and text-quiz parser experiments
  - Captured: 2026-08-11 America/Detroit
  - Status: deferred; orphan tests removed from canonical active suite
  - Area: advanced tools, assessment generation, credential settings, memory, future architecture
  - Source context: Canonical-main consistency pass after the TEEECHR/UI-1 consolidation. The checkpoint contained tests from older or unfinished architectures whose implementation counterparts are not present in the current product tree.
  - Deferred files: `tests/agents/question/test_coordinator.py`, `tests/agents/question/test_generator.py`, `tests/agents/question/test_model_routing.py`, `tests/agents/question/test_quiz_submission_agent.py`, `tests/agents/question/test_structured_responses.py`, `tests/agents/solve/test_tool_runtime.py`, `tests/agents/solve/utils/test_json_utils.py`, `tests/services/config/test_env_store_send_dimensions.py`, `tests/services/memory/test_memory_service.py`, `web/tests/quiz-types.test.ts`, `web/components/practice/FlashcardsWorkspace.tsx`, and `web/components/math-animator/MathAnimatorConfigPanel.tsx`.
  - Decision: Do not restore removed subsystems merely to satisfy these tests. Their prior source/test state remains recoverable in checkpoint commit `beacb3fc`; any future implementation must be intentionally scoped, reconnected to current APIs, and tested as a new lane.
  - Current proof: The removed tests no longer participate in the active canonical gates. The current memory, provider-settings, question, and Course quiz contracts remain represented by their current source and focused tests.
  - Next smallest step: If one of these advanced features is intentionally restarted, begin with a new contract and implementation inventory rather than reactivating the stale tests.

- [ ] Revisit the superseded native parallel-tool chat experiment
  - Captured: 2026-08-11 America/Detroit
  - Status: deferred; orphan test removed from canonical active suite
  - Area: advanced chat tooling and agentic orchestration
  - Source context: `tests/agents/chat/test_agentic_parallel_tools.py` targeted private pipeline methods (`_run_native_tool_loop`, `_should_use_simple_chat_reply`, and `_build_messages`) that no longer exist on the current `AgenticChatPipeline`. Current chat coverage follows the replacement loop/message/dispatch contracts.
  - Decision: Do not restore the removed private-method contract merely to satisfy this stale test. Re-open only as a new feature with an explicit current pipeline contract and bounded tool-loop tests.
  - Current proof: The orphan file was removed from the canonical active suite; current chat tests remain in `tests/agents/chat/test_agent_loop.py`, `test_message_build.py`, and the adjacent current-contract files.
  - Next smallest step: If parallel native tool calls become a supported product contract again, define the public loop behavior first and add tests against the current pipeline entrypoints.

- [ ] Add learner reminders to revisit unfinished Course work and quiz from it later
  - Captured: 2026-08-11 America/Detroit
  - Status: parked
  - Area: product, UI, persistence, notifications, Course learning loop
  - Source context: TEEECHR read-only product census and Course-learning UX exploration. The learner should be able to work on something, mark or ask the app to revisit it later, and receive a reminder such as “Quiz me later on what I started.”
  - Request: Let a learner defer a learning task while working in a Course—such as a Chat topic, material, Practice set, or unfinished concept—and have the app remind them later to return and quiz them on the same context.
  - Analysis: This should preserve the learner’s Course identity, academic term, source/material context, objective or topic, and unfinished-work state rather than creating an unrelated generic quiz. The reminder should be an explicit learner action with a due time or snooze choice, and it should resume the original Course context through a clear action. The design needs to distinguish “remind me to continue,” “quiz me later,” and “done/dismissed,” while avoiding provider work or quiz generation before the due action unless the existing learning contract explicitly allows it. It likely touches Course Chat/Practice entry points, persisted learning-task or reminder data, notification/in-app reminder UI, and authorization so reminders remain private to the owning learner and Course.
  - Current proof: Not proven yet. This is a captured product idea only; no route, schema, reminder service, notification delivery, or resume flow has been implemented or validated.
  - Acceptance: A learner can create a reminder from unfinished Course work without losing Course/term/source context; the reminder persists across refresh and session reopen; the due reminder appears in the app with the original context; “Quiz me” resumes the correct Course and starts or opens the intended bounded quiz flow; snooze, dismiss, completion, and duplicate-reminder behavior are explicit; cross-user access is denied; no unrelated generic Course or duplicate quiz is created; focused UI/API/tests cover create, due, resume, snooze, dismiss, and authorization states.
  - Next smallest step: Inspect the current Course Chat and Practice persistence seams—`web/components/courses/CourseChatRoute.tsx`, `web/components/practice/PracticeWorkspace.tsx`, the Course/session/practice API helpers, and any existing notification or scheduled-task infrastructure—then decide whether this should be a reminder record, a resumable learning task, or both.

- [ ] Re-prove TEEECHR branding in a supported browser runtime
  - Captured: 2026-08-11 13:21 EDT
  - Status: parked
  - Area: UI, branding, runtime, browser verification, docs
  - Source context: Product-brand migration in `/Users/home/Desktop/2k26/teeech/DeepTutor`, covering current web UI, metadata, localized copy, accessibility labels, settings, access gates, status copy, and the Co-Writer sample.
  - Request: When this work comes back, verify that no current learner-facing surface displays `DeepTutor`; `TEEECHR` must be the only public product name while technical and historical `DeepTutor` identifiers remain unchanged.
  - Analysis: Source and localization checks now replace the public brand while preserving repository/package/import names, API routes, environment variables, storage keys, CLI commands, migration identifiers, historical receipts, test fixtures, and GitHub repository URLs. Browser proof was deferred because the local dev guard rejected Node `26.5.0` with `Unsupported Node.js 26.5.0. Use Node.js 22 LTS (see web/.nvmrc); supported majors are 22 and 24.` The affected review set is login, register, Classes, Course Hub, Materials, Course Chat, Practice, Review/Flashcards, Learning Space, Settings, signed-out direct routes, browser tab title, mobile drawer, and footer/profile areas.
  - Current proof: `git diff --check` and `npm run i18n:check` passed. Source audit found no unclassified exact `DeepTutor` public UI text. `npm run test:node`, `npm run lint`, `npx tsc --noEmit`, `npm run build`, and browser verification remain blocked by existing dirty-checkout/type/dependency/Node-runtime issues.
  - Acceptance: Run the app under Node 22 or 24, inspect the listed desktop and mobile surfaces plus signed-out routes, confirm the browser title and rendered text contain `TEEECHR` and no unmarked `DeepTutor`, and attach a dated browser receipt. Confirm remaining matches are classified as technical identifiers, historical provenance, or test fixtures.
  - Next smallest step: Select an installed Node 22/24 runtime, start the web app from `/Users/home/Desktop/2k26/teeech/DeepTutor/web`, then perform the focused signed-out route and responsive browser pass before considering any further brand edits.
