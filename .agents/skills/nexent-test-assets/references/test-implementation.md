# Fixed test implementation

Implement only from an active or blocked formal Case. Choose the framework by proof boundary: pytest for Python unit, API, and runtime checks; the frontend component framework for FE-COMP; Playwright for D4; and an appropriate fixed runner for D5.

Preserve existing D1, including unit-oriented scripts. New D1 proves component contracts/internal collaboration, not merely another copy of traditional UT. D3 proves actual inter-component/service/protocol runtime paths. Traditional Python UT uses nexent-python-tests separately; every product change assesses it, not only changes that break existing tests.

Each collected item must expose its Case ID in stable metadata or its test title. Do not create constant assertions, swallow failures, use skip or xfail as completion, or change expectations to mirror the current implementation. Scripts may not depend on developer absolute paths or specific SQL filenames.

After implementation, collect the exact selector and run it. Bind it in the owning Case's `execution.yaml` (primary file is relative to that Case directory); the validator derives hashes and registry entries. Run the full formal-asset validator, then check the affected Case IDs in the generated registry and Excel view.

For new/acceptance-modified Cases follow [acceptance-integrity.md](acceptance-integrity.md). Validate every obligation and actual reported test name, check the assertions against the contract and retain evidence. A script PASS, valid binding or unchanged hash is not semantic certification. Do not auto-mark a missing obligation complete or shrink expectations to fit an incomplete script.
