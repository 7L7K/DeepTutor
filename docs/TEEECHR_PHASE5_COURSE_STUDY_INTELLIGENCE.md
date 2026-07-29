# TEEECHR Phase 5 — Course Study Intelligence

Status: provider-free single-host engineering boundary complete

Authority: `/Users/home/Desktop/2k26/teeech/DeepTutor-v1.5.2-baseline`

Starting point: Phase 4 closeout commit `43e388d17d154ab0c2e0eaa3c2465584c2e88f2d`
Implementation branch: `feature/teeechr-v152-phase5-course-study-intelligence`

## Goal

Turn private Course evidence and learner intent into confirmed, grounded,
cited, reviewable Flashcards.

The first useful Phase 5 flow is:

```text
select Course
  -> describe the study goal
  -> review count, difficulty, card mix, objectives, and sources
  -> confirm provider use
  -> generate bounded candidates
  -> validate every candidate against the frozen source snapshot
  -> include/exclude and reorder
  -> publish an immutable generated deck
  -> study through the existing durable review schedule
```

Phase 5 reuses the Phase 4 Course, source, Flashcard, review, idempotency,
restart, archive, and owner-isolation primitives. It does not restore the
historical tester-cookie, KB-name, or shared-storage architecture.

## Authority contract

- Conversation supplies learner intent. It is never factual authority.
- Ready, current, owned Course sources supply factual authority.
- Learning and graded Practice evidence may suggest remediation focus.
- The authenticated server context supplies the immutable owner and Course.
- The server resolves permitted source and objective identifiers.
- The provider cannot select an owner, Course, Knowledge Base, filesystem
  path, provider credential, tool, or publication state.
- Missing and foreign Course, source, session, message, Practice attempt,
  deck, operation, and candidate identifiers return the same not-found shape.
- A generated card is not active learning material until the learner publishes
  it from an `awaiting_review` operation.

## Locked product decisions

- Private Course ownership remains the only access model.
- Manual Flashcards remain available without any provider.
- Ungrounded AI-generated decks remain disabled.
- Every paid generation requires a visible learner confirmation.
- Generated factual cards are immutable after publication.
- Candidate review initially supports include/exclude and reorder, not factual
  rewriting.
- A learner-edited generated card is a future manual successor with explicit
  provenance, not an in-place mutation.
- Candidate previews archive after seven days; no hard-delete path exists.
- A usable result requires at least three valid candidates and at least 60
  percent of the requested count.
- Initial cards support definition, concept, comparison, application, process,
  and recall types plus an optional hint.
- Initial provider qualification targets GPT-5 Mini through the Responses API;
  an exact snapshot is pinned only after the evaluation campaign.
- Provider requests use strict structured output, `store=false`, no web search,
  no tools, and no arbitrary URL retrieval.
- No automatic paid retry occurs after an uncertain provider response.
- The single-host beta permits one paid operation per user and two globally.
- Real-provider closeout proof requires separate approval and a maximum total
  budget of two US dollars.

## Non-goals

- Course sharing, collaboration, or instructor-assigned decks.
- Cross-Course decks.
- Automatic generation from every BlueWay transcript.
- BlueWay write-back or raw lecture-audio access.
- Web-assisted generation.
- Adaptive provider routing.
- Multi-server budget coordination.
- Historical learner-data import.
- Upstream DeepTutor reconciliation.
- Push, merge, deployment, or production release.

## Generation brief

Every entry point resolves to one server-validated brief:

```text
GenerationBrief
  focus
  desired_count
  card_type_mix
  difficulty
  objective_ids
  source_ids
  answer_length
  include_hints
  conversation_origin?
  remediation_context?
```

Workspace input, the existing Chat `Make flashcards` action, and Practice
remediation all use this contract. Chat and Practice do not receive separate
provider or persistence authority. A natural-language Chat tool is deferred;
ordinary conversation cannot silently allocate work or invoke a paid provider.

## Durable lifecycle

```text
queued -> running -> awaiting_review -> completed
                  \-> failed

queued -> cancelled
running -> cancelling -> cancelled
awaiting_review -> cancelled
```

Terminal operations cannot reactivate. Provider output is normalized and
validated before `awaiting_review`. Publication inserts only selected
candidates, creates review schedules, readies the deck, and completes the
operation in one transaction.

Cancellation before durable provider admission makes zero provider calls.
Cancellation after admission cannot promise that provider cost stops; it enters
`cancelling`, and the result is discarded and cannot publish.
Awaiting-review cancellation archives the draft. Course archive first
reconciles expired review drafts, then remains blocked while queued, running,
cancelling, or non-expired awaiting-review work exists.

## Persistence contract

Migration `0008_provider_flashcard_review.sql` adds the candidate-review
lifecycle. Additive migration `0009_provider_invocation_admission.sql`
preserves the already-replayed `0008` checksum while adding the exact provider
admission boundary. Together they extend
`flashcard_generation_operations` with:

