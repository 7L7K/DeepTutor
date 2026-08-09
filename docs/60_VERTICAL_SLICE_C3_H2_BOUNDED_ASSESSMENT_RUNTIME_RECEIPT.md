# Vertical Slice C3-H2 Bounded Assessment Runtime Receipt

Status: SOURCE / FOCUSED TEST / BROAD REGRESSION / WEB BUILD / LOCAL BROWSER RUNTIME PROVEN; HUMAN QUALIFICATION OPEN; PROVIDER QUALIFICATION NOT RUN; PRIVATE BETA BLOCKED

Branch: `feature/teeechr-content-quality-c3`

Base: `9954350b4d1273cde4fc86ddea54f6e71d86ecda`

H2 source commit series:

- `9f8d60c5` — `feat(practice): add bounded assessment runtime`
- `d089babb` — `fix(quality): reconcile invalidated assessment authority`
- `21c40d97` — `feat(web): support bounded Practice interactions`
- `2152ac03` — `test(c3): prove bounded assessment and correction contracts`

Final tested source HEAD: `2152ac03`

Docs archive commit: `THIS_COMMIT`

Push target: `fork/feature/teeechr-content-quality-c3`

## Authority boundary

C3-H2 implements a deterministic learner runtime. It does not approve an
assessment, sign a human-review disposition, publish a provider generation, or
open private beta. The mixed Biology runtime fixture uses frozen repository
contracts as manual test data only. The additive OBJ-RESP-01 bounded-answer
amendment remains unsigned and pending genuine human review.

No Luna or other provider request was made during H2 implementation or its
deterministic validation.

## Runtime contracts implemented

- `bounded_short_answer_v1` applies only the named normalization contract:
  Unicode compatibility normalization, safe dash canonicalization,
  case-folding, whitespace collapse, and bounded trailing sentence punctuation.
  Correctness is membership in an explicit normalized allowlist; there is no
  fuzzy, semantic, or AI grading.
- `single_choice_v1` freezes opaque option IDs and display order into the
  immutable Practice revision and attempt presentation. Learner writes contain
  exactly one option ID. Foreign, malformed, text-substituted, or cross-question
  selections fail before persistence.
- Python and managed SQLite connections execute the same deterministic grader
  and seal the algorithm, normalized response, option-order hash, contract hash,
  and correctness into immutable grading evidence.
- Ready learner projections withhold the answer contract, explanation, and
  answer-adjacent citation locators. Durable graded Results reveal the selected
  answer, correct answer, explanation, and Course citation.
- Short answers autosave after a 500 ms debounce. Choice answers autosave
  immediately. Writes are serialized per attempt item, reuse the idempotency key
  after failure, rotate it only after durable success, and flush before
  navigation or submission.
- The web runner uses native `fieldset`, `legend`, labelled radio inputs, a
  visible selected state, per-item live save status, and ordinary keyboard radio
  behavior.
- Missing answer rows, partial grading, malformed post-0015 contracts, invalid
  option permutations, invalidated pending evidence, and legacy-upgrade
  ambiguity all fail closed. Pre-0015 exact questions with historical bounded
  type labels remain readable and gradeable; new authoring is canonical.
- New attempts materialize only questions that remain trustworthy. A partially
  invalidated revision admits its valid subset; a fully invalidated revision
  returns `409 no_valid_questions` and exposes no Start or Try-again action.
- An already-open attempt containing a withdrawn question becomes read-only:
  autosave, submit, and pre-grade grading fail closed, while abandon remains an
  explicit escape to a new valid-only attempt.
- Learner-facing attempt detail, history, and Results redact withdrawn item
  grading and superseded raw scores. Immutable raw grades and evidence remain
  available only in the internal stored audit receipt.

## Deterministic proof ledger

Environment:

- Python `3.11.15` at
  `/Users/home/.codex/runtimes/teeechr-b1-python311/bin/python`
- Node `22.23.2` at `/opt/homebrew/opt/node@22/bin`
- npm `10.9.8`
- provider credential loaded: `false`
- provider requests: `0`

Results:

| Layer | Result |
| --- | --- |
| H2/H2.1 affected backend and migration gate | `150 passed`, one existing macOS temporary-directory warning, `94.11s` |
| Exact owner-isolation and invalidation nodes | `6 passed`, one existing warning, `7.58s`; submitted-before-withdrawal grade guard `1 passed`, `1.31s` |
| Exact invalidated-grade replay node | `1 passed`, one existing warning, `1.47s`; the replay returned the learner-safe adjusted projection rather than the immutable raw score |
| Exact C3 deterministic five-file gate | `114 passed`, `33.24s` |
| First broad regression | `3973 passed`, `1 failed`, `8 skipped`, `34 warnings`, `369.23s`; the one failure was a stale pre-H2 citation-projection expectation |
| Focused stale-expectation repair | exact generation API node `1 passed` in `1.25s`; ready learner questions now withhold citations until Results |
| Final clean closeout broad regression | `3987 passed`, `8 skipped`, `34 warnings`, `255.61s`, exit `0` |
| Web Node tests | `446 passed`, `0 failed` |
| Web lint | exit `0`; `250` existing non-blocking warnings and no errors |
| Web TypeScript | `npx tsc --noEmit` exit `0` |
| Web production build | exit `0`; Next.js `16.2.3`; all 62 routes generated, including Course Practice and exact attempt routes |
| Browser campaign | mixed-assessment/foreign phase `2 passed`, `2 skipped`, `13.8s`; corrected Results phase `1 passed`, `3 skipped`, `2.9s`; admission phase `1 passed`, `3 skipped`, `5.0s`; final script exit `0` |
| Independent live browser check | unauthenticated `/classes` redirected to `/login?next=%2Fclasses`; login form rendered and accepted focus; console warnings/errors `0` |
| Independent Sol authority review | `PASS`; no P0-P2 authority or security blocker remained in `9954350b..2152ac03` |

