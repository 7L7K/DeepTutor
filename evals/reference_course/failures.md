# C3 evaluation failures

This ledger is append-only for each run. Do not replace a failed provider run
with deterministic placeholder output.

| run | case/question | label | evidence | disposition |
| --- | --- | --- | --- | --- |
| 2026-08-08 preflight | all | OPEN_PROVIDER_NOT_CONFIGURED | no non-production provider profile was visible in the isolated checkout; receipt: `run_openai_2026-08-08.json` | do not publish a golden run |
| 2026-08-09 provider campaign | primary, repeat | PROVIDER_OUTPUT_REJECTED | OpenAI reached with `gpt-5-mini`; one completed primary output failed C3 citation support and the final primary/repeat responses failed strict adapter normalization; receipt: `run_openai_2026-08-09.json` | do not publish a golden run |
| 2026-08-09 unsupported probe | case | FAIL_WRONG_SCOPE | Provider returned a source-grounded fermentation question instead of abstaining from the requested photosynthesis/mitochondrial-inheritance topics | human review required; do not publish |
| 2026-08-09 remediation | case | FAIL_UNSUPPORTED | Provider output cited glycolysis/proton-gradient fragments that did not support the full terminal-acceptor claims | do not publish; revise or rerun under a fresh approved campaign |
