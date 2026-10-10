---
name: nexent-python-tests
description: Implement and maintain Nexent's traditional Python UT for product changes and bugfixes under test/backend, test/sdk, and test/ext_components. Cover unit behavior, boundaries, errors and regression assertions with isolated pytest tests. Formal D1-D5 assets in test-e2e use nexent-test-assets.
---

# Nexent traditional Python unit tests

Paths below are relative to the repository root.

These tests are a permanently maintained suite kept separate from the requirement-driven D1-D5 system. Historical documents may call it Legacy UT; that does not mean planned removal. Do not assign formal D1-D5 Case IDs to UT, bind it under `test-e2e/cases/`, or count it in the generated functional baseline. Use `nexent-test-assets` for formal Cases.

For every product-code change, assess applicable unit behavior and document reuse, strengthen, add or a justified non-behavior exemption. New or changed behavior requires success, boundary and error coverage. Bugfixes require a regression assertion that detects the defect; demonstrate failure before the fix where feasible. Existing adequate coverage may be reused without artificial file edits. Derive expected behavior from requirements/contracts, not merely the implementation. Relevant local UT verification is mandatory before a product-code PR; CI independently runs its configured UT set. Failures, collection errors and unavailable execution are not passes. UT does not replace required component/API/runtime/journey/risk acceptance.

1. Identify the unit and behavior. Inspect neighboring tests, `test/conftest.py`, and `test/pytest.ini` before changing fixture/import setup.
2. Use pytest exclusively, pytest assertions, fixtures, and `pytest-mock`. Files/functions start with `test_`; test classes start with `Test`. Keep files below 500 lines or split by feature using `test_<module>_<feature>.py`; split package directories include `__init__.py`.
3. Import the unit and necessary test helpers. Mock collaborators rather than exercising external interfaces/clients/services. Patch the fully qualified lookup site determined from actual imports, not the dependency's definition module.

For example, if `backend.services.example_service` imports `fetch` using `from provider import fetch`, patch `backend.services.example_service.fetch`. If the runtime loads the module as `services.example_service`, use that actual path. Do not copy an unrelated service path from an example.

4. Isolate external I/O and APIs. Reset mutable state with fixtures; use `autouse=True` when every test in a scope requires it. Do not mock away the behavior being asserted.
5. Cover changed success/error flows and boundaries with specific observable assertions. Use `side_effect` for collaborator errors, `@pytest.mark.parametrize` for variants, and `@pytest.mark.asyncio` for async tests. Async collaborators need awaitable mocks.
6. Order imports as standard library, third-party, then project; write comments/docstrings in English.
7. Run narrow tests from the root with a working backend environment, such as `pytest test/backend/apps/test_agent_app.py -v`. Broaden when needed; `python test/run_all_test.py` is the existing broad runner.

Report commands, selected tests, results, reuse rationale and environment blockers in the change's verification record, separately from formal Case IDs. Do not recreate the complete historical suite for each change. Python coverage uses backend/sdk; frontend coverage remains separate. Do not impose a new threshold or edit CI from this skill without authorization. Unit-test isolation does not replace live-service functional checks or real-model acceptance.
