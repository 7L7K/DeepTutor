# Vertical Slice C3 — Trustworthy Course Content and Evidence

Status at packet creation: implementation lane opened from the final C2 head.
The C2 learning-loop mechanics are frozen. C3 is the bounded content-quality
and evidence lane for one permission-safe Biology 101 / Fall 2026 reference
Course.

## Finish line

An approved non-production provider may propose a grounded Biology explanation
and a five-question Practice revision. The server must publish nothing unless
every question has a supported answer, a reachable source locator, a valid
non-empty objective mapping, a supported exact-answer grade contract, and
distinct learner wording. Results, remediation, and a bad-question report must
remain truthful when one question is later invalidated.

This slice proves source, tests, build, provider-evaluation, and local browser
evidence separately. A deterministic provider can prove contracts, but it is
not an educational-quality pass and cannot be the C3 golden run.

## Base and protected boundaries

- Base: `74d43de7ac437c13868b02ec14df6696c590693a`
- Branch: `feature/teeechr-content-quality-c3`
- Worktree: `/Users/home/Desktop/2k26/teeech/DeepTutor-content-quality-c3`
- C2 remains at `/Users/home/Desktop/2k26/teeech/DeepTutor-course-learning-loop-c2`.
- Do not modify BlueWay, hosted environments, production secrets, or frozen
  migrations. C3 may add a new forward migration only if durable invalidation
  cannot be expressed safely in the existing schema.

## Reference Course packet

The permission-safe original fixture is under
`evals/reference_course/`:

- `sources/syllabus_excerpt.md`
- `sources/lecture_06_transcript.md`
- `sources/lecture_06_slides.md`
- `sources/reading_excerpt.md`
- `objectives.json`
- `cases.jsonl`
- `rubric.md`
- `human_review_2026-08-08.csv`
- `failures.md`

The three approved objectives are `OBJ-RESP-01`, `OBJ-RESP-02`, and
`OBJ-RESP-03`. They are fixture authority for the evaluation only; the
provider cannot invent or activate objectives.

## Current implementation seams

| Contract | Current source | C3 decision |
| --- | --- | --- |
| Course ownership/source snapshot | `deeptutor/courses/repository.py`, `practice_repository.py` | REUSE; source IDs/revisions/hashes remain server-derived |
| Practice generation | `deeptutor/courses/generation_service.py`, `generation_repository.py` | EXTEND with a C3 quality profile and pre-publication validator |
| Real provider | `deeptutor/courses/generation_provider.py` | REUSE OpenAI Responses adapter; no tools, no provider-stored content |
| Provider receipt | `practice_set_revisions.generation_receipt_json` | EXTEND with quality verdict, profile, latency, usage, request/model IDs |
| Deterministic provider | `deeptutor/courses/deterministic_provider.py` | PARK for C2 contract tests; never a C3 golden-quality result |
| Exact grading | `deeptutor/courses/grading_repository.py`, `grading_service.py` | REUSE; invalidation is an external evidence-validity ledger |
| Review/remediation | `/api/v1/courses/{courseId}/practice/.../flashcard-brief` | EXTEND to exclude invalid questions and cap C3 proposals at 2–4 |
| Bad-question report | new `content_quality_repository.py` / service and Course routes | ADD local owner/admin-safe report -> review -> invalidation path |
| Learner Practice UI | `web/components/practice/PracticeWorkspace.tsx` | EXTEND only for truthful quality/invalidation indicators |

## Quality gate

The C3 validator runs after source text resolution and provider normalization,
before `complete_operation` can insert questions or mark a revision ready.
It checks:

1. The provider is a configured non-production provider; deterministic-local is
   rejected for the C3 profile.
2. Every question has one or more valid approved objective IDs.
3. Every citation resolves to the frozen Course source owner, revision, and
   content hash; its evidence quote is present and receives a concrete offset
   locator.
4. The answer and explanation are supported by the cited source text.
5. Questions are distinct under exact and near-duplicate normalization.
6. The question is standalone, non-leaking, unambiguous, and uses the exact
   server grade contract.
