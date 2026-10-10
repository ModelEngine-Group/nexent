# Bugfix contract

Every confirmed product bug needs a `test-e2e/changes/bugs/*.yaml` record. Follow `nexent-spec-coding` for document routing: reuse a usable SPEC and its associations, or create a lightweight design.md for the complete coherent capability's final behavior when no usable SPEC exists. Both use the same Feature/business-rule to D1-D5 Case matrix. Keep complete steps/assertions in Case YAML, and current-fix acceptance/evidence separate from the wider functional inventory.

## Determine impact before generating assets

1. Identify reproduction conditions, observed/expected behavior and the affected entry point. Cross-check intent with user requirements, contracts, callers and tests; code alone establishes current behavior.
2. Inspect the changed behavior's direct callers, shared helpers, interface/state changes and risk boundaries. Follow transitive callers where a shared contract changes. A common directory/module name alone is not impact evidence.
3. Search existing SPEC associations and formal Feature/rule definitions, Case steps/expectations and actual script/API references. Read candidate Cases to confirm what they prove; do not rely solely on a name or registry match.
4. Record each related Feature/Case and impact reason in design Notes. Classify Cases as reuse, strengthen, add, regression-only or unaffected. List the execution selection separately from the whole capability's coverage inventory.

Distinguish missing SPEC documentation, test assets unavailable in this checkout (for example not yet migrated), and a confirmed missing assertion/Case. Record search scope and unavailable baselines in the design and bug record's `notes`. Do not regenerate an entire historical feature because its baseline cannot be found. If the current regression needs a new Case, keep it focused and identify the later baseline reconciliation need.

## Select regression coverage

Always assess traditional UT for the defect and necessary adjacent regressions. Use nexent-python-tests to implement or demonstrate existing regression coverage; its evidence belongs in the change's UT column, not a formal Case ID. A UT-only defect may have no new formal Cases. Reusing or adding formal coverage does not remove UT obligations. Preserve existing D1 even when it overlaps UT; distinguish unit, component and runtime proof before adding a layer.

Record traditional_ut in the current bug Change as described in lifecycle.md, and require it with --require-ut-change <Change-ID> in design and implementation validation. Actual local run evidence stays outside the formal record. A no_gap decision may refer to demonstrated UT regression coverage without claiming a formal Case exists; explain that distinction and any no-formal-change rationale.

Choose one or more outcomes based on evidence:

- reuse a formal Case that already fails for the correct reason;
- strengthen an existing Case and its script;
- add a new Case at the lowest necessary proving stage, adding another stage only for a distinct boundary or risk that the fix must prove.

Zero new Cases is valid. Existing neighboring Cases may only need execution, with no contract/script changes. Same-contract input variants may strengthen a parameterized test rather than create separate IDs. Each addition needs a reason that existing coverage cannot prove the defect or necessary regression. There is no D1-D5 quota or arbitrary Case-count cap. Record unrelated historical gaps as deferred coverage instead of current-fix tasks.

## Record and synchronize

Use `coverage_gap.type` from the maintained Change schema: `no_gap` when an existing formal Case already detects the defect, `unknown_baseline` when coverage cannot be assessed, or the evidenced gap (`missing_case`, `missing_boundary`, `missing_assertion`, `binding_omission`, `incorrect_skip`, `non_blocking_result`, `missing_contract`). Historical `manifest_omission` remains accepted as an alias for binding omission. Explain the actual gap; unavailable coverage is not a verified missing Case.

If the feature contract is already correct, do not modify it. If expected behavior changes or was undefined, update the Feature first, then the Cases, product, scripts, and case-local bindings.

Use `affected_cases.existing` for unchanged Cases selected for reuse/regression, `modified` for changed Case assets including script-only changes, and `added`/`retired` for actual additions/retirements. Unaffected Cases may appear in the design inventory but do not belong in the change's execution selection. Keep `affected_features` equally limited to actual changes and relevant unchanged owners. Record the design/SPEC path, impact reasons and deferred gaps in `notes`; no new machine configuration keys are needed.

After the fix, run selected Cases and existing binding/traceability checks. Regenerate views only from authoritative assets. Global validation is not a request to fill all historical functional coverage. Record pre-existing unrelated validation failures as blockers with evidence instead of expanding the bugfix to repair them automatically. Preserve the stable IDs and accurate contracts; do not weaken assertions or manufacture edits to show completion.
