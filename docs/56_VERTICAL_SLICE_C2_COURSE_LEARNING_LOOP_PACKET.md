# Vertical Slice C2 — Course Learning Loop Packet

## Status and boundary

C2 starts from the published C1 head and proves one bounded learner loop inside
one owner-private Course:

```text
Course Chat supported answer
  -> Practice this concept
  -> persistent Course Practice
  -> immutable ready revision
  -> owner/Course-bound Attempt
  -> autosaved answers and resume
  -> deterministic grading
  -> Results and missed-answer explanation
  -> provenance-bound targeted Review proposal
  -> learner approval
  -> same Course Review
  -> return to Course
```

This is a local authenticated slice. Hosted provider, physical device,
TestFlight, production secrets, and release operations remain outside this
packet. BlueWay B2 and TEEECHR C1 are frozen inputs; no BlueWay checkout or C1
worktree is in scope.

## Repository identity and baseline

- Worktree: `/Users/home/Desktop/2k26/teeech/DeepTutor-course-learning-loop-c2`
- Branch: `feature/teeechr-course-learning-loop-c2`
- Base: `d9faa6446490ccc228547219358752ebc3529340`
- Base provenance: published `fork/feature/teeechr-course-chat-c1`
- Runtime: Node `v22.23.2`, npm `10.9.8`, Python `3.11.15`
- Python environment: `/Users/home/.codex/runtimes/teeechr-b1-python311`

Unchanged C1 baseline on this worktree:

```text
backend: 3885 passed, 8 skipped, 10 warnings
web test: 430 passed, 0 failed
lint: 0 errors, 241 warnings
typecheck: passed
production build: passed
```

The pytest warnings are temporary-directory cleanup warnings from the existing
suite. The lint warnings are the accepted C1 backlog. The fresh worktree's
ignored `data/user/settings/main.yaml`, `data/user/settings/agents.yaml`, and
`web/node_modules` are local setup artifacts and are never staged.

## Current-system audit

### Existing source of truth

| Surface | Current authoritative implementation | C2 disposition |
| --- | --- | --- |
| Course ownership and source readiness | `deeptutor/courses/repository.py`, `deeptutor/courses/service.py`, `deeptutor/courses/chat_contract.py`, `deeptutor/api/routers/courses.py` | REUSE |
| Course Chat session/turn/citation identity | `web/app/(workspace)/classes/[courseId]/chat/page.tsx`, `web/app/(workspace)/classes/[courseId]/chat/[sessionId]/page.tsx`, `web/components/courses/CourseChatRoute.tsx`, `deeptutor/courses/chat_contract.py`, `deeptutor/services/session/sqlite_store.py` | EXTEND only at the handoff eligibility seam |
| Practice set and immutable revision | `deeptutor/courses/practice_models.py`, `practice_repository.py`, `practice_service.py`; `POST/GET /api/v1/courses/{course_id}/practice` and revision routes | REUSE |
| Generated Practice | `deeptutor/courses/generation_models.py`, `generation_repository.py`, `generation_service.py`, `generation_provider.py`; `/practice-generation` and `/practice-generation/plans` routes | EXTEND origin/turn provenance; keep existing provider and immutable revision fence |
| Attempt and autosave | `deeptutor/courses/attempt_models.py`, `attempt_repository.py`, `attempt_service.py`; attempt start/read/patch/submit routes | REUSE |
| Deterministic grading | `deeptutor/courses/grading_models.py`, `grading_repository.py`, `grading_service.py`; `exact-v1` grading evidence | REUSE |
| Results | `GET /api/v1/courses/{course_id}/practice/{practice_set_id}/attempts/{attempt_id}/results`, `PracticeWorkspace.tsx`, `practice-api.ts` | EXTEND presentation and Course route wrapper |
| Missed-answer remediation | `CourseGradingService.remediation_scope`, `POST .../attempts/{attempt_id}/flashcard-brief` | EXTEND to retain question/evidence provenance and expose a Review proposal |
| Review candidate approval | `flashcard_generation_models.py`, `flashcard_generation_repository.py`, `flashcard_generation_service.py`; `awaiting_review` candidates and publish route | REUSE/WRAP |
| Course Review UI | `web/components/flashcards/FlashcardsWorkspace.tsx`, `web/lib/flashcards-api.ts`, generic `/flashcards` route | WRAP with Course identity; no second Review engine |
| Course navigation | `web/components/courses/CourseOverview.tsx` | EXTEND destinations to Course-stable Practice and Review routes |
| General Study | `/practice`, `/flashcards`, `workspace_kind=general_study` paths | PARK/REGRESSION ONLY; no contamination |

