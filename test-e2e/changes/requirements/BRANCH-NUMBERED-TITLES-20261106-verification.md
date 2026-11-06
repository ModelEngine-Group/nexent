# Numbered branch titles

Observed 2026-11-06 on base `51c227cbe` plus existing uncommitted frontend changes, which were preserved.

## Acceptance and implementation

- `build_branch_title` in `backend/management/db/conversation/branch_titles.py` produces `Original title (2)`, skips occupied titles, increments an existing trailing numeric suffix and strips the historical Chinese branch marker when creating a new branch. It does not rename historical rows.
- The 100-character cap includes the suffix; collision checks are repeated after truncation and when the number gains a digit. Empty titles produce `(2)`. Non-numeric parentheses remain part of the base.
- `branch_conversation` reads only active titles of the current owner within its existing transaction and user advisory lock before inserting the new record. Other users/deleted conversations do not reserve names. The existing lock serializes same-owner branch allocations, but no global uniqueness against manual renames or live concurrency proof is claimed.
- Routes, request/response fields, frontend navigation, copied history and transaction ownership remain unchanged.

## Evidence

- Passed: 12 focused tests in `test/backend/database/test_branch_titles.py` importing the real helper normally, using temporary pytest dependencies and bundled Python 3.12.
- Passed: 24 tests total across that file and `test/backend/database/test_conversation_branch_db.py`. The combined isolated run substitutes the import-time `management.db.client` module with a MagicMock to avoid SDK/storage/engine bootstrap; test fixtures supply the mocked sessions already used by the repository suite. The real repository functions, real SQLAlchemy models/statements and real title helper execute. No copied product implementation or live DB is used.
- The normal combined invocation initially failed collection because SQLAlchemy was absent, then because SDK httpx was absent. An attempted storage-only import substitution hit the missing psycopg bootstrap. These are environment limitations, not product-test failures. Temporary SQLAlchemy 2.1.8 differs from the project's configured 2.0 series, and Python 3.12 differs from required backend 3.11; the configured environment must rerun the suite before a product PR.
- Existing child-query assertions were shifted to account for the additional title query. New repository coverage verifies active-owner filters and insertion of `(4)` when `(2)` and `(3)` are occupied. Existing copy/remap, quota-lock ordering and invalid-turn checks pass in the isolated run.
- Copyright headers, Python AST parsing and `git diff --check` passed. Design- and implementation-phase strict asset validation passed with `--require-ut-change BRANCH-NUMBERED-TITLES-20261106`.

## Limits

No live PostgreSQL, concurrent requests, browser journey, deployment or Daily readiness was verified. No new formal D1 duplicates the unit assertions; existing formal Cases are unchanged. External SPEC synchronization remains pending because sibling nexent-doc is unavailable. No project dependency manifests or workflows were modified.
