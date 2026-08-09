# Vertical Slice C3 Implementation Receipt

Status: SOURCE / TEST / BUILD PROVEN; PROVIDER_REACHED_C3_QUALITY_GATE_FAILED; EDUCATIONAL QUALITY UNPROVEN; PRIVATE BETA BLOCKED_QUALITY_GATE

Closeout verdict: `BLOCKED_MUST_FIX`

Branch: `feature/teeechr-content-quality-c3`

Base: `74d43de7ac437c13868b02ec14df6696c590693a`

Implementation HEAD: `61345de8` (local concern-separated checkpoints; not pushed)

## Proof ledger

| Layer | Status | Receipt |
| --- | --- | --- |
| Source contract | PROVEN | C3 quality profile, source/objective/citation gates, append-only report/invalidation ledger, and forward migration `0014_content_quality_invalidation.sql` |
| Focused impacted backend tests | PROVEN | `64 passed` across the C3 validator, OpenAI practice adapter, and grading-contract checks after the citation-support repair; the earlier C3 packet contains the broader `138 passed` focused checkpoint result |
| Full backend regression | PROVEN | External Python 3.11 runtime with `pytest -n 4 --dist loadfile -q tests`: `3899 passed, 8 skipped, 34 warnings` in `199.97s`; the superseded serial attempt was interrupted after it exceeded the prior runtime boundary with no reported failure |
| Web tests | PROVEN | Node `22.23.2`, npm `10.9.8`: `432 passed, 0 failed` |
| Web lint | PROVEN WITH WARNINGS | exit 0; `0 errors`, `244 warnings` (existing literal-UI-text/image warnings) |
| Web typecheck | PROVEN | standalone `npx tsc --noEmit` exit 0 after the production build generated `.next/types` |
| Web production build | PROVEN | `npm run build` exit 0 under Node `22.23.2`; Next.js `16.2.3`; 62 generated routes |
| Configured provider | REACHED, QUALITY GATE FAILED | The sibling local `.env` supplied a process-only `LLM_API_KEY` mapped to `OPENAI_API_KEY`; the bounded run used OpenAI `gpt-5-mini` and reached the API. No golden revision was published: primary/repeat hit provider-output rejection, remediation failed citation support, and the unsupported probe returned an answer instead of abstaining. |
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

## Provider and runtime boundary

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

The no-content preflight passed with a structured abstention (`store=false`).
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
remediation mechanics. C3 now proves the source/test/build contracts, the local
invalidation implementation, provider reachability, and no-content abstention.
It does not yet prove that Biology content is educationally correct. The real
provider returned at least one semantically out-of-scope answer for the
unsupported probe, and the primary/repeat/remediation outputs did not pass the
publication fence. Human review and browser proof therefore remain blocked.
The next smallest closeout action is to inspect the durable provider failures,
correct the provider-generation contract or model selection as warranted, run a
fresh five-question Biology evaluation, complete independent human review, and
only then run the bounded browser campaign.
