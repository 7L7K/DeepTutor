# TEEECHR v1.5.2 Phase 3A — Real Transcript CourseSource Receipt

Status: **content-free proof receipt**

Observed at: `2026-07-28T02:28:10.595958+00:00`

TEEECHR runtime source: `bd6c117e`

BlueWay proof source: isolated worktree
`/Users/home/Desktop/2k26/teeech/BlueWay-phase3a-transcript-proof` at
`1752e5f`

## Claim

One previously completed, owner-approved real BlueWay export reached the exact
private TEEECHR CourseSources, retained non-empty transcript segments, survived
process shutdown and restart, and remained retrievable only through an
owner-authorized Course Knowledge reference.

This tracked receipt contains no transcript text or raw identity. No per-user,
Course, source, Knowledge-reference, bundle-content, transcript-content, or
bearer fingerprint entered the tracked receipt. The published
evidence-artifact and verifier SHA-256 values are reproducibility checksums
only.

## Hosted BlueWay observation

- Completed transcripts: `9`
- Completed transcripts with non-empty segments: `7`
- Valid completed no-speech transcripts with zero segments: `2`
- Latest completed transcript:
  `2026-07-25T04:57:01.176211+00:00`

The query returned aggregate counts only. It did not retrieve transcript text or
reusable identifiers.

## Persisted TEEECHR observation

The same owner-bound connection has:

- Completed sync runs: `1`
- Latest completed sync:
  `2026-07-27T05:22:30.237073+00:00`
- Course mappings: `5`
- Current ready CourseSources: `5`
- Current records:
  - assignments: `2`
  - capture metadata: `22`
  - class meetings: `5`
  - class notes: `1`
  - transcripts: `7`

Across the exact current Course bundles:

- all `5` current bundle files exist;
- every manifest SHA-256 and CourseSource content SHA-256 matches its bundle
  bytes;
- all `5` deterministic indexes exist and are non-empty;
- `2` CourseSources contain the `7` transcript records;
- the transcript records contain `10` non-empty segments;
- no raw-audio, provider-ID, storage-path, or location authority crossed the
  boundary.

## Post-restart citation receipt

The local backend and frontend were restarted from `bd6c117e` with BlueWay
networking explicitly disabled and the deterministic Course provider enabled.
No export, credential refresh, LLM, embedding, transcription, deployment, or
paid-provider call occurred.

One exact real transcript CourseSource produced this tracked, content-free
summary:

```json
{
  "bundle_hash_matches": true,
  "citation": {
    "path": "blueway-course-bundle.json",
    "reference_hash_matches": true,
    "type": "knowledge_base"
  },
  "course_identity_bound": true,
  "foreign_profile_denied": true,
  "nonempty_segment_count": 8,
  "owning_profile_authorized": true,
  "source_identity_bound": true,
  "source_revision": 2,
  "transcript_content_logged": false
}
```

The citation content event was intentionally not recorded because it contains
private transcript text.

### Private reproducibility anchor

The exact hashed designations are retained outside Git in the owner-private
`0600` artifact
`/Users/home/Desktop/2k26/teeech/.phase3a-private-evidence/real_transcript_receipt_private.json`.
Its SHA-256 is
`a5e017f5ebf42c5fbbaf4117b4344e45a37def5b6fc015dedb4a251b0b86ad81`.

The read-only verifier is
`/Users/home/Desktop/2k26/teeech/.phase3a-private-evidence/verify_real_transcript_receipt.py`
with SHA-256
`c146b99d7a2883effc239149f97edbfe80250bb322380a1b805cbda642419708`.
It was run against source revision `bd6c117e` with all TEEECHR BlueWay
integration and paid-provider environment variables explicitly unset:

```text
env -u TEEECHR_BLUEWAY_INTEGRATION_ENABLED \
  -u TEEECHR_BLUEWAY_BASE_URL -u TEEECHR_BLUEWAY_CLIENT_ID \
  -u TEEECHR_BLUEWAY_API_SECRET -u TEEECHR_BLUEWAY_APPROVAL_URL \
  -u TEEECHR_INTEGRATION_MASTER_KEY -u OPENAI_API_KEY \
  -u ASSEMBLYAI_API_KEY ./.venv/bin/python \
  /Users/home/Desktop/2k26/teeech/.phase3a-private-evidence/verify_real_transcript_receipt.py \
  --repo /Users/home/Desktop/2k26/teeech/DeepTutor-v1.5.2-baseline
```

The verifier opens each Course database in SQLite read-only mode, selects the
retained non-empty transcript CourseSource deterministically, matches its
revision-`2` bundle fingerprint and index, invokes the deterministic Course
provider under the owning profile, and repeats the same Knowledge reference
under a different profile to prove that no source citation is returned. It never
prints a content event.

## Separate operational blocker

This receipt validates the historical real transfer and its persistent
CourseSource/citation boundary. It does not claim the delegated connection is
currently operable.

The prior launcher kept the local TEEECHR AES master key and its local copy of
the matching pairing API secret only in process environment. That process is
gone, so the old encrypted credential cannot be decrypted for another sync or
server-initiated revoke. The hosted pairing secret still exists but is not
retrievable; replacing it remains a separate explicitly approved rotation
action. Do not use the current Disconnect action with a replacement key: its
present ordering can fence the local connection before decryption fails.

Phase 3A therefore remains open for persistent secret authority,
credential-loss recovery, two-account browser isolation, and disposable
disconnect/reconnect proof.
