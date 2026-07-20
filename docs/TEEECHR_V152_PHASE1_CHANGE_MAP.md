# TEEECHR v1.5.2 Phase 1 Change Map

## Purpose and boundary

This document records what exists in the pre-v1.5.2 TEEECHR fork, what each
change was intended to do, and how it should be treated during a future port.
Phase 1 preserves and proves the source states only. It does not migrate a
TEEECHR feature, modify production, or claim that the authenticated learner
flows work on DeepTutor v1.5.2.

## Repository truth at preservation time

- Historical checkout: `/Users/home/Desktop/2k26/teeech/DeepTutor`
- Historical base branch before preservation: `main`
- Historical HEAD: `e991e79f3ef65c70181d0d46094fecdc887373b1`
- Preservation branch: `safety/teeechr-pre-v152-20260720`
- Upstream reference: `origin/main` at
  `b728354863540466f5410bec3530eb55a9fe0edc` (`v1.5.2`)
- Divergence after a fresh fetch: 13 local commits ahead and 419 upstream
  commits behind
- Direct merge forecast: 60 conflicts across an upstream delta touching 1,511
  files
- Patch-equivalence check: none of the 12 non-merge TEEECHR commits has an
  exact equivalent in `origin/main`

The production URL returned HTTP 200 for the home page and API documentation
during the investigation. The public OpenAPI document still exposed TEEECHR
access, Knowledge, Practice, Flashcard, and Session endpoints. Authenticated
behavior, learner data, WebSocket delivery, and physical production data were
not exercised.

## Committed TEEECHR product line

| Commit | What it introduced | Future treatment |
| --- | --- | --- |
| `949f5a8e` | Dedicated Practice and Flashcards flows, saved attempts/decks, quiz submission, APIs, UI, and tests | Preserve as the main product reference; reimplement against the current question/learning architecture |
| `16888d3d` | Private tester access codes, signed tester identity, tester-scoped data, deployment script, runbook, and domain configuration | Preserve the code-entry UX only; map successful claims into upstream users and sessions |
| `e9690048` | Faster knowledge-backed quiz generation | Preserve the latency goal and tests; do not copy the old coordinator |
| `abd66721` | Progressive Practice rendering and early streamed output | Preserve the user-visible responsiveness contract |
| `8f71829d` | Earlier first grounded quiz question | Preserve as a performance experiment and measurement case |
| `f1adc134` | Larger exam batching and scaling | Preserve batch-size and completion behavior as test cases |
| `51baed9d` | Warm-up question streaming | Preserve only if it still improves the new pipeline |
| `b230e239` | Starter-page generation | Preserve the first-useful-page contract |
| `27c63bdc` | Responses API structured-output benchmark path | Preserve benchmark inputs/results; re-evaluate on current provider adapters |
| `f9e801f9` | Minimal Responses starter benchmark refinement | Preserve as benchmark history, not production authority |
| `07731741` | TEEECHR import-path, logging, UI, and Practice polish | Port behavior selectively after the v1.5.2 baseline is stable |
| `00d4ef74` | Merge of upstream v1.3.7 into the local TEEECHR line | Historical integration boundary only |
| `e991e79f` | Production API startup repair that removed an obsolete Guide router import | Preserve the startup acceptance test; v1.5.2 has a different bootstrap |

## Uncommitted recovery state

The pre-preservation worktree was not one finished feature. It contained 28
tracked changes and 24 untracked files. It is saved as recovery evidence and
must not be treated as a known-good release.

### 1. Practice generation recovery path

Paths:

- `deeptutor/agents/question/coordinator.py`
- `deeptutor/services/llm/factory.py`
- `deeptutor/services/llm/provider_core/openai_responses/converters.py`
- `scripts/benchmark_practice_generation_api.py`
- `tests/agents/question/test_model_routing.py`
- `tests/services/llm/test_openai_responses_converters.py`

Intent:

- Replace the large legacy question coordinator with a thin direct-template
  and set-generation path.
- Route quiz generation through a dedicated model override.
- Keep optional progressive starter/background batches.
- Normalize unsupported Responses API token-limit arguments.
- Benchmark Practice quizzes and Flashcards across Chat and Responses APIs.

Treatment:

- Preserve the behavioral requirements and benchmark cases.
- Do not transplant the coordinator into v1.5.2; upstream replaced the old
  question-agent implementation.

### 2. Prompt, session, and built-in-tool compatibility stubs

Paths:

