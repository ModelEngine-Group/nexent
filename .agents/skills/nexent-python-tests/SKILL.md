---
name: nexent-python-tests
description: Use when writing, debugging, or reviewing Nexent Python unit tests under test/backend, test/sdk, or other test Python modules. Covers pytest fixtures, lookup-site mocking, async behavior, isolation, and regression assertions. Skip frontend checks and live-service functional or model-runtime verification.
---

# Nexent Python unit tests

Paths below are relative to the repository root.

1. Identify the unit and behavior. Inspect neighboring tests, `test/conftest.py`, and `test/pytest.ini` before changing fixture/import setup.
2. Use pytest exclusively, pytest assertions, fixtures, and `pytest-mock`. Files/functions start with `test_`; test classes start with `Test`. Keep files below 500 lines or split by feature using `test_<module>_<feature>.py`; split package directories include `__init__.py`.
3. Import the unit and necessary test helpers. Mock collaborators rather than exercising external interfaces/clients/services. Patch the fully qualified lookup site determined from actual imports, not the dependency's definition module.

For example, if `backend.services.example_service` imports `fetch` using `from provider import fetch`, patch `backend.services.example_service.fetch`. If the runtime loads the module as `services.example_service`, use that actual path. Do not copy an unrelated service path from an example.

4. Isolate external I/O and APIs. Reset mutable state with fixtures; use `autouse=True` when every test in a scope requires it. Do not mock away the behavior being asserted.
5. Cover changed success/error flows and boundaries with specific observable assertions. Use `side_effect` for collaborator errors, `@pytest.mark.parametrize` for variants, and `@pytest.mark.asyncio` for async tests. Async collaborators need awaitable mocks.
6. Order imports as standard library, third-party, then project; write comments/docstrings in English.
7. Run narrow tests from the root with a working backend environment, such as `pytest test/backend/apps/test_agent_app.py -v`. Broaden when needed; `python test/run_all_test.py` is the existing broad runner.

Report commands, results, and environment failures. Unit-test isolation does not replace live-service functional checks or real-model acceptance.