The first broad regression remains recorded as a failed intermediate proof
layer; it is not relabelled green. One later broad run was interrupted after Sol
found two authority gaps and is not counted as proof. The final `3987`-test run
is the authoritative closeout regression. The browser campaign likewise retains
its failed intermediate selector attempts; only the final three green phases are
closeout proof.

The final independent Sol review rechecked the previously blocked grade-replay
path and the adjacent detail, list, Results, withdrawn-attempt, partial/full
invalidation, and cross-user surfaces. It returned `PASS` with no remaining
P0-P2 authority or security finding. The review was read-only and made no
provider or external call.

## Local browser and correction proof

The hermetic campaign used one disposable owner, one disposable foreign user,
one private Biology Course, one mixed two-question Practice revision, and no
provider credential. It proved:

- bounded short-answer normalization accepted the explicit allowlisted variant;
- the server-issued opaque option IDs exposed no semantic answer labels;
- the attempt-specific option order remained stable after reload;
- short-answer autosave survived refresh, Course navigation, direct reopen, and
  later abandonment only after the UI displayed `Saved`;
- native radio controls accepted keyboard selection and autosaved immediately;
- malformed/foreign option-ID tampering failed before persistence;
- duplicate submit did not create duplicate attempt evidence;
- graded Results reopened directly at desktop and narrow-mobile viewports;
- the foreign account could not open the owner Course or attempt;
- two correction reports invalidated both questions without mutating the raw
  `1/2` grade or its two evidence records;
- effective Results became `0/0`, displayed `No scored questions remain after
  review`, retained the historical learner responses, and withheld grading,
  correct-answer, explanation, and citation authority;
- durable invalidation replay remained stable across two restarted-service
  reconciliation passes; the derived Review deck/card were archived and future
  remediation was blocked;
- partial invalidation created a one-item attempt containing only the valid
  question, with the withdrawn question absent from the attempt and its evidence;
- full invalidation rendered `No trustworthy questions remain`, hid Start and
  Try-again actions, and returned `409 no_valid_questions` to a direct attempt
  request at desktop and narrow-mobile viewports;
- the invalidation ledger retained four audit rows for two questions, while
  product counts use `COUNT(DISTINCT question_id)` and report two withdrawn
  questions rather than four;
- withdrawn question reporting controls render `Reported and withdrawn` and are
  disabled against duplicate reporting.

Durable evidence is under:

`docs/verification/2026-08-09-teeechr-c3-h2-bounded-assessment/`

Key artifacts:

- `runtime.txt` — exact runtime, branch, pre-archive committed HEAD, zero provider
  calls, and `human_approval=false`. The browser campaign ran against the final
  browser-relevant source now committed through `21c40d97`. The later Python API
  grade-replay projection fix in `d089babb` did not change the browser surface;
  its exact regression node, full 150-test H2/H2.1 gate, and replacement broad
  regression passed at `2152ac03`;
- `backend/migration-0015-populated-history.json` —
  `PASS_POPULATED_HISTORY_0015`, retained history counts, migration digest, and
  an empty foreign-key issue list;
- `backend/backend-receipt.json` — `PASS_BACKEND_CORRECTION_RECEIPT`, immutable
  raw-grade/evidence digests, effective-score correction, replay stability, and
  Review withdrawal;
- `playwright-campaign-output.txt`, `playwright-corrected-output.txt`, and
  `playwright-admission-output.txt` — exact final browser test results;
- desktop, narrow-mobile, foreign-denial, withdrawn-state, and independent
  login-focus screenshots under `screenshots/`;
- `MANIFEST.sha256` — SHA-256 inventory for every durable evidence file.

The receipt and exact verification directory are intentionally force-added by
the docs archive commit because the repository ignores `/docs/*`. No other
ignored documentation tree is included.

## Security and migration closure

- Migration `0015_bounded_assessment_runtime.sql` is additive and forward-only;
  no historical migration was changed.
- The existing grading-evidence table is rebuilt only to widen its algorithm
  allowlist, with retained evidence and invalidation rows copied and foreign-key
  integrity rechecked by migration tests.
- Managed Course connections register strict question-contract and grading UDFs.
  Raw post-0015 bounded/choice authoring fails closed when those validators are
  unavailable.
- Invalidated pending evidence cannot be redelivered into learning state.
- The authoritative Course grading error type survives the SQLite-to-learning
  projection without independent reclassification.
- Raw attempt grades and evidence remain immutable. Effective score and derived
  Review state are recomputed through the existing append-only invalidation
  path.
- Withdrawn attempts cannot be autosaved, submitted, or graded after the
  invalidation decision. Direct attempt reads remain available only as explicit
  read-only history; abandon is the sole in-progress mutation still allowed.
- Direct attempt detail, attempt lists, and Results share one learner-safe
  invalidation projection. Invalidated item correctness and raw scores are not
  recoverable through an alternate learner endpoint.
- Owner-private Course, set, attempt, Results, and list surfaces preserve uniform
  foreign-user `404` behavior.

## Open gates

- Obtain genuine human-signed dispositions for the three historical v1
  objective artifacts. Agent recommendations remain non-authoritative.
- Only after deterministic runtime and browser proof, create the v4
  generation-oriented constraints and run the separately authorized one-shot,
  no-retry Luna qualifications for OBJ-RESP-02 and OBJ-RESP-03.
- Do not open the five-question campaign, remediation campaign, human content
  review, or private beta until all upstream gates pass.
