# Shared Composer styling

Date: 2026-10-19. Change: CHAT-COMPOSER-STYLE-20261019.

## Scope and acceptance

The user requires Agent debugging to use the same Composer styling as NL2Agent, Workbench and Newchat. The shared Composer owns its frame, text input, model selector, toolbar and send/cancel controls. Agent debugging retains its surrounding header, welcome area, suggestions and footer layout.

- Remove every `debugLayout` style branch from Composer and its send/cancel controls.
- Use the existing default styles, including model selector typography and send/cancel button sizes.
- Preserve existing callbacks, disabled states and debugging's hidden plan panel. Express plan visibility through `hidePlan`, independently of presentation.
- Keep `Thread.debugLayout` only for the surrounding debug page layout; it must not select Composer styles.

## Baseline and design

Inspected `frontend/app/[locale]/agents/[agentId]/components/debug/{agent-debug,compare-panel}.tsx`, shared `composer.tsx` and `thread.tsx`, `frontend/tests/workbench/Composer.test.tsx`, `test-e2e/features/CHAT-MODEL-CONTROLS/feature.yaml`, and the sibling document repository's `docs/Developing/ux-agent-workbench-layout/design.md` on the date above. The workbench layout baseline and model-controls Feature cover adjacent layout and behavior but do not prescribe the debug-specific visual overrides. The user's instruction supplies the intended visual contract.

Remove Composer's debug presentation prop and style overrides. Thread maps the existing debug context to the content-only `hidePlan` prop. Comparison debugging already uses the default Composer and needs no caller change. The unused configuration-specific contract is outside this debug cleanup; no active caller selects it.

## Verification responsibilities

Traditional UT: presentation-only exemption, with the existing Composer suite selected for callback, parameter, resource and cancellation regressions. No new class-string tests are needed for this reversible style cleanup. Python is unaffected.

D1-D5: no changed behavioral contracts or new formal cases. Existing model-control contracts remain intact. Unit tests and static checks do not establish browser visual acceptance; no browser visual comparison is claimed.

## Verification results

- `npx vitest run --config vitest.workbench.config.ts tests/workbench/Composer.test.tsx`: 21 tests passed.
- `npm run type-check`: passed.
- Prettier check for both modified source files: passed.
- Copyright check for both modified source files and `git diff --check`: passed.
- ESLint for both modified source files: zero errors, five unused-variable warnings in untouched portions of `thread.tsx`.
- Formal design and implementation validators with `--require-ut-change CHAT-COMPOSER-STYLE-20261019`: blocked by stale generated registry and Excel views. No Case or Feature contract was changed by this cleanup; the working tree already contains unrelated Feature and Case edits. Derived views were not regenerated as part of this isolated presentation change.
- Browser visual comparison: not run.
