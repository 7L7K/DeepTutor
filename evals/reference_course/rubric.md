# C3 reference-course rubric

Each generated explanation/question pair receives exactly one primary label:

- `PASS`: correct, supported, unambiguous, objective-mapped, non-duplicative,
  and suitable for the requested grade type.
- `PASS_WITH_MINOR_EDIT`: usable after a small wording or locator edit that
  does not change the answer or objective.
- `FAIL_INCORRECT`: the answer or explanation conflicts with the packet.
- `FAIL_UNSUPPORTED`: the cited packet does not support the claim or the
  citation cannot be reached at its stated locator.
- `FAIL_AMBIGUOUS`: more than one answer is reasonable under the packet.
- `FAIL_WRONG_SCOPE`: the item does not test one of the three approved
  objectives or imports outside knowledge.
- `FAIL_PEDAGOGY`: duplicate, leaked-answer, confusing, or non-meaningful item.
- `FAIL_PRIVACY`: source IDs, owner IDs, prompts, credentials, or private
  metadata appear in learner-visible content.

The approved golden run may contain no `FAIL_*` rows. A provider error or
abstention is recorded separately and never silently converted into a pass.
