# Daily validation scope

Strict `validate_test_assets.py --phase implementation` remains the developer gate.
It fails on every finding. Daily uses `--daily-report <outside-checkout>/asset-validation.json`
instead of `--generate`; it never rewrites repository assets or silently shrinks the plan.

## Decisions

- Unknown findings, malformed contracts/configuration, duplicate IDs, unsafe script
  paths and unresolved deployment recovery stop the batch.
- Explicit `CASE_EXECUTION_MISSING`, `CASE_SCRIPT_MISSING`,
  `CASE_SELECTOR_MISSING` and `CASE_PREPARATION_MISSING` findings with a known owner retain that Case in the plan
  and produce a BLOCKED receipt without starting its worker.
- Missing traditional UT references and stale derived reading views are metadata
  warnings, not proof that formal Cases cannot run. Authoritative assets still pass
  all other validation. Daily never claims UT execution from reference validation.
- `FEATURE_RESPONSIBILITY_UNRESOLVED` and known-Case
  `CASE_RESPONSIBILITY_UNRESOLVED` are metadata warnings for missing or ambiguous
  routing. Workers still execute, including the unassigned Cases; preserve their
  UNASSIGNED/AMBIGUOUS attribution and never guess a person. A planned Feature with
  no Cases is also a warning. Strict developer design/implementation validation
  still rejects every unresolved route. Missing or malformed shared routing
  configuration, invalid domain references, placeholder contacts and invalid
  patterns remain fatal; unknown Case scopes are never downgraded.
- Shared missing helpers are inspected for every referring Case. Runtime preparation
  dependency failures retain the existing BLOCKED_BY_DEPENDENCY behavior; no
  dependency edges are inferred from titles, Change membership or failure keywords.

The launcher, full-registry selector, worker selection and deployment campaign use
the same typed policy. The global environment/configuration doctor and clean-source,
fingerprint, recovery and deployment safety gates remain unchanged.

Default implementation validation checks explicit preparation on every active
D2-D5 binding; no per-Case opt-in flag is needed. A self-contained proof declares
empty families after dependency/cleanup analysis. Daily suppresses the worker only
for a Case missing that declaration; invalid declarations/configuration remain
fatal. Developer strict validation rejects both types of finding before delivery.

## Accounting

`asset-validation.json` is saved with the launch and execution batch, including
campaign profiles. Summary exposes `asset_validation` and `coverage_integrity`.
A warning-only run may have every Case PASS and `execution_complete=true`, but its
overall status is FAILED and coverage integrity is INCOMPLETE. BLOCKED Cases stay
in the denominator and have acceptance_status=INCOMPLETE. No historical result is
rewritten. D6 and the sanitized publication bundle retain the validation receipt.

Offline checks:

```text
python -m pytest -p no:nexent_formal_pytest test-e2e/infra/tools/tests/test_daily_validation.py
```

The formal pytest plugin is disabled only for framework UT so they do not require
machine-local business credentials. It remains enabled for actual formal Cases.
