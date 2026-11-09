# Selected-text-only annotations

The frontend no longer traverses neighboring paragraphs or stores context in
selection targets, drafts, outgoing payloads or restored cards. Draft creation
uses an explicit field list, so stale runtime objects cannot reintroduce context.
The backend ignores old context keys while parsing requests and persisted JSON
units. Model-facing blocks contain only the selected quote and optional comment;
source excerpts remain display-only. No SQL migration or history rewrite is used.

Checks performed:

- PASS: 30 frontend tests in messageAnnotation.test.tsx, using the temporary
  Vitest/React test environment outside the repository. Covers outgoing fields,
  malformed legacy context, selection safety, quote/comment caps and cards.
- PASS: 15 backend tests from test_message_annotations.py selected by
  `normalize or format or parse or legacy`; 7 unrelated AgentRequest/service/DB
  integration tests were deselected. Uses temporary Python 3.12/Pydantic and
  pure-Python SQLAlchemy dependencies, not the complete Python 3.11 baseline.
- PASS: copyright checks for all six affected source/test files; diff whitespace
  check. Frontend files formatted using the project Prettier configuration.

Full frontend build, deployed request/model-input inspection and the complete
backend integration environment have not been verified. Existing formal Cases
are preserved; no runtime/formal Case pass or acceptance completeness is claimed.
The separate nexent-doc repository remains unavailable for SPEC synchronization.
Other pending bookmark and question-rail edits were preserved. No deployment,
commit or push was performed.
