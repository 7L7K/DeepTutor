# BlueWay / TEEECHR Product Boundary Correction

Status: accepted for Vertical Slice B1 planning
Date: 2026-08-07
Branch: `feature/teeechr-web-course-hub-slice-b1`

## Decision

The web Course Hub belongs to TEEECHR. BlueWay is the academic-life and
Course-entry product; it is not the full learning workspace. The previous plan
that placed a complete Course workspace inside BlueWay is **SUPERSEDED**.

This correction is a product-boundary decision, not a request to rewrite the
database, restart migrations, add BlueWay launch/SSO, or change hosted
integration authority.

## BlueWay owns

BlueWay is the academic-life surface for:

- classes and academic identity;
- schedule and academic context;
- assignments, recordings, notes, and places;
- entering or linking to an academic Course when a learner chooses to study.

BlueWay may retain a small, bounded TEEECHR connection or launch surface. It
does not own the learner's complete Course learning workspace, study state, or
learning navigation.

BlueWay remains read-only from the TEEECHR Course boundary unless a later,
separately approved integration contract says otherwise. No B1 work adds
BlueWay launch/SSO or BlueWay write-back.

## TEEECHR web owns

The authenticated TEEECHR web product owns the learner's private Course
workspace and its learning navigation:

1. Classes Home;
2. Course Overview;
3. Materials;
4. Practice;
5. Review;
6. Chat, only when its authorization contract is green;
7. later Progress and Study Sessions.

Course title, term identity, ownership, isolation, sources, practice state,
review state, and chat state remain Course-owned TEEECHR data. The B1 Course
Hub must use the existing owner-private Course APIs and truthful null states;
it must not fabricate progress, recommendations, or a timeline.

## Superseded plan

The old BlueWay-hosted Course workspace plan is marked **SUPERSEDED**. It must
not be used as the B1 route, navigation, or ownership authority. Existing
historical planning material remains available for provenance, but it is not an
implementation instruction for this branch.

The current implementation boundary is aligned with the existing Course
contracts and the local runtime instructions in
`/Users/home/Desktop/2k26/TEEECHR_BLUEWAY_COMPLETE_DOCUMENTATION/START_HERE_TO_BUILD.md`.

## Non-goals for B1

- BlueWay launch or SSO;
- syllabus parsing or Course timeline intelligence;
- Study Sessions;
- recommendation engine;
- Progress redesign;
- hosted deployment or production configuration;
- migration SQL changes.

## Proof boundary

Source and test evidence can establish the Course ownership and route contract.
They do not establish hosted Supabase Edge behavior, a physical iPhone,
TestFlight, production secrets, accessibility certification, or release and
rollback readiness. Those remain separate later gates.
