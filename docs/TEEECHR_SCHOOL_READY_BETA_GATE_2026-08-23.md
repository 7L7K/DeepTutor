# TEEECHR School-Ready Beta Gate — 2026-08-23

Status: `GO_LOCAL_QUALIFICATION / NO_GO_SCHOOL_SHARE`

Baseline branch: `codex/teeechr-school-ready-d1-20260823`
Baseline SHA: `69ced84369e84ef58dcd3f408bd8f59dcd67e3e5`
Base SHA: `171b78f15cc93c4090b64784a6e93f94be384ac8` (`fork/main`)
Baseline worktree: clean
Remote state: branch has no configured upstream
Hosted state: `NOT_VERIFIED_CURRENT`

## 1. Goal and non-goals

The one-week goal is a small, controlled, school-usable TEEECHR beta with a
truthful learner journey:

`Classes -> Course -> Materials -> Chat -> Practice -> Results -> Review`

Day 3 owns the current-SHA local qualification of that journey. It must prove
two-user ownership isolation, provider-off/manual fallbacks, and persistence
through a cold application restart in a disposable runtime.

Day 3 does not authorize:

- real student accounts or real student data;
- provider credentials, billable calls, or provider-budget changes;
- pushing, merging, deployment, DNS, VPS, or hosted-data changes;
- PocketBase enablement;
- an instructor-to-learner Course assignment feature;
- advanced learner features outside defects exposed by the school journey.

The current product is learner-driven: an administrator provisions an account
and may grant a shareable model, while each learner creates Courses in their
own private scope. There is no Course enrollment or assignment primitive.

## 2. Candidate source authority

The selected implementation checkout is:

`/Users/home/Desktop/2k26/teeech/DeepTutor-school-ready-d1`

The sibling `DeepTutor` checkout is not the selected implementation authority.
The immutable Day 3 completion receipt will record the exact committed
candidate SHA. This gate records the pre-change baseline until that receipt
exists. Every completion receipt must name one exact SHA and prove a clean
start and end state.

## 3. Historical evidence inheritance rules

A historical receipt may supply design precedent, known scenarios, or an
immutable artifact identity. It may not mark a current gate passed unless its
exact tested source is the candidate SHA or the behavior has been freshly
rerun on the candidate.

Any candidate change invalidates the affected source, test, browser, provider,
build, artifact, and hosted rows until those layers are rerun against the new
SHA.

The V157 certification, Phase 6 plan, C3/C4 receipts, and the August 12 hosted
receipt remain frozen historical evidence. Their status lines must not be
rewritten to imply current-source proof.

## 4. Current proof ledger

| Layer | Current status | Evidence boundary |
| --- | --- | --- |
| Source identity | PASS at baseline | Clean local branch at `69ced843`; not pushed or hosted |
| Learner/admin authority | PASS at baseline | Day 2 exact-SHA source, tests, build, and repeated local browser receipts |
| Core Course journey | READY FOR QUALIFICATION | P0/P1 learner repairs are implemented; fresh full browser journey is pending |
| Two-user ownership | READY FOR QUALIFICATION | Fresh repository reconstruction tests pass; browser matrix is pending |
| Cold restart | READY FOR QUALIFICATION | Hardened cold-process harness is implemented but not yet run |
| Provider-free fallback | READY FOR QUALIFICATION | Empty-Course manual Practice and draft recovery are implemented; browser proof is pending |
| Real Course AI | BLOCKED | No configured LLM or embedding profile; no provider call authorized |
| Automated Practice/cards | BLOCKED | Production adapter is OpenAI-only; no credential or budget authorized |
| Assigned Partner | CODE PASS / SCHOOL DISABLED | Delegated calls are caller-bound and local-only in source/tests; usage policy and any legacy cron-data gate remain before enablement |
| Backup/restore | BLOCKED | No current disposable restore rehearsal |
| Release/hosted/device | BLOCKED | No push, CI artifact, deployment, hosted identity, or student-device proof |

