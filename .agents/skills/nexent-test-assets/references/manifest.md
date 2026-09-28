# D1-D5 implementation manifest

The manifest maps a formal Case to one or more fixed implementations. It does not duplicate case steps or contain credentials. Files must remain below `test/automation/d1` through `test/automation/d5`; Legacy UT paths are invalid.

Update only affected entries. Recalculate `contract_hash` when the authoritative Case changes and `implementation_hash` when implementation content changes. After the incremental edit, validate all entries, file paths, selectors, Case metadata, stages, profiles, and hashes.

Resolve implementation paths before reading them; they must stay inside the case's own stage directory, including after resolving symlinks. Manual, policy-skipped, and retired cases must use the corresponding manifest status. An active automated case requires `implemented`. A blocked automated case may retain an `implemented` entry when the script exists but a runtime prerequisite is missing; this never means the case passed.

Portability and credential validation covers the entire case payload, not just `test_data`. Credential fields must use a logical reference such as `access_token: {asset_ref: tenant_a_credentials}`. Do not embed literal credentials, including synthetic tokens; declare their fixture through the asset reference. HTTP endpoint paths remain allowed.
