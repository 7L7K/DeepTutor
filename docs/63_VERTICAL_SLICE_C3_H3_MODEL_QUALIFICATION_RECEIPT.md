# Vertical Slice C3-H3 Model Qualification Receipt

Status: H3B NOT QUALIFIED / HUMAN REVIEW NOT A BLOCKING GATE / H3B3 NOT STARTED / FIVE-QUESTION CAMPAIGN CLOSED / PRIVATE BETA BLOCKED

Branch: `feature/teeechr-content-quality-c3-h3`

H3A checkpoint: `88212a21`

H3B-1 checkpoint: `4ff0c3ae`

## Gate policy

The H3A human-review records remain immutable historical project evidence. They
are not required again as a blocking gate for H3B2 or H3B3. H3B model-qualified
content must never be described as independently human-reviewed.

The H3B campaign policy is:

- generation and judging use `gpt-5.6-luna` with reasoning `high`;
- `store=false` and OpenAI transport retries are disabled;
- each objective receives at most three generated candidates after a classified
  deterministic or judge rejection;
- only deterministic-publication candidates reach two independent Luna judges;
- a disagreement permits one fresh tie-break judge;
- every request reserves cost before dispatch against a cumulative
  `500000` micro-USD (`$0.50`) ceiling and fails closed if the next reservation
  would exceed it.

The sibling environment's credential was loaded only inside the local process.
Its configured model was `gpt-5.6-luna`; no `gpt-5-mini` request was made in this
campaign.

## H3B2 result

`OBJ-RESP-02` did not qualify.

Campaign v1 made three successful generation requests. Each candidate satisfied
the structured response shape and cited the four eligible evidence IDs, but the
deterministic v3 contract rejected it as `DISTRACTOR_FAILURE` because the four
option word counts differed by one word. This is consistent with the frozen
`maximum_word_count_delta: 0` contract; no candidate reached model judging.

The first bounded repair surfaced the exact zero-delta constraint to the model
without supplying any manually authored option text. Campaign v2 then made one
successful generation request before the next candidate encountered a provider
transport failure. Transport retries are disabled by policy, so the campaign
stopped and marked that reservation uncertain rather than retrying silently.

Campaign v2 therefore also did not reach model judging. `OBJ-RESP-03` was not
started automatically because H3B2 did not qualify.

## Provider and budget receipt

| Field | Result |
| --- | --- |
| Requested model | `gpt-5.6-luna` |
| Actual model | `gpt-5.6-luna` |
| Reasoning | `high` |
| Storage | `store=false` |
| Transport retries | `0` |
| Successful requests | `4` |
| Provider transport failures | `1` |
| Model judges | `0` |
| Tie-break judges | `0` |
| Settled spend | `8544` micro-USD (`$0.008544`) |
| Uncertain reservation | `9105` micro-USD (`$0.009105`) |
| Cumulative admitted ledger spend | `17649` micro-USD (`$0.017649`) |
| Hard campaign ceiling | `500000` micro-USD (`$0.50`) |

The uncertain reservation remains counted against the cap. No automatic retry or
manual settlement was performed.

## Durable artifacts

The raw structured provider outputs and campaign summaries are preserved under:

- `docs/verification/2026-08-09-teeechr-c3-h3-model-qualification/`;
- `docs/verification/2026-08-09-teeechr-c3-h3-model-qualification-v2/`.

The v1 artifacts preserve all three deterministic `DISTRACTOR_FAILURE` records.
The v2 artifacts preserve the successful generation response and the
`PROVIDER_REQUEST_FAILED` campaign stop. The external SQLite usage ledger is
outside the repository and contains administrative reservation metadata only;
it contains no credential, prompt, source excerpt, or learner content.

## Validation boundary

- H3 harness compilation: passed.
- H3-focused contract gate: `51 passed in 0.22s` before provider calls.
- Canonical deterministic C3/H3 gate after the provider runs: `119 passed in
  33.57s`, exit `0`.
- Full broad regression: not run after this failed provider campaign.
- Educational qualification: not proven.
- Human review: intentionally not started; it is no longer the H3 blocking gate.
- Browser proof, private beta, five-question generation, repeat generation,
  remediation, Progress, Study Sessions, and recommendations: not started.

The current result is a productive fail-closed stop, not a model qualification.
The v1 formatting failure and v2 provider transport failure must remain visible
in the next authorized campaign. Do not relabel either as an educational pass.

## Historical boundaries preserved

The H3A records and H3B-1 OBJ-RESP-01 successor proof remain unchanged. No
BlueWay checkout, C2 checkout, frozen migration, hosted environment,
production configuration, or production student content was modified.

The next valid step is a separately authorized bounded H3B rerun after the
transport environment is stable. If it clears deterministic publication, use
the two-judge Luna-high evaluation automatically; do not reinstate human review
as a blocking gate and do not call model-qualified content human-reviewed.
