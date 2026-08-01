# TEEECHR v1.5.7 Upstream Divergence Inventory

Date: 2026-08-01
Mode: read-only repository analysis
TEEECHR checkout: `DeepTutor-v1.5.2-baseline`
TEEECHR branch: `feature/teeechr-v152-phase5-course-study-intelligence`
TEEECHR reviewed snapshot: `762ccc3982183354e26107860a87a3973607eae1`
TEEECHR remote snapshot: `fork/feature/teeechr-v152-phase5-course-study-intelligence`
Upstream authority: `origin/main` at `740ec413a0ce56145ef02d63e181715d207b8b11`
Upstream release: `v1.5.7`
Shared v1.5.2 base: `b728354863540466f5410bec3530eb55a9fe0edc`

## Scope and non-goals

This inventory refreshes the moving-upstream evidence before an integration
branch exists. It does not merge, cherry-pick, deploy, migrate learner data,
change BlueWay, invoke a provider, or modify either `main` branch.

The historical fork main is a separate authority. `fork/main` remains at
`e991e79f`; it is not the destination for an automatic merge and is not treated
as the current upstream foundation.

## Divergence receipt

| Measure | Fresh result |
| --- | ---: |
| Upstream-only commits, `origin/main...TEEECHR` | 98 |
| TEEECHR-only commits, `origin/main...TEEECHR` | 75 |
| Shared base | `b7283548` |
| Paths changed upstream since the base | 408 |
| Paths changed by TEEECHR since the base | 280 |
| Paths changed on both sides | 33 |
| Predicted textual conflicts from `git merge-tree --write-tree` | 8 |

The eight predicted textual conflicts are:

1. `README.md`
2. `deeptutor/agents/chat/agentic_pipeline.py`
3. `deeptutor/multi_user/paths.py`
4. `deeptutor/services/config/model_catalog.py`
5. `deeptutor/services/session/turn_runtime.py`
6. `tests/services/test_model_catalog.py`
7. `web/app/(workspace)/home/[[...sessionId]]/page.tsx`
8. `web/context/UnifiedChatContext.tsx`

Textual auto-merge is not semantic approval. The other 25 overlapping paths
include authentication, Knowledge, PathService, session stores, settings,
provider runtime, Chat UI, and tests; each remains a mandatory review surface.

## Upstream changes that materially affect integration

Upstream v1.5.3 through v1.5.7 added or repaired behavior that TEEECHR should
reuse unless it violates an explicit private-Course invariant:

- RAG coexistence with exclusive Knowledge capabilities and citations grounded
  in actual retrieval results.
- Knowledge file-inventory answers and Tencent IMA connected Knowledge.
- Buffered session-event commits and removal of the post-stream generating
  stall.
- Unique optimistic Chat message IDs and prevention of sends during streaming.
- Turn-scoped streaming quiz cards.
- Generated-file collection in the Chat activity panel.
- First-party OpenAI Codex OAuth and corrected OAuth callback routing.
- Composer-focus preservation and scrolling fixes.
- Source-launcher `npm ci` recovery when `node_modules` is missing.
- Additional provider, embedding, localization, packaging, and release fixes.

Upstream did not add TEEECHR's authenticated Course entity, Course-scoped
sources, BlueWay delegation, Course Practice/Flashcards, grading/mastery
evidence, General Study, or the shared paid-use ledger. Those remain TEEECHR
contracts that must survive integration.

## Overlap classification

### A. Identity, paths, and private storage — highest authority risk

| Path | Upstream contribution | TEEECHR authority that must survive | Integration disposition |
| --- | --- | --- | --- |
| `deeptutor/api/routers/auth.py` | Codex OAuth callback/state changes | current-account revalidation, immediate disable/demotion enforcement | Reconcile; upstream OAuth routing cannot weaken account authority |
| `deeptutor/multi_user/paths.py` | new upstream path/service layout | strict role-independent personal Course workspace, no admin fallback | Manual conflict resolution with owner-isolation tests |
| `deeptutor/services/path_service.py` | upstream path additions | immutable-user personal resolver and separate global namespace | Reconcile and prove two-admin separation |
| `deeptutor/multi_user/knowledge_access.py` | Knowledge inventory behavior | Course-managed Knowledge derived from authenticated ownership | Reconcile; client KB names remain non-authoritative |
| `deeptutor/services/session/pocketbase_store.py` | post-stream/session performance changes | Phase 2 rejects PocketBase for Course authority | Reuse generic fixes; retain Course startup/API rejection |

### B. Chat, sessions, WebSockets, and Course provenance — high risk