```text
generation_brief_json
origin_json
candidate_output_json?
candidate_revision
provider_receipt_json?
provider_invoked_at?
cancel_requested_at?
review_expires_at?
```

The operation state and error constraints add:

```text
states:
  awaiting_review
  cancelling
  cancelled

errors:
  configuration_error
  quota_exceeded
  insufficient_valid_cards
  cancelled
```

Flashcards add:

```text
hint
card_type
```

Database triggers enforce immutable owner, Course, target deck, source
snapshot, brief, origin, idempotency, and allocation authority; monotonic
candidate revisions and cancellation; legal transitions; one-way receipts;
terminal immutability; atomic publication; and no deletion.

Normalized candidates may persist. Raw prompts, provider responses, full
source excerpts, transcript dumps, keys, authorization headers, and provider
diagnostics do not.

## API contract

```text
POST /api/v1/courses/{course_id}/flashcard-generation/brief
POST /api/v1/courses/{course_id}/flashcard-generation
GET  /api/v1/courses/{course_id}/flashcard-generation
GET  /api/v1/courses/{course_id}/flashcard-generation/{operation_id}
POST /api/v1/courses/{course_id}/flashcard-generation/{operation_id}/publish
POST /api/v1/courses/{course_id}/flashcard-generation/{operation_id}/cancel
```

The brief endpoint performs no provider call. It returns a normalized brief,
resolved source receipts, objective identifiers, origin receipt, warnings, and
provider availability without returning source text.

Generation requires the final brief, origin receipt, idempotency key, and
expected Course revision/write epoch. The server re-resolves every authority
field.

Publication requires selected candidate IDs, their order, expected candidate
revision, and current Course/deck optimistic authority.

## Provider credential contract

Raw provider keys do not belong in `model_catalog.json` or browser responses.

The model catalog persists an opaque `credential_ref` and a configured status.
A server-only provider credential authority stores the secret in a private
directory/file with current-OS ownership, `0700`/`0600` permissions,
single-link regular-file shape, no symlink following, atomic replacement, and
post-write verification.

Internal runtime catalog loads may resolve a credential reference to an
ephemeral `api_key`. Public Settings payloads return only redacted configured
status. Logs, errors, test artifacts, provider receipts, and API responses
never contain secret values.

## Pre-invocation authority fence

Immediately before every provider call, one transactional preflight verifies:

1. The current account exists and remains active.
2. The operation belongs to the immutable authenticated owner.
3. The Course belongs to that owner and remains active.
4. Course revision/write epoch still match.
5. The generated draft deck and target epoch still match.
6. The exact source IDs, revisions, fingerprints, and ready states match.
7. The operation is not cancelled, superseded, or terminal.
8. Provider configuration is enabled and its credential is usable.
9. Per-user and global concurrency are available.
10. Per-user and global provider budgets allow the call.

The same Course/source/target checks run independently before candidate
persistence and publication. Archive, source replacement, cancellation, or
account revocation before invocation results in zero provider calls.

## Cost governance

Paid-provider accounting is administrative metadata, separate from every
personal Course database. It stores:

```text
operation_id
owner_user_id
provider
requested_model
reserved_input_tokens
reserved_output_tokens
settled_input_tokens?
settled_output_tokens?
estimated_cost?
pricing_version
state
timestamps
```

It stores no prompt, source, transcript, card, or learner response.

The single-host ledger provides a global kill switch, daily user/global
limits, conservative full-request reservation, bounded settlement,
deterministic pre-call release, conservative uncertain-outcome accounting, and
concurrency admission. Reservations left by a killed process become uncertain
after a five-minute lease and stop holding concurrency while remaining charged
against that day's limits.

## Provider request

The provider receives:

1. Versioned system rules.
2. The normalized generation brief.
3. Optional bounded conversation intent.
4. Course objective labels.
5. Bounded excerpts labeled with temporary source keys.
6. A strict output schema.

Source text is explicitly untrusted evidence. Instructions embedded in a
document or transcript cannot select tools, owners, providers, or sources.

The safe provider receipt records provider, requested and actual model, prompt
version, response/request ID, token counts, latency, requested/returned/valid
counts, `store=false`, and timestamps. The published count is derived from the
immutable selected cards rather than copied from provider output.

## Deterministic validation

Before candidate persistence:

- Strict schema rejects unknown properties.
- Prompt, answer, hint, locator, and total-output sizes are bounded.
- Card type and objective IDs use allowed values.
- Each card has one to three citations.
- Every temporary source key maps to the frozen operation snapshot.
- Evidence text is a normalized substring of supplied source material.
- Duplicate prompts and obvious answer leakage are rejected.
- Empty or meaningless answers are rejected.
- At least three candidates and 60 percent of the requested count survive.

Rejected candidates never become active cards. A failed threshold produces
`insufficient_valid_cards`.

## Learner surfaces

### Flashcards workspace

