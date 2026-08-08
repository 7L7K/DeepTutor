# Vertical Slice C2 — Course Learning Loop Implementation Receipt

## Status

```text
SOURCE / TEST / BUILD PROVEN
BROWSER RUNTIME PROVEN — authenticated local runtime only
HOSTED / DEVICE / RELEASE OPEN
```

C2 is complete for the bounded local Course learning loop. The slice does not
claim hosted Supabase/provider, physical-device, TestFlight, production-secret,
or release proof.

## Repository and runtime

```text
Worktree: /Users/home/Desktop/2k26/teeech/DeepTutor-course-learning-loop-c2
Branch: feature/teeechr-course-learning-loop-c2
Base: d9faa6446490ccc228547219358752ebc3529340
Final source head before this receipt: 08c0d809
Node: v22.23.2 (/opt/homebrew/opt/node@22/bin)
npm: 10.9.8
Python: 3.11.15
Python environment: /Users/home/.codex/runtimes/teeechr-b1-python311
Backend: 127.0.0.1:8045, DEEPTUTOR_HOME=/tmp/teeechr-c2-browser.R3xmLy
Frontend: http://localhost:3825
Provider mode: deterministic local test provider
```

The local backend was started with `AUTH_ENABLED=true`, an isolated
`DEEPTUTOR_HOME`, and no hosted environment or production secret.

## Fixture identity and authoritative records

```text
User A: c2_alice / u_514ad1c6b9d54054905310e13aac20aa
User B: c2_bob / u_cc8360be1b244f6ca9c968c239b451a7
User C: c2_carol / u_54b52e15cb504ea087ab9b0ad889923a7

User A Course: Biology 101 / fall-2026
Course: crs_5eed00ef127f446082ccaadf81263f41
Ready source: src_4451ae7e7399487db2f47409c11a761b
Ready revision: 2; source hash: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
Failed source: src_20350bf0df8147a18834da6a42027db4
Practice set: prc_7de79a91b080461781cb9a377e24346b
Ready Practice revision: prv_5e31cb9489b34b89b376a29f951f6830
Attempt: att_2cfbb798c5a44c6299f1261bcbdc4173
Review generation operation: ofg_2488292685e2407283107329b2f6afd7
Approved Review deck: dck_1680ade31db6495ab0deb1fb7ec13db6
```

The Attempt is owner-, Course-, Practice-set-, and revision-bound. Its final
server receipt is `graded`, with `3` correct out of `5`; the first two items
are misses and the remaining three are correct. The Review operation is
`practice_remediation`, contains eight candidates, and retains the Attempt,
Practice revision, two missed question IDs, and their grading evidence IDs.
The approved deck is `ready` with eight cards.

Durable JSON receipts are in
`docs/verification/2026-08-08-teeechr-c2-browser/backend/`, including
`attempt.json`, `practice-revision.json`, `results.json`,
`flashcard-generation-operations.json`, and `campaign-summary.json`.

## Browser routes and proof

The authenticated local campaign exercised:

```text
/classes
/classes/crs_5eed00ef127f446082ccaadf81263f41
/classes/crs_5eed00ef127f446082ccaadf81263f41/chat
/classes/crs_5eed00ef127f446082ccaadf81263f41/practice
/classes/crs_5eed00ef127f446082ccaadf81263f41/practice/prc_7de79a91b080461781cb9a377e24346b/attempts/att_2cfbb798c5a44c6299f1261bcbdc4173
/classes/crs_5eed00ef127f446082ccaadf81263f41/review
/classes/crs_5eed00ef127f446082ccaadf81263f41/materials
```

Observed sequence:

1. Alice opened Biology 101 and received a supported grounded Course Chat
   answer. `Quiz me` was visible only after the persisted supported turn was
   present.
2. `Quiz me` opened the Course Practice plan, created one persistent Practice
   set and five-question ready revision, and landed on the exact nested
   Course/Practice/Attempt route.
3. Alice entered two wrong answers and three correct answers. The UI displayed
   save state, then a refresh reopened the same Attempt with the first three
   answers retained. The final Attempt was submitted and graded.
