# Fixed test implementation

Implement only from an active or blocked formal Case. Choose the framework by proof boundary: pytest for Python unit, API, and runtime checks; the frontend component framework for FE-COMP; Playwright for D4; and an appropriate fixed runner for D5.

Each collected item must expose its Case ID in stable metadata or its test title. Do not create constant assertions, swallow failures, use skip or xfail as completion, or change expectations to mirror the current implementation. Scripts may not depend on developer absolute paths or specific SQL filenames.

After implementation, collect the exact selector and run it. Bind it in the owning Case's `execution.yaml` (primary file is relative to that Case directory); the validator derives hashes and registry entries. Run the full formal-asset validator, then check the affected Case IDs in the generated registry and Excel view.
