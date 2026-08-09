# Vertical Slice C3 Implementation Receipt

Status: PARTIAL — C3-H1 DETERMINISTIC DESIGN GATE GREEN; THREE AUTOMATED SHORT-ANSWER PASSES; ZERO HUMAN-QUALIFIED OBJECTIVES; CHOICE QUALIFICATION PRECALL BLOCKED; PRIVATE BETA BLOCKED_QUALITY_GATE

Closeout verdict: `BLOCKED_MISSING_PROOF` (`GENUINE_HUMAN_SIGNATURE_AND_BOUNDED_CHOICE_RUNTIME`)

Branch: `feature/teeechr-content-quality-c3`

Base: `74d43de7ac437c13868b02ec14df6696c590693a`

Preserved one-question checkpoint: `d74e910f` on
`fork/feature/teeechr-content-quality-c3`. The assessment-contract implementation
is `ee0f5800`; the objective-qualification receipt and artifacts are preserved by
the current branch history. The evidence-role repair is preserved by
`df222bed`; the fresh OBJ-RESP-01 artifact, qualification matrices, proposed
reviewer amendment, and H1 receipts are preserved by the commit containing this
receipt. `run_c3_h1_2026-08-09.json` intentionally retains the pre-preservation
HEAD and `DIRTY_UNCOMMITTED` capture state rather than rewriting historical
execution provenance.

## Proof ledger

| Layer | Status | Receipt |
| --- | --- | --- |
| Source contract | PROVEN | C3 quality profile, source/objective/citation gates, append-only report/invalidation ledger, and forward migration `0014_content_quality_invalidation.sql` |
| Focused impacted backend tests | PROVEN | The five-file deterministic C3 gate passed `112` tests in `27.39s`, including context/support evidence roles, mandatory claim coverage, objective-qualified claims, aggregate requested-objective coverage, the bounded OBJ-RESP-01 amendment, v3 choice-contract preflight, offline replay, grading, and the Luna probe contract. |
| Full backend regression | PROVEN FOR BEHAVIOR TREE | External Python 3.11 runtime with `pytest -n 4 --dist loadfile -q tests`: `3947 passed, 8 skipped, 34 warnings` in `218.88s`; zero failures. The one allowed broad run preceded the final `review_disposition` → `agent_recommendation` authority-label change; its seven exact amendment/grading/tamper nodes then passed in `0.75s`. |
| Web tests | PROVEN | Node `22.23.2`, npm `10.9.8`: `432 passed, 0 failed` |
| Web lint | PROVEN WITH WARNINGS | exit 0; `0 errors`, `244 warnings` (existing literal-UI-text/image warnings) |
| Web typecheck | PROVEN | standalone `npx tsc --noEmit` exit 0 after the production build generated `.next/types` |
| Web production build | PROVEN | `npm run build` exit 0 under Node `22.23.2`; Next.js `16.2.3`; 62 generated routes |
| Configured provider | THREE OBJECTIVE AUTOMATED GATES PASSED | The sibling local `.env` supplied a process-only `LLM_API_KEY` mapped to `OPENAI_API_KEY`; bounded runs used only OpenAI `gpt-5.6-luna` at medium reasoning. The fresh OBJ-RESP-01 evidence-role probe made exactly one no-retry request and passed automated publication on its first attempt. |
| Human review | OPEN | The evidence-role v2 worksheet keeps agent recommendations and human decision/signature columns separate; every human field remains blank. |
| Browser/runtime | OPEN | no browser campaign was started because genuine human review remains open |

## What is implemented

- C3 `quality_profile` is carried through generation requests, plans,
  operations, fingerprints, and receipts. The deterministic local provider is
  rejected for the C3 profile before publication.
- The C3 publication fence requires an OpenAI provider receipt with request and
  model IDs, usage, latency, exact requested count, approved objective mappings,
  reachable source quotes with offsets, supported answer/explanation text,
  bounded exact short-answer grading with explicit accepted variants where
  needed, distinct wording, and no opaque IDs in learner text.
- A Course-owned bad-question report and review/invalidation path is exposed at
  the Course routes. Report and invalidation history is append-only; immutable
  grading rows remain intact while effective Results, remediation scope, and the
  local learning projection exclude invalidated questions/evidence.
- C3 remediation is bounded to 2–4 proposals in the practice-remediation path;
  baseline remediation remains at eight.
- The learner Practice UI can report a question and displays the adjusted
  effective score/status after invalidation.
