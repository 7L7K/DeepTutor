# TEEECHR v1.5.7 Integration Beta Certification

Date: 2026-08-01
Status: `PASS_WITH_PARKED_FOLLOWUPS`
Branch: `feature/teeechr-v157-integration`
Integration commit: `c55d1e1a58c73f042794c00b7da182ff63090710`
Upstream parent: DeepTutor `v1.5.7` / `740ec413a0ce56145ef02d63e181715d207b8b11`
TEEECHR parent: `b8130e7f`

## Certification claim

The upstream-based integration branch is qualified for a bounded local beta
review. It preserves the reviewed TEEECHR identity, private Course, BlueWay,
Practice, Flashcard, learning, provider-accounting, and learner-action
contracts while incorporating DeepTutor v1.5.7.

This is a source, automated-test, disposable-database, supported-runtime,
production-build, and local authenticated-browser claim. It is not a hosted,
deployed, packaged-device, paid-provider, historical-data-migration, or
canonical-main claim.

## Authority receipt

- The integration branch was created from `origin/main` at `740ec413`.
- The two-parent merge retained the complete upstream and TEEECHR histories.
- The merge resolved the eight predicted textual conflicts and semantically
  reviewed the overlapping identity, path, session, provider, Knowledge, and
  frontend surfaces.
- The review snapshot is published only as
  `fork/feature/teeechr-v157-integration`.
- `origin/main` remains `740ec413`.
- `fork/main` remains `e991e79f`.
- Neither main branch was moved by this work.

## Automated qualification

All runs were provider-free and used deterministic local adapters or fakes.

| Surface | Result |
| --- | ---: |
| Identity, sessions, and provider contracts | 113 passed |
| Course foundation and ownership | 110 passed |
| Practice and Flashcards | 218 passed |
| BlueWay hermetic integration | 79 passed |
| Learning and mastery | 245 passed |
| Migration and package replay | 23 passed |
| Frontend Node tests | 416 passed |
| TypeScript | passed |
| Diff and secret checks | passed |

The database proof includes disposable fresh replay and migration-order
validation. It does not alter a learner database or a hosted BlueWay project.

## Authenticated browser qualification

The hermetic browser campaign passed under the supported bundled Node 24
runtime. It proved:

- two authenticated learners create and retain separate private Course loops;
- identity, quiz, learning, and cache isolation survive a server restart;
- manual Practice and Flashcards remain usable with providers disabled;
- the study-first Flashcard shell keeps provider machinery out of the learner
  journey;
- grounded Flashcard generation moves through review into a usable card;
- a published deck survives restart;
- General Chat can create conversation-drafted Flashcards;
- grounded Practice survives reload and retains citations;
- multiple Course sources and the manual fallback remain usable; and
- Course Chat opens an editable Practice plan.

The first cold browser run found a real hydration race: the server-rendered
login shell could be clicked before its client submit handler existed. The E2E
helpers now wait for the authenticated status request that marks hydration and
for navigation away from `/login` before continuing. The complete campaign
then passed.

## Startup, shutdown, and build qualification

- Node 22 and Node 24 are the supported web development/build runtimes.
- Unsupported Node 26 fails before package-manager or metadata mutation.
- A cold Node 24 development start became ready, served `/login` with HTTP 200,
  and stopped cleanly.
- A Node 24 production build compiled successfully, type-checked, generated all
  60 routes, and exited normally.
- `package.json` and `package-lock.json` remained unchanged.
- Next.js `next-env.d.ts` is generated differently by development and
  production. It is therefore ignored and removed from version control so
  ordinary supported startup/build operations cannot dirty the repository.

## Beta operating policy

- One persistent single-host server remains the supported beta topology.
- Every learner, including an administrator, retains a separate immutable-user
  Course workspace.
- Course removal remains archive/restore only.
- Provider calls are disabled by default. Paid Chat, Practice, or Flashcard use
  requires the existing explicit server policy, encrypted credential, budget,
  reservation, and receipt gates.
- BlueWay is read-only from TEEECHR. No BlueWay write-back is authorized.

## Parked release gates

The following are not defects in the local integration claim, but they remain
required before a broader production release:

1. review and explicitly decide whether to merge the integration branch into a
   canonical TEEECHR main branch;
2. run the final real two-owner Apple/BlueWay certification or retain it as a
   clearly disclosed parked beta risk;
3. qualify production secrets, hosted migrations, domains, Origin rules, and
   deployment configuration in the actual target environment;
4. produce and test the intended packaged/release artifact;
5. run the reviewed historical learner-data migration dry run before importing
   any legacy record; and
6. re-run the appropriate qualification when upstream moves beyond v1.5.7.

## Decision

The local v1.5.7 integration is acceptable as the next TEEECHR beta review
snapshot. Keep the release and canonical-main gates closed until the parked
items receive their own authority and evidence.
