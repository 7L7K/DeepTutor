# Vertical Slice C3 Implementation Receipt

Status: SOURCE / TEST / BUILD PROVEN; BLOCKED_PROVIDER_NOT_CONFIGURED; EDUCATIONAL QUALITY UNPROVEN; PRIVATE BETA BLOCKED_QUALITY_GATE

Branch: `feature/teeechr-content-quality-c3`

Base: `74d43de7ac437c13868b02ec14df6696c590693a`

Implementation HEAD: `c5bbb54c` (local concern-separated checkpoints; not pushed)

## Proof ledger

| Layer | Status | Receipt |
| --- | --- | --- |
| Source contract | PROVEN | C3 quality profile, source/objective/citation gates, append-only report/invalidation ledger, and forward migration `0014_content_quality_invalidation.sql` |
| Focused backend tests | PROVEN | `138 passed` across C3, migration, generation, grading, flashcard-generation, OpenAI-adapter, and co-writer checks; the C3 packet includes bounded-answer, citation-offset, and derived-Review invalidation coverage |
| Full backend regression | PROVEN | External Python 3.11 runtime with `pytest -n 4 --dist loadfile -q tests`: `3898 passed, 8 skipped, 34 warnings` in `427.57s`; the superseded serial attempt was interrupted after it exceeded the prior runtime boundary with no reported failure |
| Web tests | PROVEN | Node `22.23.2`, npm `10.9.8`: `432 passed, 0 failed` |
| Web lint | PROVEN WITH WARNINGS | exit 0; `0 errors`, `244 warnings` (existing literal-UI-text/image warnings) |
| Web typecheck | PROVEN | standalone `npx tsc --noEmit` exit 0 after the production build generated `.next/types` |
| Web production build | PROVEN | `npm run build` exit 0 under Node `22.23.2`; Next.js `16.2.3`; 62 generated routes |
| Configured provider | BLOCKED_PROVIDER_NOT_CONFIGURED | `OPENAI_API_KEY` is absent; configured provider is OpenAI model `gpt-5.6-luna`, medium reasoning, pricing `openai-gpt-5.6-luna-2026-08-01`; no provider call attempted |
| Human review | OPEN | `evals/reference_course/human_review_2026-08-08.csv` is a review template, not a golden approval |
| Browser/runtime | OPEN | no browser campaign was claimed because the real provider/content receipt is not configured |

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

## Provider and runtime boundary

The isolated external runtime used for the evaluation was:

- Python `3.11.15`: `/Users/home/.codex/runtimes/teeechr-b1-python311/bin/python`
- Node `22.23.2`: `/opt/homebrew/opt/node@22/bin`
- npm `10.9.8`
- provider base URL: `https://api.openai.com/v1`
- provider enabled: `false`
- API key configured: `false`
- configured model: `gpt-5.6-luna`
- reasoning effort: `medium`
- pricing version: `openai-gpt-5.6-luna-2026-08-01`
- C3 prompt version: `course-practice-c3-v1`
- C3 schema version: `course-practice-c3-schema-v1`

No secret was created, no paid request was made, and no deterministic output was
relabeled as educational-quality evidence. The C3 fixture, rubric, failure
ledger, and blocked provider receipt are durable under `evals/reference_course/`.

## Honest boundary

C2 proves the persistence, refresh/resume, deterministic grading, and bounded
remediation mechanics. C3 now proves the source/test/build contracts and the
local invalidation implementation. It does not yet prove that Biology content
is educationally correct: `OPENAI_API_KEY` is absent, so the required
no-content preflight, real generations, human review, and browser campaign were
not attempted. The next smallest closeout action is to provide an approved
non-production credential outside Git, run the five-question Biology
evaluation, archive its request/model/usage/latency receipt, complete human
review, and then run the bounded browser campaign.