7. A C3 receipt records the Course/source/objective/provider/time boundary.

An unsupported or malformed response fails closed. It is not a partial ready
revision and is not relabeled as a provider success.

## Learning-loop acceptance

The local campaign will use one five-question revision and a deterministic
answer key for the test harness only:

1. begin a real Biology question and receive a supported cited explanation;
2. select `Quiz me` and receive five meaningful objective-mapped questions;
3. answer three correctly and two incorrectly;
4. refresh/resume, submit, and inspect Results and both misses;
5. request 2–4 targeted Review proposals, approve selected items, and retain
   the attempt/evidence provenance;
6. report one intentionally flawed question, resolve it as invalidated, and
   verify the question/evidence are excluded from effective Results and future
   remediation/learning projection.

The invalidation table is append-only. Existing grading rows remain immutable;
the validity ledger is the authoritative correction event, and the local
learning projection is reconciled so an invalid question creates no durable
learning effect.

## Out of scope

Syllabus parsing, automatic week extraction, topic graphs, Progress UI,
recommendations, Study Sessions, BlueWay work, hosted production, multiple
subjects, autonomous objectives, voice, and release infrastructure remain
parked.

## C2 provenance note

C2's authoritative local Practice set is
`prc_7de79a91b080461781cb9a377e24346b`, revision
`prv_5e31cb9489b34b89b376a29f951f6830`, attempt
`att_2cfbb798c5a44c6299f1261bcbdc4173`, and remediation operation
`ofg_2488292685e2407283107329b2f6afd7`. The archived campaign also contains
older same-title `Course quiz` rows from local retries. Those rows are not
interchangeable evidence. The archived C2 export does not retain the original
Practice-set assistant-message/idempotency binding; it retains the attempt and
missed-question/evidence binding for the authoritative run. C3 preserves this
limitation and records complete provenance for new quality-profile operations.

## Closeout evidence

The source and local contract lane is green on the isolated C3 branch:

- Focused C3, migration, generation, grading, flashcard-generation, provider,
  and co-writer checks: `138 passed`.
- After the provider-evaluation citation repair, the directly impacted C3,
  OpenAI-adapter, and grading-contract checks pass: `64 passed`.
- Full backend regression with the required external Python 3.11 runtime and
  four workers: `3899 passed, 8 skipped, 34 warnings` using
  `pytest -n 4 --dist loadfile -q tests` in `199.97s`. The added C3 tests cover
  bounded answer variants, exact citation-offset provenance, collective
  citation support, and withdrawal of already-derived Review cards after
  invalidation.
- Web under Node `22.23.2` / npm `10.9.8`: `432` Node tests passed, lint exit 0
  with 244 warnings and 0 errors, standalone TypeScript check passed, and the
  Next.js production build passed with 62 generated routes.

The real provider evaluation reached the API on 2026-08-09 using the
process-only `LLM_API_KEY` from the sibling local checkout, mapped to the C3
`OPENAI_API_KEY` contract, with `gpt-5-mini`. The no-content preflight passed
with abstention, but the bounded Biology campaign did not pass the publication
fence: primary and repeat provider outputs failed adapter validation, the
remediation output failed citation support, and the unsupported probe returned a
source-grounded answer instead of abstaining from its requested out-of-scope
topics. The durable receipt is
`evals/reference_course/run_openai_2026-08-09.json` with status
`PROVIDER_REACHED_C3_QUALITY_GATE_FAILED`. The deterministic provider remains
test-only and is not educational-quality evidence.

Browser/runtime proof is also open. No browser campaign, golden Biology set,
human approval, or student-value claim should be inferred from the local tests.

## Luna-only replay and request-fidelity amendment

The active C3 publication policy is now `gpt-5.6-luna` at medium reasoning.
Mini is not eligible for C3 Practice or remediation publication. It remains
defined only as the central registry's inactive emergency rollback model, and
the C3 adapter rejects it before admission, cost, or network work.

