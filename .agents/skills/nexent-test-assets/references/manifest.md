# D1-D5 implementation manifest

The manifest maps a formal Case to one or more fixed implementations. It does not duplicate case steps or contain credentials. Files must remain below `test/automation/d1` through `test/automation/d5`; Legacy UT paths are invalid.

Update only affected entries. Recalculate `contract_hash` when the authoritative Case changes and `implementation_hash` when implementation content changes. After the incremental edit, validate all entries, file paths, selectors, Case metadata, stages, profiles, and hashes.