### Current route and API map

Current browser routes:

```text
/classes
/classes/{courseId}
/classes/{courseId}/chat
/classes/{courseId}/chat/{sessionId}
/classes/{courseId}/materials
/practice
/flashcards
```

Current Course APIs used by the authoritative systems:

```text
GET    /api/v1/courses/{courseId}
POST   /api/v1/courses/{courseId}/learner-actions
POST   /api/v1/courses/{courseId}/practice
GET    /api/v1/courses/{courseId}/practice
GET    /api/v1/courses/{courseId}/practice/{practiceSetId}
POST   /api/v1/courses/{courseId}/practice-generation/plans
PATCH  /api/v1/courses/{courseId}/practice-generation/plans/{planId}
POST   /api/v1/courses/{courseId}/practice-generation/plans/{planId}/confirm
GET    /api/v1/courses/{courseId}/practice-generation/{operationId}
GET    /api/v1/courses/{courseId}/practice/{practiceSetId}/revisions/{revisionId}/questions
POST   /api/v1/courses/{courseId}/practice/{practiceSetId}/attempts
GET    /api/v1/courses/{courseId}/practice/{practiceSetId}/attempts/{attemptId}
PATCH  /api/v1/courses/{courseId}/practice/{practiceSetId}/attempts/{attemptId}
POST   /api/v1/courses/{courseId}/practice/{practiceSetId}/attempts/{attemptId}/submit
POST   /api/v1/courses/{courseId}/practice/{practiceSetId}/attempts/{attemptId}/grade
GET    /api/v1/courses/{courseId}/practice/{practiceSetId}/attempts/{attemptId}/results
POST   /api/v1/courses/{courseId}/practice/{practiceSetId}/attempts/{attemptId}/flashcard-brief
GET    /api/v1/courses/{courseId}/flashcards
GET    /api/v1/courses/{courseId}/flashcards/{deckId}
POST   /api/v1/courses/{courseId}/flashcard-generation
GET    /api/v1/courses/{courseId}/flashcard-generation/{operationId}
POST   /api/v1/courses/{courseId}/flashcard-generation/{operationId}/publish
GET    /api/v1/courses/{courseId}/flashcards/{deckId}/reviews
POST   /api/v1/courses/{courseId}/flashcards/{deckId}/reviews
```

C2 may add Course-stable browser wrappers and a narrow server-owned handoff
receipt. It must not replace these services or invent a Chat-local quiz.

### Existing schema and persistence

The current migration chain already provides the required Practice and Attempt
authority:

```text
0001_practice_authoring.sql
  practice_sets, practice_set_revisions, practice_questions
0002_quiz_attempts.sql
  quiz_attempts, quiz_attempt_items, quiz_attempt_answers
0003_grading_evidence.sql
  grading_evidence and exactly-once learning-effect receipts
0004_practice_generation.sql
  practice_generation_operations and immutable generated revisions
0005_flashcards.sql
  flashcard_decks, flashcards, flashcard review state/history
0007_assessment_resource_governance.sql
  bounded Practice/Review resource governance
0008_provider_flashcard_review.sql
  provider-backed candidate review and publish fences
0011_practice_generation_plans.sql
  editable generation plans and course_chat origin binding
```

