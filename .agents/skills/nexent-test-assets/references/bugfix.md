# Bugfix contract

Every confirmed product bug needs a `test/changes/bugs/*.yaml` record and one of these regression outcomes:

- reuse a formal Case that already fails for the correct reason;
- strengthen an existing Case and its script;
- add a new Case at the lowest proving stage and any escaped higher stage that needs protection.

Classify the coverage gap as `missing_case`, `missing_boundary`, `missing_assertion`, `manifest_omission`, `incorrect_skip`, `non_blocking_result`, or `missing_contract`. Do not use a generic statement such as `insufficient coverage`.

If the feature contract is already correct, do not modify it. If expected behavior changes or was undefined, update the Feature first, then the Cases, product, scripts, and manifest.