## 5. Go/no-go gate matrix

| Rank | Gate | Day 3 acceptance |
| ---: | --- | --- |
| 1 | Source identity | One clean committed candidate; exact digest before and after proof |
| 2 | Learner authority | Day 2 admin/learner route and API boundaries remain green |
| 3 | Core learner loop | Current nested Course routes complete the provider-free golden path |
| 4 | Ownership/persistence | Two learners stay isolated and committed state survives cold restart |
| 5 | Provider truth | Deterministic mode is labeled test-only; provider ledger stays at zero |
| 6 | Partner safety | Delegated learners cannot reach owner/global memory or owner-bound profiles |
| 7 | Runtime cleanup | Owned processes, ports, and disposable data are gone before success sentinel |

Failure of any row keeps `NO_GO_SCHOOL_SHARE`.

## 6. Day 3 learner golden path

The fresh local receipt must prove:

1. An administrator creates two disposable regular learners.
2. Each learner logs in and sees only learner-safe navigation.
3. In simultaneous browser contexts, both learners create same-titled private
   Courses and upload same-named, byte-distinct synthetic sources.
4. Each source moves through the shipped upload/processing/ready path and is
   bound to its expected content hash.
5. Non-ready Course Chat displays truthful grounding/readiness language while
   preserving the intended usable Chat surface.
6. A deterministic-local Course Chat turn is persisted with only the caller's
   source evidence.
7. With automated generation unavailable, a learner can create the first
   manual Practice set, add a question, mark it ready, start an attempt,
   autosave, reload, submit, grade, and view Results.
8. A learner can create or open manual Flashcards, review a card, and retain the
   state after reload.
9. Materials, Overview, Practice, Results, and Review remain readable at the
   current nested Course routes.
10. Every externally addressable foreign Course, source, Chat session,
    Practice set, attempt/result, deck, and card identifier fails with the same
    non-enumerating class as a random missing identifier. Flashcard review
    ownership and persistence are proven through the owner-scoped deck
    schedule's `last_review_id`; there is no review-ID lookup API to probe.
11. A controlled cold restart preserves completed state. Interrupted source
    work fails closed instead of becoming falsely ready or remaining forever
    in progress.
12. No unexpected privileged request, browser page error, console error,
    failed request, skipped test, retry, or mocked positive receipt is present.

The positive upload/readiness claim must use shipped UI/API paths. Direct
repository seeding or Playwright response fulfillment may not satisfy it.

## 7. Provider and budget sub-gate

The current checkout has zero configured LLM profiles and zero configured
embedding profiles. The Day 3 campaign therefore uses the explicit
`TEEECHR_TEST_DETERMINISTIC_PROVIDER` adapter only inside a disposable test
runtime. This proves wiring, access control, persistence, and presentation; it
does not prove model quality or a production provider.

The lowest-risk production candidate is a paired local Ollama LLM and embedding
profile for Course ingestion and Chat, with manual Practice and Flashcards.
Automatic Practice and Flashcard generation currently requires the dedicated
OpenAI adapter, a deployment-owned credential, and an enabled budget ledger.

No real provider call may be folded into the hermetic Day 3 sentinel. A later
real-provider receipt requires separate authorization, one allowlisted model,
one bounded operation, a hard cost ceiling, settled usage evidence, and no
secret or raw learner content in logs.

If Day 3 passes without that authorization, its provider conclusion is:

`LOCAL_CORE_PROVIDER_FREE_PASS / AI_SCHOOL_USE_NO_GO`

## 8. Persistence, backup, and rollback sub-gate

The supported school-beta persistence mode is local JSON plus per-user SQLite
and private Knowledge Base trees under one `DEEPTUTOR_HOME`. PocketBase remains
startup-rejected for private Courses and is not part of this gate.

