# Vertical Slice C3 Implementation Receipt

Status: PARTIAL — ONE OBJECTIVE QUALIFIED; FULL EDUCATIONAL CAMPAIGN OPEN; SOURCE / TEST / BUILD PROVEN; OBJECTIVE-BOUND EVIDENCE PROVEN; PRIVATE BETA BLOCKED_QUALITY_GATE

Closeout verdict: `PASS_BOUNDED_SINGLE_QUESTION_GATE_CONTINUE_C3`

Branch: `feature/teeechr-content-quality-c3`

Base: `74d43de7ac437c13868b02ec14df6696c590693a`

Current repository HEAD: `1c7af76d` (the Luna replay/fidelity work is an uncommitted, unpushed working-tree checkpoint)

## Proof ledger

| Layer | Status | Receipt |
| --- | --- | --- |
| Source contract | PROVEN | C3 quality profile, source/objective/citation gates, append-only report/invalidation ledger, and forward migration `0014_content_quality_invalidation.sql` |
| Focused impacted backend tests | PROVEN | `46 passed` in `3.57s` across the current C3 validator, offline replay, Luna policy, request-fidelity, objective-evidence admission, stale/missing abstention, cross-objective citation rejection, and OpenAI adapter surface; the complete Course Practice suite is `244 passed, 4 warnings` in `37.54s` |
| Full backend regression | PROVEN | External Python 3.11 runtime with `pytest -n 4 --dist loadfile -q tests`: `3913 passed, 8 skipped, 34 warnings` in `211.09s`; zero additional failures |
| Web tests | PROVEN | Node `22.23.2`, npm `10.9.8`: `432 passed, 0 failed` |
| Web lint | PROVEN WITH WARNINGS | exit 0; `0 errors`, `244 warnings` (existing literal-UI-text/image warnings) |
| Web typecheck | PROVEN | standalone `npx tsc --noEmit` exit 0 after the production build generated `.next/types` |
| Web production build | PROVEN | `npm run build` exit 0 under Node `22.23.2`; Next.js `16.2.3`; 62 generated routes |
| Configured provider | ONE-QUESTION PUBLICATION GATE PASSED | The sibling local `.env` supplied a process-only `LLM_API_KEY` mapped to `OPENAI_API_KEY`; the bounded run used only OpenAI `gpt-5.6-luna` at medium reasoning. The objective-bound supported probe generated exactly one `OBJ-RESP-02` question, cited only approved oxygen evidence, and passed on its first provider attempt. |
| Human review | OPEN | `evals/reference_course/human_review_2026-08-08.csv` is a review template, not a golden approval |
| Browser/runtime | OPEN | no browser campaign was claimed because no provider output passed the C3 quality gate |

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
- C3 now carries a typed server-owned objective-evidence contract. Each binding
  fixes the objective, source ID, revision, content hash, and exact reachable
  lines before provider admission. The narrowed objective evidence—not the
  entire Course packet—drives the request hash, provider input, schema citation
  enum, adapter checks, and publication validator. Missing or stale bindings
  abstain before cost or network work; cross-objective citations fail closed.

## Provider and runtime boundary

### Current Luna-only campaign

- configured and actual model: `gpt-5.6-luna`
- reasoning effort: `medium`
- pricing version: `openai-gpt-5.6-luna-2026-08-01`
- final prompt version: `course-practice-c3-v4`
- final schema version: `course-practice-c3-schema-v5`
- automatic retries: `0`
- provider requests attempted: `4`
- settled usage: `2,578` micro-USD
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
invalidation, request fidelity, objective-bound evidence, provider reachability,
local abstention, and one first-attempt publishable Luna question. This does not
yet prove a complete Biology set is educationally correct. The five-question
primary, repeat, remediation, independent human review, and browser gates remain
open and were deliberately not started in this bounded closeout. Private beta
remains blocked until those later C3 gates pass.