The existing `practice_generation_plans.origin_json` and
`flashcard_generation_operations.origin_json` are the current provenance
extension points. C2 must preserve source ID, revision, content hash, source
title snapshot where available, the exact Course Chat session/message binding,
Practice revision, Attempt, missed question IDs, and grading-evidence IDs. A
new migration is not justified by the audit unless tests prove the existing
JSON provenance shape cannot safely hold those bounded fields.

## Handoff contract

The browser may send only:

```json
{
  "course_id": "server path parameter",
  "session_id": "opaque persisted Course Chat session",
  "assistant_message_id": 41,
  "idempotency_key": "opaque request key",
  "expected_course_revision": 3,
  "expected_course_write_epoch": 2
}
```

The server derives and validates:

```text
authenticated owner
  + active exact Course
  + Course Chat session.course_id
  + assistant message role and persisted completion
  + supported Course grounding, not abstention/failure
  + at least one validated citation anchor
  + citation source IDs/revisions/hashes/title snapshots
        -> persistent idempotent Practice intent/plan
        -> existing Practice generation and immutable ready revision
```

The server ignores or rejects browser-supplied owner IDs, source IDs, answer
keys, provider settings, retrieval fragments, prompts, free-form concept text,
or a foreign Course/session/message reference. A foreign, deleted, archived,
unsupported, processing-only, or provider-failed turn returns a bounded
not-found/unavailable result without creating a Practice set, generation plan,
revision, Attempt, or Review proposal.

Idempotency identity is:

```text
authenticated owner + exact Course + assistant message ID + c2 practice-purpose version
```

Repeated handoff requests return or resume the same valid Practice plan/intent.
They do not create duplicate plans, generated revisions, or Review proposals.
After completion, a learner may explicitly start a new Attempt; that is distinct
from silently creating another Practice revision.

## Learner flow and UI boundary

The bounded browser flow is:

```text
/classes/{courseId}/chat/{sessionId}
  supported Biology answer with validated Course citations
  -> Practice this concept
/classes/{courseId}/practice
  -> same Course, five-question ready revision
  -> start or resume Attempt
  -> one question at a time, autosave and visible save state
  -> refresh midway and resume exact Attempt/revision
  -> submit, deterministic grade
/classes/{courseId}/practice/{practiceSetId}/attempts/{attemptId}
  -> Results, score, correct/missed answers, authorized explanations
  -> Review 2 missed concepts
/classes/{courseId}/review
  -> candidate Review proposal, learner approval
  -> Course Review items visible
/classes/{courseId}
  -> Course identity preserved
```

The Practice action is visible only for a persisted completed Course answer
with at least one validated citation. It is hidden for unsupported abstention,
provider failure, zero-ready/processing-only state, unauthorized resources,
archived Course, and Course/session mismatch. Chat reading is not learning
evidence; only Attempt answers and committed grading evidence count.

## Failure and safety contracts

| Failure | Required C2 behavior |
| --- | --- |
| Grounded turn missing/deleted | Bounded unavailable handoff; no Practice resource |
| Unsupported or provider-failed turn | No Practice action and no server-side resource |
| Foreign Course/session/message | Same bounded not-found behavior; no existence leak |
| Citation archived after Chat | Keep immutable snapshot only when authorized; otherwise stop safely |
| Practice generation fails | Preserve one intent/plan, show retry, publish no empty revision |
| No valid questions | No ready revision and no Attempt |
| Attempt save fails | Keep local answer, show unsynced state, do not claim saved |
| Duplicate answer or submit | Return original durable receipt/result |
| Grading explanation mismatch | Preserve deterministic score; explanation cannot rewrite grade |
| Bad question report | Persist report separately; do not convert it into learning evidence |
| Review generation fails | Results remain available; retry proposal safely |
| Review approval repeats | Return the original approved operation/deck; no duplicate deck |
| Biology/Psychology mismatch | Course, source, Attempt, and Review ownership fail closed |

## Audit-based implementation order

1. Add focused failing tests for supported-turn eligibility, citation/source
   revalidation, handoff idempotency, Practice provenance, foreign/mismatch
   denial, Attempt resume/duplicate submission, Results authorization, and
   Review proposal provenance.