The learner chooses focus, count, difficulty, card mix, objectives, sources,
answer length, and hints; confirms provider use; monitors durable status;
reviews citations; includes/excludes and reorders candidates; then publishes.

### Course Chat

The existing `Make flashcards` action becomes a non-mutating proposal that can
suggest focus/count/difficulty/mix but cannot choose owner, Course, provider,
arbitrary source authority, make a paid call, or publish. Natural-language
tool selection remains deferred so that ordinary Chat text cannot bypass the
visible confirmation flow.

### Practice remediation

An owned graded attempt may propose missed or weak objective IDs. Learner
answers and grading output do not become factual authority; Course sources
remain required.

## Verification

### Provider-free gates

- Secret migration, redaction, permissions, symlink, hard-link, and log scans.
- Counting fake provider proves zero calls after account disablement, Course
  archive, source replacement, target change, cancellation, provider disable,
  and quota denial.
- Fresh migration replay and Phase 4 upgrade replay.
- Direct-SQL trigger bypass attempts.
- Restart in queued, running, awaiting-review, cancelling, and terminal states.
- Idempotent replay and concurrent admission.
- Alice/Bob Course, operation, candidate, deck, session, and attempt isolation.
- Logout/login cache isolation.
- Prompt-injection Course material remains inert.
- Browser flow covers brief, confirmation, progress, refresh, preview,
  publication, review, restart, and provider-unavailable manual fallback.

### Provider-free structural quality campaign

Use fixed Biology, Calculus, History, Psychology, and Computer Science packets,
including transcript-style and malicious-instruction variants.

Provider-free gates:

- Schema validity: 100 percent.
- Citation resolution: 100 percent.
- Prompt-injection authority resistance: 100 percent.
- Answer leakage: zero.
- Duplicate prompts: at most 5 percent.
- Deterministic packet answers and citations remain bound to the selected
  frozen Course source receipts.

Human-reviewed answer support is a real-provider qualification gate, not a
claim made from deterministic fakes.

### Real-provider gate

After all provider-free proof and separate approval: at most three decks,
eight cards each, two-dollar total budget, no automatic retry, no deployment.

## Execution order

```text
P5-00 contract docs
  -> P5-01 secure credential authority
  -> P5-02 pre-invocation fence
  -> P5-03 cost governance
  -> P5-04 candidate lifecycle
  -> P5-05 provider adapter
  -> P5-06 deterministic evidence validation
  -> P5-07 Flashcards workspace
  -> P5-08 Chat proposals
  -> P5-09 Practice remediation
  -> P5-10 provider-free proof
  -> P5-11 separately approved real-provider proof
  -> P5-12 closeout
```

## Exit

Phase 5 is engineering-complete when the provider-free implementation and
full proof campaign pass on the exact final tree; documentation and changelog
match that tree; every tracked and untracked path is reviewed; the repository
closeout backcheck passes; and reviewed local commits exist.

Real-provider quality, push, merge, deployment, production release, historical
data migration, BlueWay expansion, and upstream reconciliation remain separate
claims and approval gates.

## 2026-07-29 closeout receipt

The final reviewed source tree has:

- 469 affected Course, BlueWay, multi-user, Settings, catalog, credential, and
  provider-usage Python tests passing with seven warnings.
- 195 web node tests passing.
- TypeScript passing.
- ESLint completing with zero errors and 147 warnings.
- The 54-route Next production build passing.
- Ruff, shell syntax, diff-integrity, and changed-line secret scans passing.
- Both the root and CLI wheels built offline with the installed toolchain, with
  each wheel inspected to contain all ten Course migration files.
- Migration `0008` preserved at SHA-256
  `aaf67b7b29b960d05b63897c76832838fffb454a3bbf1651d0505bd3fe3ddfe8`;
  the post-replay provider-admission repair is isolated in additive migration
  `0009`.
- Independent Terra review finding no remaining P0 or P1 issue after repair of
  reservation overflow, cancellation admission, stale reservation,
  card-type, expired-review archive, and cancellation-status defects.

The normal isolated wheel-content pytest remains environment-blocked because
its build subprocess requires unavailable PyPI build dependencies. The same
wheel contents passed the explicit offline build-and-inspection proof without
changing the regression test.

The authenticated browser campaign passed on the reviewed tree outside the
restricted sandbox:

- Disposable Alice and Bob created same-titled private Courses without identity
  or browser-cache crossover.
- Course learning state and a five-question quiz survived actual backend
  process death and restart.
- Manual Practice and Flashcards remained usable with provider generation
  disabled.
- The explicit deterministic Phase 5 adapter staged grounded candidates behind
  learner review without contacting a model.
- A second backend restart preserved the awaiting-review operation, after which
  the learner excluded/reincluded a candidate, published the selected immutable
  deck, and entered the durable review flow.

All five Playwright tests passed. The `module.register()` deprecation message is
an upstream Node warning and did not affect the campaign.

No real or paid provider call, push, merge, deployment, hosted mutation,
BlueWay source change, historical import, or upstream integration occurred.
