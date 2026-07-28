# TEEECHR BlueWay Credential Authority and Recovery Runbook

Status: source implementation and provider-free tests are present on the Phase 3A
closeout branch. No hosted secret rotation, primary-grant mutation, live recovery,
deployment, or disposable-account proof is authorized by this document.

## Safety contract

- The current primary BlueWay grant is preserved until the owner explicitly
  approves recovery.
- TEEECHR never attempts sync, refresh, or Disconnect with an unreadable
  credential.
- An unreadable credential becomes the owner-scoped
  `credential_recovery_required` status. Its connection row, opaque external
  subject, Courses, sources, records, mappings, mastery, and sync history remain.
- Recovery must return the exact same opaque BlueWay subject. A grant for another
  BlueWay account is revoked and cannot inherit the retained Course workspace.
- The replacement credential is encrypted in a staging file, the unreadable
  envelope is moved into a private quarantine directory, and the same connection
  ID becomes healthy only after the database fence commits.
- A crash or database failure leaves the connection recovery-required. It never
  reports a replacement grant as active prematurely.
- Browser responses contain recovery metadata only. Keys, tokens, credential
  references, key IDs, file paths, and crypto diagnostics remain server-only.

## Persistent authority

The single-host beta stores one deployment authority at:

```text
data/system/integrations/blueway-secret-authority.json
```

The directory is `0700`; the file is `0600`. Reads reject symbolic links, hard
links, foreign ownership, non-regular files, permissive modes, malformed data, and
unknown schema. Creation is exclusive, fsynced, and never overwrites an existing
authority.

The authority contains the local AES-256 credential key and the local copy of the
BlueWay pairing API secret. The initial environment values are one-time bootstrap
candidates only. After successful bootstrap, restart must load the same authority
without those secret environment values.

Normal bootstrap is permitted only when every referenced legacy primary and
rotation envelope authenticates under the candidate AES key and no unreferenced
envelope remains:

```text
TEEECHR_INTEGRATION_SECRET_BOOTSTRAP=true
```

Recovery bootstrap is deliberately separate. It preserves unreadable envelopes
and installs new persistent authority only when an operator explicitly selects:

```text
TEEECHR_INTEGRATION_SECRET_RECOVERY_BOOTSTRAP=true
```

Never set both bootstrap modes. Supply secret values through the protected
single-host launcher, not an inline shell command, and remove the one-time secret
inputs and bootstrap flag after the authority is created.

## Approved recovery sequence

The steps below are gates, not a single blanket authorization.

1. Stop TEEECHR and snapshot the private runtime tree. Record hashes and modes for
   the authority path, owner credential envelope, and the owner's `courses.db`.
2. Confirm the target owner and connection are the primary connection to preserve.
   Do not call Sync or Disconnect.
3. Obtain separate action-time approval to rotate the hosted BlueWay pairing
   secret. Rotation and hosted deployment are not implied by source approval.
4. Configure the matching new pairing secret in the protected TEEECHR launcher.
   Select recovery bootstrap and either supply an explicit new 32-byte AES key or
   allow the recovery bootstrap to generate one.
5. Start one TEEECHR process. Confirm the authority file is private, then remove
   the bootstrap flag and secret environment inputs and restart once.
6. Confirm the owner sees `Credential recovery required`; all other TEEECHR
   features remain usable and no provider call or Course mutation occurred.
7. The owner selects **Reconnect BlueWay** and approves using the same BlueWay
   account. A different account must fail and its new grant must be revoked.
8. Confirm the same TEEECHR connection ID is healthy. Compare retained Course,
   source, mapping, record, mastery, and history identities to the preflight
   snapshot.
9. Only after recovery succeeds, run one bounded sync and verify its durable
   receipt. Do not use the primary account for destructive Disconnect proof.
10. Create and use a disposable second BlueWay account for two-owner browser
    isolation and disposable Disconnect/reconnect proof.

## Disposable Owner B constraint

The released BlueWay client authenticates through native Sign in with Apple. It
does not expose email/password, magic-link, or browser OAuth sign-in. Therefore a
Supabase-admin-created email user would not be a valid BlueWay app user and must
not be used as Alice/Bob proof.

Owner B requires a distinct Apple identity on a second physical iPhone with
TestFlight access to the reviewed BlueWay build. Do not sign the primary phone out
of its Apple account to simulate Owner B. Account creation alone does not submit
audio or spend transcription budget, but it does create the normal beta enrollment
row; recording and transcription must remain out of this proof.

## Failure handling

- Missing or unsafe persistent authority: BlueWay returns unavailable; generic
  TEEECHR remains available.
- Unreadable owner envelope: the database increments its revision and generation,
  cancels active BlueWay work, clears any rotation receipt, and records recovery
  required. Imported Course data remains available.
- Provider approval still pending: polling remains pending and commits nothing.
- Wrong BlueWay subject: revoke the newly issued grant and keep recovery required.
- Staging or database failure: revoke the new grant when possible, keep recovery
  required, and retain the old envelope in private quarantine.
- Hosted or network failure before owner approval: keep the primary grant and local
  data untouched.

Do not delete the authority, credential envelopes, quarantine, database rows, or
imported Course material as rollback. Disable the optional BlueWay integration and
preserve evidence for review.

## Proof still required

- Real persistent-authority startup/restart on the authoritative runtime.
- Hosted pairing-secret rotation under separate approval.
- Primary same-account owner recovery without changing Course/source identities.
- One disposable second BlueWay account.
- Current Alice/Bob browser isolation across both applications.
- Disposable Disconnect/reconnect and reviewed fixture retirement.
- Final Phase 3A closeout backcheck, reviewed commit, and publication decision.

## Local source proof captured on 2026-07-27

- Full Python suite with auth forced to its default-disabled test mode and all
  known paid-provider keys removed: `2877 passed, 6 skipped`.
- Focused recovery and affected identity/runtime suites: pass.
- Web node suite: `168 passed`; TypeScript and production build: pass.
- Ruff over every affected Python surface: pass.
- Web lint: no errors; `104` literal-copy warnings remain, including the new
  recovery copy. Moving the complete Settings page into translation catalogs is
  parked as UI localization work rather than widening this security repair.
- Secret-pattern scan over the intended recovery diff: no match.
- Independent security/diff review: no remaining P0, P1, or P2 finding.

This is source and provider-free test proof. It does not prove persistent
authority on the real runtime, a hosted secret rotation, a live replacement
grant, browser recovery, a second owner, deployment, or release publication.