4. Results displayed `3 correct out of 5`, two `Needs review` items, and the
   cited `Biology energy notes.txt` source for each question.
5. `Make Flashcards from misses` opened the same Course Review route. The
   generation operation first displayed a candidate review state; it did not
   auto-publish. Alice approved the eight-card proposal and the same Course
   Review showed the ready deck.
6. The nested Attempt URL was reopened directly after completion and returned
   the same Course-bound Results. The Course Hub was reopened afterward.

Responsive and state captures are archived in
`docs/verification/2026-08-08-teeechr-c2-browser/screenshots/`:

```text
desktop-course-hub.png
desktop-review-approved.png
desktop-unauthorized-course.png
desktop-zero-course.png
mobile-classes-course-card.png
mobile-course-hub.png
mobile-materials-source-states.png
mobile-results-3-of-5.png
mobile-review-approved.png
```

The mobile captures use an explicit 390×844 viewport. The Materials capture
shows the ready Biology source and the failed `Pending lab worksheet.pdf`
state, with the attach-source control available. The Course Hub capture shows
the human-readable `Fall 2026` label and stable Materials, Practice, Review,
and Course Chat destinations. A keyboard focus pass reached the Course Hub
`Back to Classes` link and the route exposes labeled links/buttons; the active
focus marker is retained in the browser DOM snapshot used for the campaign.

User B’s direct request for Alice’s Course returned HTTP 404 and the browser
rendered `Course resource not found`. User C’s `/classes` returned an empty
Course list and the truthful `No Classes yet` state. No foreign Course or
Attempt data was displayed.

The `/classes` performance check is archived at
`docs/verification/2026-08-08-teeechr-c2-browser/performance-check.txt`.
`CourseContext.loadForIdentity` calls the owner-scoped `listCourses()` summary
once; `ClassesHome` does not issue per-Course source, readiness, or provider
calls, and `CourseRepository.list_courses` executes one owner-scoped Course
SELECT. The IAB campaign did not expose a low-level network-event listener, so
this is source-backed request-shape evidence plus the live `/classes` render,
not a packet capture of every browser request.

## Verification commands and outputs

```text
/Users/home/.codex/runtimes/teeechr-b1-python311/bin/python -m pytest -n 4 --dist loadfile -q tests
3887 passed, 8 skipped, 34 warnings in 193.28s

PATH=/opt/homebrew/opt/node@22/bin:$PATH npm run test:node
431 passed, 0 failed

PATH=/opt/homebrew/opt/node@22/bin:$PATH npm run lint
0 errors, 243 warnings

PATH=/opt/homebrew/opt/node@22/bin:$PATH npx tsc --noEmit
passed

PATH=/opt/homebrew/opt/node@22/bin:$PATH npm run build
passed; Next.js compiled the Course Hub, Materials, Chat, Practice,
Course/Practice/Attempt, and Review routes
```

`pytest-xdist` was installed only in the external Python environment. The
repository lockfile, migrations, hosted environments, and production
configuration were not changed.

## Commits

```text
79017cc1 docs(c2): record Course learning-loop packet
6640e6dd test(c2): lock Chat-to-Practice learning-loop contracts
90965962 feat(practice): create Course Practice from grounded Chat turns
3c99ae54 feat(results): connect grading Results to targeted remediation
fdd4069a feat(web): complete the Course learning loop
7b48e323 test(c2): align authority proof with grounded Chat admission
71b58bde fix(c2): persist supported Course Chat lifecycle evidence
a2849adc fix(c2): honor requested deterministic Practice item count
08c0d809 fix(web): keep generated Attempts Course scoped
```

The final documentation closeout commit will add this receipt and the
targeted `docs/verification/2026-08-08-teeechr-c2-browser/**` evidence tree
only. Because the repository ignores `/docs/*`, those exact documentation
paths must be added with `git add -f`; the entire ignored docs tree must not be
force-added.

## Push state and remaining proof

The only permitted publication target is:

```text
fork/feature/teeechr-course-learning-loop-c2
```

No `origin` push, merge, BlueWay change, C1 change, frozen migration change,
hosted deployment, or production-secret change is part of C2. The final
receipt commit hash and push result are to be appended here after the targeted
docs-only closeout.
