# Backend and SDK configuration

Applies to backend/SDK Python configuration changes.

- Define environment reads and defaults only in `backend/consts/const.py`.
- Backend apps and services import values from `consts.const` or accept explicit parameters. Apps pass configuration through to services.
- SDK code accepts configuration through constructor/function parameters. Do not add environment reads or `from_env()` methods.
- Update `deploy/env/.env.example` or the relevant component's tracked example when adding/changing a variable. Do not overwrite local `.env` files.
- Update affected constructors/callers to pass values to the SDK. Remove superseded direct reads within the changed path.
- Verify defaults and explicit configuration; inspect affected backend/SDK code for stray `os.getenv()` / `os.environ.get()` outside `const.py`.