2. Extend the existing learner-action resolver to require a persisted
   citation-bearing supported Course turn and produce one idempotent
   Course-Chat Practice intent. Keep current `course_chat` origin and source
   receipt fences.
3. Extend Practice generation/remediation provenance with bounded missed
   question and grading-evidence identity. Do not persist raw Chat/source text.
4. Wrap the existing Practice, Attempt, Results, and candidate-review systems
   in Course-stable routes and navigation. Preserve the existing API services.
5. Add the narrow Results-to-Review proposal/approval presentation. Use the
   current `awaiting_review` candidate gate; never auto-publish a deck.
6. Add deterministic fixture and authenticated browser proof only after the
   server contracts are green.

## Required tests and runtime proof

Backend focused suites:

```text
tests/courses/test_course_chat_c1_contract.py
tests/courses/practice/test_api.py
tests/courses/practice/test_attempt_contract.py
tests/courses/practice/test_grading_contract.py
tests/courses/practice/test_generation_contract.py
tests/courses/practice/test_flashcard_generation_contract.py
tests/courses/test_learner_actions.py
```

New C2 coverage must include:

- supported citation-bearing Biology turn exposes the handoff;
- unsupported, provider-failed, zero-ready, processing-only, and failed-only
  turns do not;
- foreign Course/turn and Biology/Psychology mismatches fail closed;
- client-supplied source/owner/answer authority is ignored or rejected;
- repeated handoff is idempotent;
- Practice plan/revision preserves Course Chat and frozen source provenance;
- ready revision is immutable and no empty revision is published;
- Attempt is owner/Course/revision-bound, autosaves, resumes, and survives
  duplicate submit;
- deterministic score and grading evidence remain stable;
- Results expose only authorized Course sources and preserve refresh/direct-link;
- missed questions create a provenance-bound proposal, not auto-published cards;
- proposal approval is duplicate-safe and Biology items cannot enter Psychology;
- General Study and all C1 authorization/citation/readiness tests remain green.

Web/runtime fixture:

```text
User A
└── Biology 101
    ├── one supported grounded Chat turn
    ├── five-question deterministic Practice
    ├── two deliberate misses
    └── two approved targeted Review items

User B
└── separate private Course
```

The final browser campaign must capture desktop and 390×844 views for the Chat
handoff, Practice, autosave, midway refresh/resume, Results, miss detail,
Review proposal, approved Review, Course return, cross-user denial,
Course/session/Attempt mismatch, and keyboard/focus order. The receipt must
also retain runtime versions, exact fixture IDs, routes, backend/web outputs,
screenshots, and checksums.

## Non-goals and stop conditions

C2 does not build or modify:

- BlueWay or the B2 launch;
- the C1 Chat engine or citation model beyond the handoff seam;
- syllabus parsing or Course timeline intelligence;
- Progress percentages, mastery redesign, recommendations, or ranking;
- Study Sessions or advanced spaced repetition;
- instructor/authoring workflows;
- temporary quizzes or flashcards trapped inside Chat;
- automatic publishing of large decks;
- hosted deployment, production secrets, physical-device proof, or release
  operations.

Stop immediately if a foreign source/citation/Attempt/Review can cross the
Course boundary, a provider is called with no supported citation-bearing turn,
a Chat turn is treated as learning evidence, an unsupported answer opens the
handoff, a duplicate click creates a second authority resource, or C1
authorization/source isolation regresses.

## Commit and publication plan

```text
test(c2): lock Chat-to-Practice learning-loop contracts
feat(practice): create Course Practice from grounded Chat turns
feat(results): connect grading Results to targeted remediation
feat(review): create provenance-bound Review proposals from misses
feat(web): complete the Course learning loop
docs(c2): archive Course learning-loop runtime proof
```

Push only:

```text
fork/feature/teeechr-course-learning-loop-c2
```

Do not push `origin`, merge into integration, or modify any adjacent checkout.