- C3 citation validation now evaluates the reachable citation set collectively,
  supports short polarity answers through their evidence-bearing explanation,
  and removes heading-only evidence from the C3 provider vocabulary.
- Archived Mini outputs now replay through a deterministic stage ledger without
  provider cost. The ledger proves the old polarity false negative is repaired,
  retains one genuine primary support failure and one genuine remediation
  support failure, identifies the old wrong-scope substitution, and marks final
  primary/repeat normalization as unrecoverable because raw responses were not
  preserved.
- Every new C3 output must echo a deterministic request contract containing the
  requested objectives, source-scope hash, and generation purpose. Unsupported
  requested objectives abstain before provider admission; generated objectives
  must remain within both the approved and explicitly requested sets.
- C3 publication is pinned to `gpt-5.6-luna`; an accidentally constructed Mini
  C3 adapter is rejected before cost or network work. Mini remains only the
  central registry's inactive emergency rollback definition.
- C3 evidence extraction now preserves exact physical source lines so wrapped
  claims can be supported by a reachable citation set without multiline schema
  literals.
- C3 now separates server-owned `context_evidence` from claim-bearing
  `support_evidence`. Context may orient generation but is never citation
  eligible. The provider returns stable evidence IDs only; the server resolves
  each ID to the immutable source receipt, exact quote, and offsets before the
  adapter and final publication fences accept it.
- Every requested objective has a mandatory claim contract. Claim and evidence
  roles are objective-qualified, required claims must be covered by selected
  support fragments, and emitted questions must collectively cover every
  requested objective. Exact-grade publication also rechecks the assessment
  contract's required answer variants; the validator was not loosened.

## Provider and runtime boundary

### Current Luna-only campaign

- configured and actual model: `gpt-5.6-luna`
- reasoning effort: `medium`
- pricing version: `openai-gpt-5.6-luna-2026-08-01`
- final prompt version: `course-practice-c3-v5`
- final schema version: `course-practice-c3-schema-v6`
- automatic retries: `0`
- provider requests attempted across the preserved Luna campaigns: `7`
- recorded estimated usage across those campaigns: `5,288` micro-USD; the archived probe artifacts do not contain the terminal provider-usage ledger rows, so this package does not independently prove settlement
- one HTTP-400 reservation: `uncertain`, reserved ceiling `4,062` micro-USD
- full primary, repeat, remediation, human review, and browser campaigns:
  `NOT_RUN`

The deterministic unsupported probe passed before network with
`unsupported_by_allowed_sources`, zero questions, and no publication. The first
supported probe abstained because the adapter had exposed none of the multiline
oxygen evidence. After that extractor defect was repaired, a multiline-enum
request received HTTP 400 before generation. The final exact-line request
completed, but Luna selected the opening pathway-stage lines as citations for
the answer `Oxygen`; the publication fence correctly rejected it as
`ANSWER_UNSUPPORTED`. All three artifacts remain preserved as negative
evidence.

The subsequent objective-bound contract exposed only the four exact approved
`OBJ-RESP-02` oxygen lines. One new supported probe then passed on its first
provider attempt with request
`resp_0fba88bf4c09bca6016a7890cf1838819daa1807b90180ba14`, source-scope hash
`20fc89e40da1e4c99116fe434afb338b5a593d96ffc09b7df9ad68dbf0e29e5d`,
1070 input tokens, 606 output tokens, 40 reasoning tokens, `7442ms`, and 942
micro-USD. The raw response and normalized/validated output are preserved at
`evals/reference_course/provider_runs/2026-08-09-gpt-5.6-luna-c3-objective-evidence-v1/supported-one.json`
(SHA-256
`d7eff246b9fbcbf89c47573a6e8c629fd949c23ed532de8f0d011b1c279cbf91`).
The durable Luna summary is
`evals/reference_course/run_openai_2026-08-09_luna.json`.

The evidence-role v2 contract then repaired OBJ-RESP-01 without reordering
quotes, retrying until lucky, or weakening validation. Stage-overview lines are
now context-only; only the pyruvate conversion and cycle-entry fragments are
citation eligible. Exactly one fresh no-retry Luna call passed on its first
attempt with request
`resp_03c77e9915edeb15016a78af951a48819eb7e4d9352078293e`, 1,659 input
tokens, 369 output tokens, 116 reasoning tokens, `3984ms`, and 775 micro-USD.
The artifact is
`evals/reference_course/provider_runs/2026-08-09-gpt-5.6-luna-c3-evidence-roles-v2/obj-resp-01.json`
(SHA-256
`15dadd68d1ce95064cfcae6fb6e03605ccb299090504872cca7ef8a5b86029fc`).
The original rejected artifact remains byte-for-byte unchanged at SHA-256
`35d6fbdf3e64f7fd6f2d325e315318c0e6d273aa3fc8f8ece0123db36d0d3caa`.

