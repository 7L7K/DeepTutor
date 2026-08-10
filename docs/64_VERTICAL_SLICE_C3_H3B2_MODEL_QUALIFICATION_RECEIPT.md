# Vertical Slice C3-H3B2 Model Qualification Receipt

Status: OBJ-RESP-02 AND OBJ-RESP-03 MODEL-QUALIFIED / C3 OBJECTIVE QUALIFICATION 3/3 / HUMAN REVIEW NOT REQUIRED FOR H3B / FIVE-QUESTION CAMPAIGN CLOSED / PRIVATE BETA BLOCKED

Branch: `feature/teeechr-content-quality-c3-h3`

Implementation freeze: `b53a9f91`

## Decision

The fresh generation-only v4 contract campaign qualified both remaining C3
objectives. `OBJ-RESP-01` remains the H3B-1 human-qualified objective. The
machine qualification snapshot is:

| Objective | Status | Contract | Candidate | Independent judges |
| --- | --- | --- | --- | --- |
| `OBJ-RESP-01` | `HUMAN_QUALIFIED` | `ac_resp_01_transition_v1` | H3B-1 immutable successor | Historical King review plus deterministic runtime |
| `OBJ-RESP-02` | `MODEL_QUALIFIED` | `ac_resp_02_causal_role_v4_generation` | 1/3, deterministic pass | 2/2 `QUALIFY` |
| `OBJ-RESP-03` | `MODEL_QUALIFIED` | `ac_resp_03_bounded_contrast_v4_generation` | 1/3, deterministic pass | 2/2 `QUALIFY` |

`MODEL_QUALIFIED` means that the candidate passed the deterministic publication
fence and two independent blinded Luna judges. It does not mean independently
human-reviewed, student-tested, or approved for production publication.

The earlier v2 stop remains immutable in
`docs/63_VERTICAL_SLICE_C3_H3_MODEL_QUALIFICATION_RECEIPT.md` and its v2
artifacts. This receipt records a new versioned contract and a new campaign; it
does not relabel v2 failures as passes.

## Frozen generation-only contract

The active contract is:

`evals/reference_course/assessment_contracts_v4_generation_only.json`

SHA-256: `a5b2eb9787c8f56b0a7a5f733584048960af7314b20563db9e9c5cd9b4b90895`

It explicitly supersedes the v3 evaluation-only contract for this generation
campaign. It does not contain manually authored golden options. The option
word-count rule is `maximum_word_count_delta: 3`, a versioned contract change,
not a silent relaxation of v2.

The learner-text policy rejects opaque identifiers in prompts, options,
explanations, learner answers, and hints. The forbidden families are
`ev_*`, `src_*`, `qst_*`, `grd_*`, `prv_*`, `prc_*`, `ati_*`, and
`OBJ-RESP-*`. Evidence IDs remain allowed only in machine citation metadata.

## Provider campaign

Campaign artifact root:

`docs/verification/2026-08-09-teeechr-c3-h3-model-qualification-v4-delta3/`

Campaign summary SHA-256:
`6e163fc7a27552a354e8885a590b4998d34bd62d008ca6d05533984d604ec1c2`

| Field | Result |
| --- | --- |
| Campaign | `2026-08-09-teeechr-c3-h3-model-qualification-v4-delta3` |
| Requested model | `gpt-5.6-luna` |
| Actual model | `gpt-5.6-luna` |
| Reasoning | `high` |
| Storage | `store=false` |
| Provider | OpenAI Responses API |
| New settled spend | `7106` micro-USD (`$0.007106`) |
| Cumulative settled spend | `19370` micro-USD (`$0.019370`) |
| Cumulative uncertain reservation | `9105` micro-USD (`$0.009105`) |
| Cumulative admitted ledger spend | `28475` micro-USD (`$0.028475`) |
| Remaining under `500000` micro-USD cap | `471525` micro-USD |
| Candidate limit | 3 per objective |
| Candidates used | 1 for `OBJ-RESP-02`; 1 for `OBJ-RESP-03` |
| Judge policy | 2 independent judges per candidate |
| Tie-break judges | 0 |
| Automatic generation retries | 0 |
| Transport failures | 0 |

The sibling checkout credential was loaded only inside the process. It was not
printed, copied, persisted, or committed. No `gpt-5-mini` request was made.

Generation request receipts:

- `OBJ-RESP-02`: request `resp_001b91f88518f0f0016a7937b7cfa08191881456c56c83329a`,
  estimated cost `1903` micro-USD, latency `10894` ms.
- `OBJ-RESP-03`: request `resp_0600ab0b60ec2a25016a7937ce41e081a2981edc50b0885b87`,
  estimated cost `1849` micro-USD, latency `9622` ms.

Each objective's candidate and judge receipt is preserved under the campaign
artifact root. The exact file hashes are recorded in
`artifact-manifest.sha256`.

## Validation

- Contract and H3 harness focused tests: `8 passed in 0.09s`, exit `0`.
- Deterministic C3/H3 gate before provider: `122 passed in 32.88s`, exit `0`.
- Broad regression before provider: `4014 passed, 8 skipped, 34 warnings in
  240.58s`, exit `0`.
- Provider campaign: `PASS_3_OF_3`, exit `0`.
- Post-campaign focused deterministic gate: `122 passed in 31.65s`, exit `0`.
- Post-campaign broad regression: `4014 passed, 8 skipped, 34 warnings in
  253.38s`, exit `0`.

These gates prove source, deterministic validation, provider qualification, and
artifact provenance. They do not prove browser behavior, human educational
review of H3B2 outputs, production publication, student outcomes, hosted
provider operations, or private-beta readiness.

## Scope boundary

Not started and still closed: five-question generation, repeat generation,
remediation, browser proof, private beta, Progress, Study Sessions, Course
timeline, recommendations, hosted provider operations, and real-student
recruitment.

No BlueWay checkout, C2 checkout, frozen migration, hosted environment,
production configuration, or production student content was modified.

## Machine qualification ledger

The versioned three-objective snapshot is:

`evals/reference_course/objective_qualification_evidence_roles_h3b2_2026-08-09.csv`

It preserves the H3B-1 human-qualified status and records H3B2's two
model-qualified statuses without converting them into human decisions.

## Final handoff

Final implementation commit: `b53a9f91`.

The docs, machine ledger, and durable v4 evidence are included in the
docs/proof closeout commit recorded in Git after this receipt update. The branch
may be handed to the next lane only with the fork push state reported alongside
that commit. Do not start the five-question campaign from this receipt alone.