Before the Luna campaign, all five archived Mini artifacts were replayed
offline. The machine-readable ledger at
`evals/reference_course/provider_runs/2026-08-09-c3-offline-replay-ledger.json`
made zero provider requests and found:

- the old primary polarity-answer false negative is repaired;
- earlier primary item 2 still genuinely lacks answer support;
- final primary and repeat cannot be normalized offline because their raw
  provider responses were never preserved;
- the old unsupported probe passes the historical validator but fails the new
  `request_objective_fidelity` stage;
- remediation item 1 remains genuinely unsupported.

The C3 provider and publication validator now require one deterministic request
contract: request-contract ID, explicitly requested objective IDs, exact source
scope hash, and generation purpose. Requested objectives must be a subset of
the approved objective allowlist. A mismatch produces a local structured
abstention with no provider call, question, Practice revision, or Review item.
Provider-generated objectives must remain inside both sets.

The bounded Luna campaign then proved the deterministic unsupported abstention,
but did not clear one supported question. An initial supported request abstained
because the borrowed flashcard evidence extractor had silently omitted every
multiline oxygen passage. The repaired multiline-enum request received HTTP 400
before generation. The final exact-line request completed under prompt v3 and
schema v4, but cited only the opening pathway-stage lines for the answer
`Oxygen`. The publication fence rejected it as `ANSWER_UNSUPPORTED`.

That v4 result was retained as negative evidence and was not overwritten. No
validator threshold was weakened and no tune-and-retry campaign followed it.

## Objective-bound evidence closeout

The v4 failure established that an approved objective allowlist alone was not
an evidence-selection contract: Luna could still choose any exact line from the
whole Course packet. C3 now carries a typed, server-owned objective-evidence
binding containing the objective ID, exact source ID, source revision, content
hash, and exact reachable physical source lines. The Biology fixture authority
is `evals/reference_course/objective_evidence.json`; the generic provider does
not hard-code Biology mappings.

Before admission, the C3 provider verifies that requested objectives are an
approved subset, every requested objective has eligible bound evidence, every
binding matches the frozen material receipt, and every quote is exactly
reachable. Missing or stale evidence produces a structured local abstention
before ledger reservation, cost, client creation, or network work. The request
contract's source-scope hash is derived from only the requested objectives'
bound evidence. Provider input and citation enums contain only that narrowed
evidence, and both adapter normalization and the publication validator reject
a citation bound only to another objective.

Final proof on the objective-binding worktree:

- Direct C3/provider/replay gate: `46 passed` in `3.57s`.
- Complete Course Practice suite: `244 passed, 4 warnings` in `37.54s`.
- Full backend under the external Python 3.11 runtime with four workers:
  `3913 passed, 8 skipped, 34 warnings` in `211.09s`.
- One new first-attempt-only Luna supported probe used prompt v4, schema v5,
  medium reasoning, `store=false`, and zero automatic retries. It generated
  exactly one `OBJ-RESP-02` question, cited only the four approved oxygen lines,
  and passed the publication fence on its first provider attempt.
- Provider receipt: request
  `resp_0fba88bf4c09bca6016a7890cf1838819daa1807b90180ba14`, 1070 input
  tokens, 606 output tokens, 40 reasoning tokens, `7442ms`, and 942 micro-USD.
- Durable artifact:
  `evals/reference_course/provider_runs/2026-08-09-gpt-5.6-luna-c3-objective-evidence-v1/supported-one.json`,
  SHA-256
  `d7eff246b9fbcbf89c47573a6e8c629fd949c23ed532de8f0d011b1c279cbf91`.

The bounded one-question eligibility gate is now green. Per the campaign
boundary, the five-question primary, repeat, remediation, human-review, and
browser gates remain `NOT_RUN`; this pass is not yet an educational-quality or
private-beta claim. The durable campaign summary is
`evals/reference_course/run_openai_2026-08-09_luna.json`.