| Path | Upstream contribution | TEEECHR authority that must survive | Integration disposition |
| --- | --- | --- | --- |
| `deeptutor/agents/chat/agent_loop.py` | DSML parsing | Course resolver and permitted source boundary | Auto-merge plus focused semantic review |
| `deeptutor/agents/chat/agentic_pipeline.py` | RAG coexistence and Knowledge inventory | Course-only source derivation and provenance | Manual conflict resolution; compose both behaviors |
| `deeptutor/api/main.py` | new routers/runtime wiring | Course/Practice/Flashcard/BlueWay routers and Origin checks | Auto-merge plus route inventory proof |
| `deeptutor/services/session/protocol.py` | post-stream state protocol | immutable session-to-Course binding | Reconcile protocol fields without optionalizing Course authority |
| `deeptutor/services/session/sqlite_store.py` | event batching and turn-scoped quiz fixes | durable `course_id` and provenance metadata | Reconcile migrations and replay behavior |
| `deeptutor/services/session/turn_runtime.py` | batching, generated files, stall repair | re-resolved owner/Course/source authority for every command and commit | Manual conflict resolution with HTTP/WS lifecycle tests |
| `tests/api/test_unified_ws_turn_runtime.py` | upstream runtime regressions | foreign session/Course and reconnect/cancel/resume denial | Preserve both test families |

### C. Provider, model, settings, and spend authority — high risk

| Path | Upstream contribution | TEEECHR authority that must survive | Integration disposition |
| --- | --- | --- | --- |
| `deeptutor/services/config/model_catalog.py` | Codex OAuth provider catalog | typed Luna bindings, requested/actual model receipts, dormant rollback | Manual conflict resolution; central registry remains sole identity authority |
| `deeptutor/services/config/provider_runtime.py` | embedding/provider routing fixes | encrypted dedicated study credential and fail-closed provider resolution | Reconcile without fallback to env/client authority |
| `deeptutor/core/agentic/client.py` | Codex provider parameters | normalized model/reasoning/store behavior | Reconcile and rerun provider-kwargs tests |
| `deeptutor/api/routers/settings.py` | Codex OAuth and code-theme settings | protected credential and usage-policy controls | Reconcile routes and redact all credential surfaces |
| `tests/services/test_model_catalog.py` | upstream provider coverage | Luna registry and rollback proof | Manual test merge; no authority by display name |
| `tests/services/config/test_provider_runtime.py` | upstream runtime coverage | study binding and accounting failure boundaries | Preserve both suites |

### D. Knowledge and settings APIs — medium/high risk

| Path | Upstream contribution | TEEECHR authority that must survive | Integration disposition |
| --- | --- | --- | --- |
| `deeptutor/api/routers/knowledge.py` | Tencent IMA and inventory work | owner-scoped Course managed KB and source lifecycle | Reconcile; foreign IDs remain indistinguishable 404 |
| `tests/api/test_settings_router.py` | new settings tests | credential redaction and runtime-policy tests | Preserve both suites |
| `deeptutor/runtime/registry/tool_registry.py` | upstream tool adjustments | Course-mode generic-resource restrictions | Auto-merge plus capability review |

### E. Frontend Chat, Course shell, and caches — high learner-risk

| Path | Upstream contribution | TEEECHR authority that must survive | Integration disposition |
| --- | --- | --- | --- |
| `web/app/(workspace)/home/[[...sessionId]]/page.tsx` | upstream workspace evolution | General Chat/Course mode, active Course selector, action handoffs | Manual conflict resolution and authenticated browser proof |
| `web/context/UnifiedChatContext.tsx` | unique optimistic IDs and stall fixes | immutable session/Course binding and identity/request epochs | Manual conflict resolution; preserve both concurrency protections |
| `web/components/chat/home/ChatComposer.tsx` | send-lock and focus fixes | Course sources-only presentation and learner actions | Reconcile and retain focus/accessibility behavior |
| `web/components/chat/home/ChatMessages.tsx` | turn-scoped quiz behavior | Make Flashcards/Quiz me actions and safe provenance labels | Reconcile without leaking foreign or internal IDs |
| `web/components/sidebar/SidebarShell.tsx` | upstream navigation changes | Practice, Flashcards, Courses, BlueWay settings | Reconcile navigation without deleting upstream tools prematurely |
| `web/lib/settings-nav.ts` | upstream settings navigation | BlueWay and provider-policy entries | Reconcile and prove capability gates |

### F. Packaging and runtime metadata — medium risk

| Path | Required treatment |
| --- | --- |
| `pyproject.toml` and `packaging/deeptutor-cli/pyproject.toml` | Begin from v1.5.7 packaging and reapply only TEEECHR dependencies/entry points that remain necessary |
| `web/package.json` and `web/package-lock.json` | Begin from v1.5.7 dependencies, retain evidenced Node 22/24 startup/build guards, run `npm ci`, tests, and build |
| `README.md` | Preserve upstream release documentation and add only current TEEECHR source-runtime guidance |

## Non-overlapping TEEECHR surfaces

The majority of TEEECHR product code does not overlap upstream textually.
Course repositories and migrations, BlueWay integration modules, Practice,
Flashcards, grading/mastery evidence, qualification artifacts, and TEEECHR
closeout documents can be carried into the v1.5.7 integration branch without
inventing new behavior. They still require import, router, migration-order,
schema, and end-to-end validation against the new base.

## Inventory verdict

`PASS_WITH_PARKED_FOLLOWUPS`

The upstream authority and finite overlap set are now proven. No integration
mutation has occurred. The next lane is the version-specific v1.5.7 integration
plan and a separate integration branch created from `origin/main` only after
that plan is reviewed.