### Historical Mini campaign

The isolated external runtime used for the evaluation was:

- Python `3.11.15`: `/Users/home/.codex/runtimes/teeechr-b1-python311/bin/python`
- Node `22.23.2`: `/opt/homebrew/opt/node@22/bin`
- npm `10.9.8`
- provider base URL: `https://api.openai.com/v1`
- provider enabled for the bounded evaluation ledger: `true`
- API key configured in process: `true`; the value was read from the sibling
  checkout and was not copied, printed, or committed
- configured model: `gpt-5-mini`
- actual provider model: `gpt-5-mini-2025-08-07`
- reasoning effort: `minimal`
- pricing version: `openai-gpt-5-mini-pricing-2026-07-29`
- C3 prompt version: `course-practice-c3-v1`
- C3 schema version: `course-practice-c3-schema-v1`

The following paragraph describes the earlier Mini campaign retained for
historical comparison, not the active C3 model policy. Its no-content preflight
passed with a structured abstention (`store=false`).
The final bounded provider campaign made one primary, one repeat, one
unsupported-content, and one remediation request; its generation ledger settled
`7,918` micro-USD. An earlier primary output-rejection attempt settled another
`2,684` micro-USD, for `10,602` micro-USD of recorded generation activity. The
primary was rerun once after the in-scope citation repair; there were no
automatic retries.
No secret was created or persisted, and no deterministic output was relabeled as
educational-quality evidence. The C3 fixture, rubric, failure ledger, provider
outputs, and failed-provider receipt are durable under `evals/reference_course/`.

## Honest boundary

C2 proves the persistence, refresh/resume, deterministic grading, and bounded
remediation mechanics. C3 now proves the source/test/build contracts, local
invalidation, request fidelity, evidence-role enforcement, provider reachability,
local abstention, and three automated objective qualifications. This does not
yet prove a complete Biology set is educationally correct. The five-question
primary, repeat, remediation, independent human review, and browser gates remain
open and were deliberately not started in this bounded closeout. Private beta
remains blocked until those later C3 gates pass.

## Objective qualification campaign

After the one-question checkpoint was committed and pushed to `fork`, three
evaluation-only assessment contracts were frozen in
`evals/reference_course/assessment_contracts_evidence_roles_v2.json`. They distinguish objective
membership from cognitive alignment and exact-grading fairness. The separate
matrix and human worksheet are
`evals/reference_course/objective_qualification_evidence_roles_v2_2026-08-09.csv` and
`evals/reference_course/human_review_objective_qualification_evidence_roles_v2_2026-08-09.csv`.
Agent prechecks are recorded separately and are not represented as human
approval.

The current deterministic C3 gate passed `112` tests in `27.39s`. The current
4-worker closeout regression passed `3947` tests with `8` skips and `34`
warnings in `218.88s`. The warnings include the known macOS pytest
temporary-directory cleanup warning. No provider credential was loaded for
either test command.

The prior objective-qualification campaign made exactly two first-attempt,
no-retry Luna qualification requests:

- `OBJ-RESP-01`: the preserved v1 automated `REJECT` is classified
  `CITATION_ELIGIBILITY_DEFECT`: background context had been incorrectly
  eligible for citation. That artifact remains frozen. Under evidence-role v2,
  one separately authorized first-attempt no-retry request produced the exact
  transition question, cited only support evidence, included the required
  acetyl-CoA variants, and passed automated publication. Genuine human review
  remains open.
- `OBJ-RESP-03`: automated `PASS`. Luna produced one supported fermentation
  versus aerobic-respiration contrast with four reachable citations. Cost:
  1,239 micro-USD. Preliminary agent review flags potential exact-grading
  ambiguity because many defensible three-clause phrasings exist beyond the two
  accepted variants; genuine human review remains open.

The prior `OBJ-RESP-02` automated pass also remains human-review open. Its key
and citations are sound, but its prompt asks only for terminal-acceptor identity
rather than the assessment contract's causal-role explanation. The agent
recommendation is `FAIL_PEDAGOGY`. The OBJ-RESP-03 recommendation is
`FAIL_AMBIGUOUS`; neither recommendation is a human decision. The v2 designs for
those objectives are preserved in
`evals/reference_course/assessment_contracts_v2.json` and remain parked until a
bounded choice grader exists. Therefore zero objectives are currently
human-qualified, and the five-question primary,
repeat, remediation, invalidation runtime, and browser campaigns remain
`NOT_RUN_GATE_BLOCKED`. The durable machine summary is
`evals/reference_course/run_openai_2026-08-09_evidence_roles_v2.json`.

