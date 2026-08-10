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
- `store=false` and OpenAI transport retries are bounded to two retries per
  intended request, separately from educational candidate retries;
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

The three v1 outputs are preserved as `SUPERSEDED_CONTRACT_FAILURE` evidence.
They are not part of the active v2 candidate limit.

The first active v2 candidate was preserved from the earlier run and was
revalidated before any judge call. Its option counts were `[21, 21, 21, 22]`,
so it failed the frozen `maximum_word_count_delta: 0` contract as
`DISTRACTOR_FAILURE`. It was not deterministic-valid and was correctly not sent
to judges.

The later transport failure was not counted as an educational candidate. The
same intended generation operation was retried through two bounded transport
retry slots under the cumulative ledger. The retry returned a complete v2
candidate and consumed the next active candidate slot. A final active candidate
was then generated. Both had exactly balanced option lengths, but both leaked
opaque evidence IDs into the learner-facing explanation and were rejected as
`DETERMINISTIC_CONTRACT_FAILURE`.

H3B2 therefore exhausted its three completed candidates under the current
contract without reaching model judging. `OBJ-RESP-03` was not started
automatically because H3B2 did not qualify.

## Provider and budget receipt

| Field | Result |
| --- | --- |
| Requested model | `gpt-5.6-luna` |
| Actual model | `gpt-5.6-luna` |
| Reasoning | `high` |
| Storage | `store=false` |
| Transport retries | `2` allowed per intended request |
| Successful requests | `6` |
| Provider transport failures | `1` initial failure; bounded retry succeeded |
| Model judges | `0` |
| Tie-break judges | `0` |
| Settled spend | `12264` micro-USD (`$0.012264`) |
| Uncertain reservation | `9105` micro-USD (`$0.009105`) |
| Cumulative admitted ledger spend | `21369` micro-USD (`$0.021369`) |
| Hard campaign ceiling | `500000` micro-USD (`$0.50`) |

The uncertain reservation remains counted against the cap. The bounded
transport retry reused the same intended operation with fresh ledger operation
IDs; it did not create another educational candidate unless a complete
structured response was returned.

## Durable artifacts

The raw structured provider outputs and campaign summaries are preserved under:

- `docs/verification/2026-08-09-teeechr-c3-h3-model-qualification/`;
- `docs/verification/2026-08-09-teeechr-c3-h3-model-qualification-v2/`;
- `docs/verification/2026-08-09-teeechr-c3-h3-model-qualification-v2-resume/`.

The v1 artifacts preserve all three deterministic `DISTRACTOR_FAILURE` records.
The original v2 artifacts preserve the first active candidate and the original
uncertain transport reservation. The resumed v2 artifacts preserve the
revalidated candidate, the successful bounded transport retry, the final active
candidate, and the three-candidate stop. The external SQLite usage ledger is
outside the repository and contains administrative reservation metadata only;
it contains no credential, prompt, source excerpt, or learner content.

## Validation boundary

- H3 harness compilation: passed.
- Canonical deterministic C3/H3 gate before the resumed provider run:
  `119 passed in 33.20s`, exit `0`.
- Full broad regression: not run after this resume-harness change; the previous
  clean broad regression remains `4011 passed, 8 skipped, 34 warnings in
  281.59s`, exit `0`.
- Educational qualification: not proven.
- Human review: intentionally not started; it is no longer the H3 blocking gate.
- Browser proof, private beta, five-question generation, repeat generation,
  remediation, Progress, Study Sessions, and recommendations: not started.

The current result is a productive fail-closed stop, not a model qualification.
The v1 superseded-contract failures, the v2 exact-length failure, the v2
transport uncertainty, and the v2 opaque-ID failures remain visible. Do not
relabel any of them as an educational pass.

## Historical boundaries preserved

The H3A records and H3B-1 OBJ-RESP-01 successor proof remain unchanged. No
BlueWay checkout, C2 checkout, frozen migration, hosted environment,
production configuration, or production student content was modified.

The next valid step is a separately authorized v3 contract decision: either
retain the frozen exact-length contract and run a fresh bounded campaign, or
explicitly version the assessment contract before changing that constraint. Do
not silently loosen it. If a deterministic candidate clears publication, use
the two-judge Luna-high evaluation automatically; do not reinstate human review
as a blocking gate and do not call model-qualified content human-reviewed.
