# Runtime preparation and environment isolation

See [Case preparation execution](preparation.md) for the automatic factory call
chain and [static asset migration](static-assets-migration.md) for media placement,
inventory and pending provisioning checks.

`infra/tools/static_assets.py plan|apply|verify --test-home <external-dir>`
handles catalogued static files. Pass `--source-assets test-e2e/infra/assets` to
plan/apply from the repository-owned fixtures. Daily checks all catalog entries at D0; targeted runs check their
declared/direct references. The source suite's `test-assets.yaml` and Case prose
still need a complete reference reconciliation.

Use the repository entrypoint with Python 3.11. Bootstrap is standard-library-only, so it does not require the test environment to exist already. Install `uv`, Node.js >=22 and npm on the host first. Docker is required for deployment and Docker-dependent tests, not for inspecting a plan.

The two existing homes are machine-specific: Windows development uses `D:\work\public\nexent-test-suite`; Ubuntu Daily keeps `/home/jason/nexent-test-suite`. Running the Windows onboarding commands does not change Ubuntu's controller, configuration, or data.

```powershell
python test-e2e/infra/scripts/run-suite.py onboard --test-home D:\work\public\nexent-test-suite
# Inspect the preview first; --execute creates missing config templates only.
python test-e2e/infra/scripts/run-suite.py onboard --test-home D:\work\public\nexent-test-suite --execute
# New developers can choose their own absolute test-home path in the prompt.
python test-e2e/infra/scripts/run-suite.py onboard --interactive --execute
python test-e2e/infra/scripts/run-suite.py doctor --test-home D:\work\public\nexent-test-suite --case UT-SDK-001
# Add --live only when the local product deployment should be reachable now.
```

Onboarding never replaces an existing file, including `secrets.env`. New templates contain placeholders and do not supply working credentials or provider endpoints. Offline `doctor` checks syntax, declared configuration and selected toolchains; `doctor --live` adds bounded HTTP reachability checks. Neither command deploys the product. The entrypoint uses only `<test-home>/runtime/test-venv` for Python tests; it fails with a bootstrap hint if that environment is missing. The existing Windows environment already uses this path. Bootstrap is optional when it is usable.

```sh
python test-e2e/infra/scripts/run-suite.py bootstrap --test-home /path/outside/repo
# Add --execute to install. Without it, only the command plan is printed.
```

Bootstrap consumes `backend/uv.lock` with `uv sync --frozen` into `<test-home>/runtime/test-venv`, installs the SDK source there without re-resolving backend versions, uses `npm ci` for the product/frontend/D4 packages, and installs Chromium into the local test home. It does not download an unpinned uv installer or run sudo. Linux browser OS libraries must be provisioned by the host administrator.

The old fixed-test-requirements file was not a lock: many entries are ranges or unversioned. `fixed-test-requirements.in` preserves that input for review, but bootstrap deliberately does not install its unconstrained additions. Resolve and verify the SDK-only dependency closure against the backend graph before calling the new runtime reproducible. `doctor` checks missing SDK distributions and backend version constraints; it does not certify every native library or network service.

Direct calls to `infra/tools/suite.py` still require the right environment explicitly. Prefer `infra/scripts/run-suite.py`, which selects the existing home environment before importing its dependencies.

## Local data and deployment

Keep config, credentials, private files, browser caches, virtual environments, databases and results outside the product checkout. Copy config examples without overwriting existing settings. `users.yaml`, `models.yaml`, `asset-policy.yaml` and other case-required config remain machine-local and are read through existing helpers.

Keep the test deployment on an isolated host or give it a separate Compose project, network, ports and persistent data directory when sharing a host. The existing Ubuntu test host uses `/home/jason/nexent-test-suite/docker-data/root-dir` for product persistence (verified from the PostgreSQL and Web container mounts); it does not use the developer's normal `nexent-data`. `NEXENT_TEST_HOME` holds test configuration, assets and results, while its `docker-data/root-dir` subtree is the deployed product's persistent data. Do not point destructive/recovery cases at a developer or production stack. Recheck actual mounts and port ownership before cutover; a distinct data path alone does not allow two stacks with the same container names and ports to run concurrently on one host.

Daily build/deploy/preflight hooks belong in machine-local `config/pipeline.yaml`. Each hook is an argv array, not an interpolated shell command. Use only explicit `{python}`, `{repo}`, `{home}`, `{run}` tokens and pass credentials through existing local configuration. No build or deployment is performed unless `daily --execute` is requested. Empty hooks fail closed. Existing deployment scripts, latest image tags and container recreation policy are unchanged.

This candidate controller does not fetch Git, enable schedules, migrate databases, switch the running Ubuntu suite, or automatically recover an interrupted destructive test. A pending deployment recovery blocks execution. Those cutover operations require the remaining migration and same-commit validation gates.
