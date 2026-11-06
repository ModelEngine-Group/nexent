# Question directory rail verification

Observed on 2026-11-05. Base revision `51c227cbe`, plus the working-tree delta. The working tree was clean before this change.

## Implementation and acceptance

- The user's attached screenshot is the visual reference: a left-side column of short neutral ticks, one per question, with a darker active tick and a small dot.
- Added `frontend/app/[locale]/newchat/ui/question-directory-rail.tsx`. Reuses existing directory collection, active-question identity and jump callbacks. Native buttons support keyboard activation; shared Radix tooltips provide question/reply previews on hover/focus.
- Mounted the same rail outside the message viewport in normal chat, workbench/share mode and the read-only conversation. Reserve a 32px left gutter whenever questions exist; empty conversations do not render the rail or reserve space.
- Bound long tick lists to the available rail height. Active-item synchronization changes only the rail's scrollTop; it never invokes scrollIntoView on the chat. Coarse pointers get larger tick hit targets and a persistent full-directory entry.
- Retained the existing searchable question directory as a compact secondary button, revealed on rail hover/focus and always shown for coarse pointers. Existing search, preview and navigation contracts remain unchanged.

## Evidence

- Passed: 23 tests in `frontend/tests/component/questionDirectory.test.tsx`, including five new rail tests for empty state, active marker and jump identity, keyboard-focus preview, searchable directory access, and keeping active ticks visible without scrolling the chat.
- Execution: Vitest 4.1.12 with jsdom 30.1.3 using temporary dependencies outside the repository and a temporary Vite configuration mapping those dependencies into the actual repository components/tests. Command: `node <temporary-dependencies>/vitest/vitest.mjs run --config <temporary-config>`. The temporary configuration was removed after verification. The project dependency files were not modified. Temporary package versions differ from the project lockfile; this is not the full locked frontend build.
- Initial sandbox execution was blocked by temporary-cache rename permissions. Approved outside-sandbox execution passed after fixing temporary CommonJS/ESM test dependency resolution.
- Passed: copyright headers for all three changed source/test files, Prettier formatting and `git diff --check`.
- Passed: strict design- and implementation-phase formal asset validation with `--require-ut-change QUESTION-DIRECTORY-RAIL-20261105`. These are asset checks, not formal runtime Case execution.

## Limits

- The full frontend type-check/lint/build and a real running application visual check were not run: project node_modules is absent. No browser screenshot, D4 journey, performance result or pixel-equivalence claim is made.
- No Python production code changes, so Python UT is unrelated. No new formal D1-D5 Case duplicates the component tests; existing Cases are preserved.
- The sibling nexent-doc repository and ../docs/前端ui.md are absent. External SPEC synchronization remains pending; the user's screenshot and current requirement change record define the requested presentation.
- No remote merge, deployment or Daily readiness is claimed.
