## [Unreleased]

### Fixed
- web frontend: allow `127.0.0.1` as a Next dev origin so the in-app browser can load hydrated `/practice` and `/practice/flashcards` controls instead of rendering dead HTML.
- web frontend: pin Turbopack's workspace root to the repo `web` app so local page requests do not hang while Next scans an unrelated higher-level lockfile root.
- local runtime: start the Next frontend in webpack mode from the launcher because Turbopack was crashing on `/practice/flashcards` with `uncaughtException: write EPIPE`.
- llm: force the SDK-backed OpenAI executor path to honor GPT-5 temperature constraints so chat and diagnostics work with `gpt-5-mini`.
- chat: route plain greeting-only turns like `hi` and `hello` through a direct quick-reply path so they return a short normal answer instead of the full internal thinking / observing pipeline.
- chat ui: keep `New chat` on a real fresh draft instead of snapping back to the previous session URL, and stop completed plain-chat turns from rendering the full internal trace panel inline.
- chat ui: hide leaked internal-only memo replies from chat history hydration and live message rendering so older broken turns do not keep showing internal observation text to the learner.
- navigation: expose `Practice` and `Notebook` in the main sidebar so those existing learner-facing pages are reachable without typing routes manually.
- web chat: render quiz-like assistant replies as a clickable multiple-choice panel so learners can answer in the UI and submit one-line responses back to the thread.
- web chat: attach hidden quiz-submission grading context when the interactive quiz UI sends answers so the assistant scores the quiz instead of treating the answer line like a fresh chat prompt.
- web chat: route interactive quiz answer submissions through the quiz capability so grading uses the larger question-response budget instead of the shorter generic chat response cap.
- unified ws: reply to client heartbeat pings with `pong` so practice and chat streams do not fail with `Unknown type: ping` during long-running turns.
- tests: cover quiz text parsing variants, interactive submit routing to `deep_question`, and incomplete interactive quiz submissions that should request only missing question numbers.
- web frontend: replace effect-driven state hydration in app-shell subscriptions and settings tour spotlight measurement so the frontend lint suite no longer fails on synchronous effect updates, while visualization error labels stay translatable.

### Added
- practice mode: add a dedicated `/practice` workspace for generating quizzes, taking them with an optional soft timer, submitting without chat, and reviewing inline score/domain results.
- practice mode: persist quiz attempts, graded items, and domain progress summaries through new practice APIs so results and study trends survive beyond a single response.
- practice mode: add a first `/practice/flashcards` page slice so flashcards can be explored as a dedicated Practice workflow with setup, deck overview, and one-card study states before backend generation is wired.
- practice mode: add real `/practice/flashcards` deck generation, persistence, recent-deck loading, and per-card review/restart APIs so flashcards now save as structured study assets instead of a preview-only shell.
- practice mode: add flashcard session reviews, KB topic suggestions, and a dedicated completion state so finished decks now produce a saved coach-style write-up plus a clearer missed-cards remediation loop.
- web chat: add tutor action chips under coaching replies so learners can tap `Quiz me`, `Explain simpler`, `Make flashcards`, or `Review weak spots` without retyping follow-up prompts.

### Changed
- quiz grading: return structured quiz submission results alongside the learner-facing explanation so the UI can render reliable scorecards, wrong-answer review, and saved practice history.
- quiz grading: accept answer maps for interactive submissions and allow dedicated practice flows to score incomplete/timed-out attempts while chat-based quizzes still request missing answers.
- practice mode: gate flashcard `Knowledge` decks when no KBs are loaded, surface clearer source-trust badges, and tighten generated flashcard quality to reduce vague or duplicate cards.