Day 3 proves a fresh backend/frontend restart against one disposable home. A
later pre-student gate must additionally prove a consistent stopped-process
backup, whole-home restore, migration version, credential-envelope/key pairing,
and compatible rollback artifact.

## 9. Partner sub-gate

Assigned Partners are not enabled for a school beta until all of these hold:

- delegated learner calls retain caller provenance;
- delegated turns receive only the reviewed local learning-tool allowlist and
  fail closed for every current or future off-list tool;
- `partner_read`, `partner_memorize`, and `partner_search` are unavailable to
  delegated learners unless memory is safely partitioned by caller;
- effective primary, backup, and implicit-default models are deployment-owned
  and shareable, never owner-bound OAuth profiles;
- revocation denies the next action before manager, budget, or session mutation;
- the learner-facing path has an explicit usage-control policy.

Any deployment that ran a build capable of creating delegated Partner cron
jobs must quarantine, remove, or explicitly migrate provenance-free legacy
Partner jobs before enabling its scheduler. If that vulnerable build was never
deployed, a fresh or empty cron store is sufficient proof for this gate.

Admin-only Partner use may retain the existing owner memory behavior. If this
sub-gate is not fully qualified, Partners remain disabled/unassigned for the
school beta.

## 10. One-week execution order

### Day 3

- Repair only P0-P2 defects exposed by the learner journey.
- Harden the two assigned-Partner P0 boundaries.
- Produce one exact-SHA provider-free, two-user, cold-restart receipt.

### Day 4

- Rerun the complete local candidate matrix after repairs.
- Prove current desktop and narrow-mobile learner surfaces.
- If separately authorized, qualify one local or capped paid provider path.

### Day 5

- Prove backup, migration, restore, revocation, and account/grant operations.
- Decide explicitly whether Partner and BlueWay surfaces are enabled or kept
  off for the controlled beta.

### Day 6

- Only with explicit source-control authority: push the exact candidate, run CI,
  and build a digest-bound release artifact plus rollback reference.

### Day 7

- Only with explicit deployment authority: deploy the exact artifact, prove
  hosted HTTPS/auth/Course/provider/budget/restart behavior, then admit at most
  three to five controlled students for one supported study event.

## 11. Findings and proof invalidation rules

The Day 3 audit found these blocking defects and the candidate now carries
bounded repairs for each one:

- active Course Chat hides non-ready grounding truth;
- an empty provider-off Course cannot create its first manual Practice set;
- assigned learner Partner turns can reach privileged global/admin memory;
- assigned Partners can lend owner-bound model credentials;
- several P1 failure and context states can hide manual learner fallbacks.

Independent backcheck also found and closed broader delegated-Partner paths for
cron, host execution, deployment MCP tools, GitHub, notebooks, queued
revocation, and cross-learner raw session-key reuse. Delegated Partner web and
external search tools remain outside the school allowlist until their network
and spending policies are separately qualified.

Only the affected receipt rows must be rerun after a change, but the final
candidate browser receipt must be executed from one clean committed SHA.

## 12. Parking lot

- Instructor Course assignment, enrollment, and shared classroom membership.
- Course Progress and advanced Adaptive Remediation.
- Historical learner-data import.
- Broad Partner catalog, persistent learner Partner memory, and unbounded usage.
- BlueWay write-back or multi-owner expansion.
- PDF/exam mimic, proctoring, semantic grading, and spoken answers.
- Sharing, instructor workspaces, cross-Course mastery, and notifications.
- Multi-server coordination, native packaging, and broad device certification.
- Existing lint-warning and `fitz` deprecation cleanup unless they block release.

## 13. Final decision and sign-off

Current decision: `GO_LOCAL_QUALIFICATION / NO_GO_SCHOOL_SHARE`.

The Day 3 result will be signed off only after the candidate commit, validation
matrix, evidence directory, cleanup receipt, and exact remaining proof limits
are recorded here.
