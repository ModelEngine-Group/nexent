# Backend and SDK configuration

Applies to backend/SDK Python configuration changes.

- Define backend application environment reads and defaults in `backend/contracts/constants/environment.py`. The standalone Gateway reads its injected environment through `backend/gateway/configuration.py` and does not load `.env` files.
- Backend apps and services import values from `contracts.constants.environment` or accept explicit parameters. Apps pass configuration through to services.
- SDK code accepts configuration through constructor/function parameters. Do not add environment reads or `from_env()` methods.
- Update `deploy/env/.env.example` or the relevant component's tracked example when adding/changing a variable. Do not overwrite local `.env` files.
- Update affected constructors/callers to pass values to the SDK. Remove superseded direct reads within the changed path.
- For Ops-managed configuration, locate the administrative API in `backend/ops/api/` and the persisted catalog and process-local snapshots in `infrastructure/system_configuration/`. Use the existing snapshot and refresh path for settings that update at runtime.
- Verify deployment defaults and explicit overrides at the owning configuration entry point. For hot-reload changes, also verify snapshot refresh in the affected service. Inspect changed backend/SDK paths for environment reads outside the defined entry points.