## C3-H1 human qualification and contract-repair result

The historical v1 fixtures and receipts are again byte-for-byte reconstructable:

- `assessment_contracts.json`:
  `411b2b000ef72402d4b18b602ff264d9c7b9c6434d090342f128b083acbf1d08`
- `objective_evidence.json`:
  `3e88864dae72665091e925c59ca6153f372e2bcba391b498da79abe29c6148ab`
- `run_openai_2026-08-09_objective_qualification.json`:
  `59d92290919fd539388a69bca92db05e3458eec2f8908450e8b28127a42184c6`

The evidence-role repair now lives additively in
`assessment_contracts_evidence_roles_v2.json` and
`objective_evidence_roles_v2.json`, preserving the hashes already bound by the
fresh OBJ-RESP-01 artifact. The old failure row remains unchanged; the later
`CITATION_ELIGIBILITY_DEFECT` diagnosis is a separate amendment in
`failures.md`.

OBJ-RESP-01 has a separate proposed answer amendment at
`evals/reference_course/reviewer_amendments/obj-resp-01-answer-variants-v1.json`
(SHA-256
`ef301ff80a8dd80afeb6af0bb28647354477544755a484b3c4f515d5e54ff0ab`).
It binds the unchanged provider artifact, raw-output hash, question index, and
base answer-contract hash; merges the provider's two variants with the six
review-recommended variants; and exhausts the existing eight-variant bound.
The exact grader accepts all nine total answer surfaces (primary plus eight
variants), remains case-insensitive and outer-space tolerant, and rejects
missing punctuation, changed hyphens, doubled internal spaces, reversals, and
nearby wrong concepts. An isolated persisted-attempt test proves the candidate
contract's immutable `exact-v1` evidence hash and idempotent replay.

That amendment remains `PROPOSED_PENDING_HUMAN_SIGNATURE`. Its reviewer,
review timestamp, and signature are null. It is not dynamically overlaid onto
ready Practice, does not rewrite any provider artifact, and is not learner
publication authority. A genuine reviewer must sign the exact candidate, after
which runtime use requires a successor Practice revision rather than mutation
of an immutable ready question.

The original OBJ-RESP-02/03 multiple-choice v2 design remains unchanged at
SHA-256
`9d1deab3d5fa629883b44e3eca90ddc0b4628189a8bb8de2243b7c6df25bff29`.
Sol review found that it omitted one required claim per objective, used
multi-fault or cross-objective distractors, and allowed conspicuous answer-length
cues. It was therefore not used for a provider request. The additive v3 design
at `assessment_contracts_v3_evaluation_only.json` (SHA-256
`45c909a68d67442b77821d62c515d6e7f72d31ab048794a5b51720f777acd5aa`)
uses exact four-option text, equal word counts, all required evidence fragments,
one declared contradicted claim per distractor, and explicit source-format
precedence. It remains `FROZEN_DESIGN_PRECALL_BLOCKED` and
`PARKED_UNTIL_BOUNDED_CHOICE_GRADER_EXISTS`.

C3-H1 made **zero provider requests**. The two no-retry Luna qualifications were
stopped before credential loading or spend because Course Practice currently
has no typed choice answer contract, learner-safe option projection, option-ID
autosave validation, choice-aware SQLite grading validation, or accessible
radio UI. A design-only model response could not truthfully be called
publishable Course Practice. No five-question, remediation, browser,
invalidation, or beta campaign was opened.

The C3-H1 machine receipt is
`evals/reference_course/run_c3_h1_2026-08-09.json` (SHA-256
`1a7ef337aba35b306b6aa980dc6b82947812b5d5be32e9cbe73833a197743092`).

## Remaining source-materialization seam

The persisted deterministic index stores a source receipt beside derived chunks,
but the receipt does not independently bind mutable chunk payloads. This is a
pre-existing local source-materialization trust seam, not evidence-role v2 proof:
the qualification script read fixture files directly and hashed those exact
bytes. Before enabling a real production C3 evidence-policy resolver against
persisted Course indexes, treat the index as a cache and derive quote/offset
authority from raw private source files revalidated against the database-owned
source receipt. A checksum stored beside mutable chunks would not close this
gate.
