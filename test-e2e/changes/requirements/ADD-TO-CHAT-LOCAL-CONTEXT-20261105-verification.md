# Reply annotation nearby-context verification

Observed on 2026-11-05. Base revision: `3aae5d5395875f4312fffb9bbb7087bbc0e7e31b`, branch `feat/conversation-artifacts-panel`, plus the current working-tree delta. Pre-existing conversation branch, scrolling, artifacts and directory edits were preserved. No merge, remote reconciliation or deployment was performed.

## Acceptance and implementation

- Selection captures optional before/after snapshots from the actual DOM Range, not a first-occurrence string search. Prefer the endpoint paragraph; at paragraph boundaries use nearby reply text. Each side is limited to the nearest 200 characters.
- Exclude reasoning/tool containers from captured context and reject selections crossing those containers. Preserve the existing 1500-character selected-quote and 500-character comment limits.
- Keep the 40-character source label for UI display. Model input omits that label and separates contextual excerpts from selected text and the user's question.
- Extend frontend wire readers/writers and the backend annotation model with optional context fields. Existing generic JSON message-unit persistence, history projection, current-run formatting, historical-context formatting and branch unit copying carry the snapshots without schema changes. Existing payloads remain accepted.
- Strengthen existing frontend and backend UT. No new formal D1-D5 Case was introduced; unit assertions are not reported as runtime, browser, model or persistence acceptance.

## Checks

- Passed: 14 existing/new contract-focused pytest cases selected from `test/backend/services/test_message_annotations.py` (normalization, formatting, context limits, malformed and legacy payloads, JSON parsing). Because the full test module imports unavailable application dependencies, its contract-only imports/constants/functions were extracted with Python AST into a temporary pytest module. These tests execute the real `contracts.annotations` implementation. Runtime used bundled Python 3.12, not the required backend Python 3.11 environment.
- Passed: temporary Node/jsdom assertions against the real frontend helper implementation, using Node TypeScript stripping. Checked actual Range selection, repeated quote positions, frozen snapshots after DOM mutation, wire/history round-trip, adjacent-paragraph fallback, 200-character limits, tool exclusion and legacy malformed optional fields. This is an ad hoc helper check, not execution of the repository Vitest suite or a browser journey.
- Passed: Prettier check on all four changed TypeScript/TSX files; copyright header check on all six changed source/test files; `git diff --check`.
- Passed: unified design- and implementation-phase asset validation with `--require-ut-change ADD-TO-CHAT-LOCAL-CONTEXT-20261105`. Initial sandbox attempts failed because of missing PyYAML and temporary Excel directory permissions; the completed checks used temporary dependencies and approved execution outside the sandbox.

## Remaining verification and prerequisites

- Full `test/backend/services/test_message_annotations.py` collection is blocked by missing SQLAlchemy. The configured backend Python 3.11 environment and project dependency installation are absent. Persistence/service/history tests were strengthened to include context but have not run as a complete suite.
- Repository Vitest and TypeScript project checks are blocked by absent frontend `node_modules`; npm is not on PATH. Temporary helper tooling does not replace those checks.
- Sibling `nexent-doc` is absent, so the external SPEC update remains blocked. The repository change YAML records the authorized behavior and UT responsibilities; no substitute external SPEC was created.
- No live browser/API/model execution, generated functional coverage claim or Daily/merge readiness claim is made.