- `deeptutor/services/prompt/__init__.py`
- `deeptutor/services/prompt/language.py`
- `deeptutor/services/session/__init__.py`
- `deeptutor/tools/builtin/__init__.py`

Intent:

- Keep import contracts alive while parts of the old implementation were
  absent from the checkout.
- Reduce the language helper and built-in tool registry to minimal exports
  needed by the recovered Practice path.

Risk and treatment:

- These are repair stubs, not product improvements.
- Never port the empty built-in tool registry or simplified compatibility
  modules over v1.5.2.

### 3. Restored upstream modules

Paths:

- `deeptutor/agents/co_writer/`
- `deeptutor/agents/guide/`
- `deeptutor/services/rag/pipelines/llamaindex.py`

Evidence:

- The file blobs match upstream DeepTutor commits from April 20-23, 2026.
- They were untracked in the TEEECHR checkout and appear to be restoration or
  cross-version recovery artifacts rather than original TEEECHR work.

Treatment:

- Preserve them in the safety snapshot for provenance.
- Do not port them; use the v1.5.2 Co-Writer, learning, and LlamaIndex modules.

### 4. Notebook prompt deletions

Paths:

- `deeptutor/agents/notebook/prompts/en/analysis_agent.yaml`
- `deeptutor/agents/notebook/prompts/en/summarize_agent.yaml`
- `deeptutor/agents/notebook/prompts/zh/analysis_agent.yaml`
- `deeptutor/agents/notebook/prompts/zh/summarize_agent.yaml`

Assessment:

- The working tree deletes the YAML prompts while notebook Python modules
  contain inline prompt text.
- No complete migration proof or targeted tests were found.

Treatment:

- Preserve as incomplete recovery state. Do not reproduce these deletions on
  v1.5.2 without proving the current prompt-loading contract.

### 5. TutorBot input-performance recovery

Paths:

- `web/app/(workspace)/agents/[botId]/chat/page.tsx`
- `web/components/chat/AtMentionPopup.tsx`

Intent and evidence:

- Colocate composer input state and extract the mention popup to reduce
  keystroke-driven full-page rerenders.
- File provenance matches upstream input-lag work from April 20-22, 2026.

Treatment:

- Preserve the performance goal. v1.5.2 replaced TutorBot with Partners and a
  newer chat surface, so validate current input performance before porting
  anything.

### 6. Incomplete frontend route and preview deletions

Paths:

- `web/app/(utility)/space/{chat-history,memory,notebooks,questions,skills}/page.tsx`
- `web/components/chat/preview/previewers/`

Assessment:

- The deleted Space files were small route wrappers.
- The deleted preview components are still imported by
  `FilePreviewDrawer.tsx` and `KbFilePreview.tsx`.
- Therefore this deletion set is incomplete and would break frontend module
  resolution/build behavior.

Treatment:

- Preserve only as recovery evidence. Do not port or describe it as a
  completed cleanup.

### 7. Working agreements

Path:

- `AGENTS.md`

Intent:

- Add DeepTutor-specific delegation lanes and parent-agent ownership rules.

Treatment:

- Preserve separately from implementation so workflow documentation does not
  disguise source changes.

## Product migration decision map

### Preserve and reimplement

- Dedicated Practice learner workflow
- Persistent quiz attempts, grading, progress, and remediation
- Saved Flashcard decks, reviews, restart, and completion summaries
- Code-entry private tester experience
- Quick learner replies and action chips
- First-useful-output and large-exam latency goals
- TEEECHR branding and focused navigation

### Replace with upstream v1.5.2 foundations

- Authentication, authorization, and per-user isolation
- Chat orchestration and WebSocket ownership
- Knowledge Base storage, registry, and retrieval engines
- Model/provider configuration
- Guided Learning and mastery primitives
- Same-origin web/backend routing and deployment foundations
- Co-Writer, Partners, and built-in tool registries

### Preserve as history only

- Old question coordinator implementation
- Tester-prefixed Knowledge Base names as the isolation mechanism
- Parallel tester-cookie ownership checks
- Build-time public API URL injection
- Compatibility stubs and incomplete frontend deletions

## Phase 1 exit contract

Phase 1 is complete only when:

1. The historical checkout is preserved on its safety branch with the recovery
   state explicitly labeled.
2. A separate worktree exists at the exact v1.5.2 commit.
3. The untouched upstream baseline has dependency, backend, and frontend test
   evidence, or each blocked check has a precise environment reason.
4. No TEEECHR product feature has been migrated and production has not been
   modified.
