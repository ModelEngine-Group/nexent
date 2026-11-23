# V5 migration

Migrate V5 Cases, existing fixed scripts, binding information, and every referenced asset dependency to `test-e2e/`. Do not migrate Legacy UT.

The first pass is behavior-preserving: retain Case IDs, expectations, selectors, and script contents; allow only declared path and format changes. Keep source/target checksums in `test-e2e/infra/migration/layout-copy-report.json` and the prior asset inventory under `test-e2e/infra/migration/source-audits/`. Copy only small non-sensitive stable fixtures into Git.

Before optimization or Mock conversion, compare migration results on the same product commit, Ubuntu environment, and assets. Explain every Case-set, selector, hash, or result difference.
