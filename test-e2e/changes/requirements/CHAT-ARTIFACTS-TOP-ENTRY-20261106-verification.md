# Persistent top-right artifacts entry

Observed 2026-11-06 on base `51c227cbe` plus the existing uncommitted question-rail changes. Those changes are preserved.

## Acceptance and implementation

- Replace the assistant-message entry with one `ConversationArtifactsToolbarEntry` in ThreadView, after the optional conversation header and before the message viewport. It is outside the scroll viewport and aligned to the right edge of the conversation column, immediately left of an open side panel.
- The toolbar occupies 48px only when the current conversation has artifacts. Without a provider or with a zero count, it returns null and reserves no space. It does not cover messages or scroll away with them.
- Continue reading the existing aggregate conversation count from the provider. Later text-only questions/answers retain the entry; new files update the count; an empty conversation hides it. Do not introduce a global ever-generated flag that leaks visibility between conversations.
- Clicking opens the existing panel through the existing callback. Preview, download and add-to-chat behavior are retained. No backend or persistence changes.
- Rename the component and update context documentation to reflect toolbar ownership; remove the assistant-message call site entirely.

## Verification

- Passed: 50 tests across `frontend/tests/component/conversationArtifacts.test.tsx` and `frontend/tests/component/questionDirectory.test.tsx`, using actual repository components with Vitest 4.1.12 and temporary dependencies outside the repository. The temporary Vite resolver configuration was removed after execution. Package versions differ from the repository lockfile; dependency manifests and lockfiles were not changed.
- The added lifecycle test verifies hidden initial state, first generated file, a single toolbar entry, visibility through subsequent text-only turns, opening the panel, updated count after another file, and reset on an empty conversation. Existing panel preview/download/add-to-chat tests pass.
- jsdom emits its existing unsupported document-navigation notice during download tests; all tests pass.
- Copyright checks passed for all four modified source/test files; Prettier and `git diff --check` passed.
- Strict design- and implementation-phase asset validation are run with `--require-ut-change CHAT-ARTIFACTS-TOP-ENTRY-20261106`. These are asset checks, not formal browser/runtime execution.

## Limits

- No full locked frontend type-check/lint/build or live application visual verification was performed because project dependencies are absent. No screenshot equivalence or D4 journey result is claimed.
- Python UT is unrelated to this frontend-only placement change. Existing formal Cases are preserved; no duplicate D1 or new external boundary is introduced.
- External SPEC synchronization remains pending because sibling nexent-doc and ../docs/前端ui.md are absent. The user's screenshot and explicit position/visibility clarification define this change.
- No deployment, remote merge or Daily readiness is claimed.
