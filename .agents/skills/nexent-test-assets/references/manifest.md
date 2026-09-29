# Case-local execution binding

There is no hand-maintained central manifest. Each automated Case owns `test-e2e/cases/<Case-ID>/execution.yaml` with its Case ID and one or more implementations. The first implementation is primary: its file is relative to the Case directory and must exist there. Later auxiliary implementation paths are repository-relative and must remain under `test-e2e/infra/`. Every implementation declares `framework`, `file`, and a stable `selector`; optional `profiles` specify Mock or Real Smoke.

Keep Case steps and expectations in `case.yaml`, not in the binding. Do not store credentials, absolute developer paths, fixed resource IDs, or SQL file paths. Reference machine-local assets by logical name and use existing configuration helpers; new configuration keys require a maintained schema and example. A blocked Case may retain a binding when its script exists but a declared runtime prerequisite is unavailable; this is not a passing result.

Only modify affected Case directories. Run `python test-e2e/infra/tools/validate_test_assets.py --phase implementation --generate` to check all Feature/Case/change relationships, safe paths, selectors, and generated views. The registry and Excel are derived artifacts, never edited by hand. Execute affected Case IDs with `test-e2e/infra/tools/run_cases.py` and retain results in a machine-local test home outside Git.
