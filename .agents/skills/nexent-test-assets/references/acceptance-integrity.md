# Acceptance implementation integrity

Keep execution evidence separate from semantic completeness. Script presence, Case IDs, hashes, a binding map or green execution cannot prove every requirement was implemented. Do not create a new manual approval workflow: the implementing workflow must independently check actual test inputs/actions/assertions against the contract and retain sanitized evidence locally. High-risk rules need targeted negative/variant tests and, where practical, a controlled mutation demonstrating the test detects broken behavior.

## Compatible contract

Preserve every existing D1 Case/script. Cases without the following metadata remain executable with acceptance completeness `UNREVIEWED`, not automatically certified or retired. For a new automated Case or a changed acceptance contract, add `case.acceptance`:

```yaml
acceptance:
  - id: AC-01
    description: Source-byte usage remains correct when ES statistics fail.
    expected_results: [1]
    steps: [1, 2]
    forbidden_side_effects: [1]
```

The integer references are one-based expected_results/forbidden_side_effects indexes and actual step.order values. Across the obligations, cover every step, final expectation and forbidden side effect. Preserve stable IDs when changing wording. Do not drop requirements simply to pass the completeness gate. `acceptance` is not a replacement for existing steps or expectations.

Add `acceptance_bindings` to that Case's execution.yaml:

```yaml
acceptance_bindings:
  AC-01:
    - test_usage_survives_es_statistics_failure
```

Values are actual framework-reported test names, not filenames, comments or the Case selector. For pytest use the reported name, optionally `ClassName::test_name`; a base name includes every collected parameter variant. Vitest uses its reported test name. Node uses leaf TAP titles. Fixed D4 can use its Case ID, backed by the existing complete journey/step audit; mapping every obligation to that ID is not semantic certification. Independently verify the journey really asserts all mapped requirements.

## Gates and evidence

1. Design: define obligations and cover the complete written contract. Run the design validator with `--require-acceptance-case <ID>` for each added or acceptance-modified automated Case. Do not invent test names before implementation.
2. Implementation: bind all obligation IDs, then run the same validator in implementation phase. Extra/omitted IDs and uncovered contract references fail. Unchanged regression Cases may retain legacy metadata.
3. Execute the fixed Case. The runner reads actual JUnit/TAP/audited D4 outcomes; an absent mapped test is `INCOMPLETE`, a skipped mapped test is blocked, and failed evidence never turns green. Local acceptance-execution.json records obligation outcomes and source hashes. A successful mapped run is `MAPPED_EXECUTION_PASSED`, with semantic_review `UNREVIEWED`; it is not a full correctness claim.
4. Independently inspect each actual assertion, including parameter variants, collaborator substitutions and forbidden side effects. Record concrete selector/assertion locations, expected/observed behavior, current product version and contract/script hashes in task.md or lightweight bugfix evidence. A generic "all covered" statement is insufficient. Do not require a person to approve cases; automated workflow review may perform this step, but deterministic structural checks cannot replace it.
5. For important regression/security/quota rules, demonstrate negative detection or a targeted mutation without committing broken product code. Report limitations honestly. An affected AC cannot close while implementation or evidence is missing.

The runner does not auto-certify semantic review or write status back into formal YAML. Formal reports state execution and mapping coverage separately; existing unreviewed Cases retain their historical execution status. Do not count missing/blocked obligations as acceptance passes. Traditional UT obligations remain in SPEC traceability, outside formal bindings and the functional Case count.
