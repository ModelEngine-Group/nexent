# V5 migration

Migrate V5 Cases, `/home/jason/nexent-test-suite/auto_test` fixed scripts, the existing formal manifest, and every referenced asset dependency. Do not migrate Legacy UT.

The first pass is behavior-preserving: retain Case IDs, expectations, selectors, and script contents; allow only declared path and format changes. Record static, secret/config, runtime-ID, large-file, and policy-skipped assets in `test/migration/v5-asset-inventory.yaml`. Copy only small non-sensitive stable fixtures into Git.

Before optimization or Mock conversion, compare migration results on the same product commit, Ubuntu environment, and assets. Explain every Case-set, selector, hash, or result difference.
