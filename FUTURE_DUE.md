# Future Due

## Future Due

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
