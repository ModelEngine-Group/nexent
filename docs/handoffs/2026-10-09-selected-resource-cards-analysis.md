# Selected Model, Knowledge-Base, and Skill Cards (2026-10-09)

## Scope and source evidence

This analysis covers only the populated states of selected models, knowledge bases, and skills in the existing Huawei Design **智能体创建** page. The shared screen stayed on that page in preview; inspection used left-click layer selection and did not navigate to another design page or request edit access. The neighboring design variants remain distinct from the **智能体配置_空状态** artboard.

The selected model area was inspected at 71% canvas zoom. Right-hand inspector values are source pixels. The visible populated example contains three selected models and one add-model entry in a two-column grid; knowledge and skill sections use the same two-column rhythm. The resource card in this populated example is 1261×1028, so its height reflects its content and must not become a fixed height for every Agent.

## Confirmed geometry

| Region                         | Inspector values                                                                                 | Implementation implication                                                                                                         |
| ------------------------------ | ------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------- |
| Model-and-prompt card / 226435 | 1261px wide, radius8, L/R24, T/B16, gap8; populated height398                                    | Keep the existing dynamic card sizing and 24/16 padding contract.                                                                  |
| Model field                    | 1213px wide; label 56×22 at top0                                                                 | Label is 14px/22 regular400 HarmonyOS Sans SC, #191919.                                                                            |
| Selected-model grid / 226525   | 1213×104 fixed, top30, gap8, centered distribution                                               | Two equal columns, each cell 48px high, with an 8px row gap; three model entries and the add entry form two rows.                  |
| Selected knowledge-base cell   | 602.5×48; top56, left610.5; radius4; 1px solid #DFDFDF; padding L/R12, T/B8; white fill with a light shadow visible in the closer crop | Keep the measured shell and two-column width. The screenshot order is icon, name, date/document/chunk metadata, configure, remove. |
| Shared resource card / 226521  | 1261×1028, top410, radius8, L/R24, T/B16, gap16, white fill                                      | Keep each resource module separated by16px; populated content expands naturally.                                                   |

The selected-model grid height confirms its cell rhythm: two48px rows plus one8px gap equals104px. Individual selected model metadata/row descendants were not separately selected in the inspector, so this analysis does not assert their border, icon, or tag colors as exact measured values.

## Populated card composition

- Model entries precede the add-model entry in the 2-column grid. Each entry shows a provider/model mark, model name, available context-capacity label, capability labels, and settings/remove actions. The sample shows context such as `1000k`, text inference, deep thinking, and tool use. In the application, render only capability values available from the current model response. Model type and reasoning support are already available; tool-call support may be absent from existing responses and must be omitted when unknown rather than implied as a mock fact.
- Knowledge-base entries precede the add entry and use the same two-column grid. Each row shows a knowledge icon, name, and metadata already provided by the frontend knowledge-base query (for local records: date, document count, and chunk count), plus configure/remove actions. If an entry is no longer present in the fetched list, render its persisted selected name without fabricated metadata.
- Skill entries precede the add entry in a two-column grid. Each row shows a skill mark, name, up to the first two catalog tags, and view/edit, configure-when-configurable, and remove actions. Do not show the existing long descriptions inside this compact row. The source-group accordion belongs to the existing non-high-fidelity management surface and remains unchanged there.
- Keep add actions as 48px Ant Design buttons using the existing `ResourceAddButton`; do not replace the interaction with an inert card. Model selection, model override, KB selection/configuration/removal, and skill detail/configuration/removal continue using existing state and modal callbacks.

## Typography and styling decisions

| Element                 | Frozen treatment                                                                                                                                                    |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Model field label       | HarmonyOS Sans SC, 14px/22, regular400, #191919 (inspector-confirmed).                                                                                              |
| Resource card name      | HarmonyOS Sans SC, 14px/22, regular400, #191919, single-line ellipsis (visual match to the compact rows; individual name layer not measured).                       |
| Secondary metadata      | 12px/18, regular400, #808080; compact neutral metadata that does not outrank the name.                                                                              |
| Capability/tag labels   | 10–11px, 16px line height, neutral light fill and dark gray text; hide unsupported values.                                                                          |
| Knowledge-base row cell | 48px high; white fill with a subtle shadow; 1px `#DFDFDF` border; 4px radius; 12px horizontal and8px vertical padding; content centered vertically.                         |
| Model/skill row cells   | 48px high, white background; content centered vertically; compact 8px spacing between icon/name/tags/actions. Their individual border and radius were not measured. |
| Grid                    | Two equal columns, 8px column and row gaps; add card remains48px high.                                                                                              |
| Actions                 | Ant Design buttons with 24px hit target and 14px line icon; preserve existing read-only disabling and tooltips.                                                     |

The styling decisions marked as visual matches fill only details the shared inspector did not expose. They do not change data contracts or backend behavior. No static provider/capability metadata is introduced. Missing service functionality can remain visible through the existing selection/configuration modals; mock data is unnecessary for these display-only cards.

For selected knowledge-base rows, shell geometry and padding above are inspector-confirmed; white fill, subtle shadow, descendant text sizing, and icon glyph sizing are visual matches from the supplied screenshot. The high-fidelity card uses the measured shell while retaining fetched date/document/chunk metadata and the existing configure/remove actions.

## Existing frontend behavior to preserve

- `AgentPrompt` keeps `selectedModelIds` order and its existing selection/override logic. Removing a card updates the same selected ID list. The normal non-high-fidelity model picker remains unchanged.
- `KnowledgeBaseConfig` resolves actual records from its existing selector query; its existing add, configure, remove, loading, error, and reselection states remain available.
- `SelectedSkillManagement` continues hydrating persisted skill instances with catalog metadata, and retains source grouping for the non-high-fidelity page.
- Read-only mode continues disabling mutation actions.

## Implementation and validation record

Implementation follows the frozen geometry: selected model, knowledge-base, and skill entries share a two-column grid with 48px rows and 8px gaps, followed by the existing 48px add control. Cards preserve the current configure/edit/remove callbacks and disabled states. Model capability/context labels and knowledge-base metadata are rendered only when supplied by existing frontend data. A missing model tool-call flag stays hidden; the model service now carries the optional frontend field when the API supplies it. No backend code or service contract changed.

Validation completed:

- `npm run type-check` passed.
- `npx vitest run --config ../test/automation/d1/agent-config.vitest.config.mjs` passed: 5 files, 22 tests.
- `npm run test:components -- --testTimeout=30000 tests/component/agentConfigLayout.test.tsx` passed: 1 file, 5 tests. The default five-second run was started concurrently with the D1 suite and timed out under that load; the isolated run passed.
- `npm run build` passed.
- Locale JSON parsing and `git diff --check` passed.
- Prettier check passed after formatting the three reported files. ESLint passed for the resource-management components, with no findings in the new model-card/grid code. The broader check reports existing violations elsewhere in the touched files, including synchronous state updates in `agent-prompt.tsx` and existing `any` types in `modelService.ts` and `modelConfig.ts`; those are outside the selected-card additions.
- No backend file is in scope.

Individual resource metadata colors, icon artwork, and per-entry border tokens were not individually exposed by the preview inspector. Those details use the measured grid rhythm and existing neutral design tokens and are documented as visual matches rather than exact inspector measurements.

The local frontend image was rebuilt from the current workspace and loaded as `nexent/nexent-web:latest` (`sha256:cf997b3ad25377c9e644afdb682028bd07d68da7cd68afa5cde82a5955642e16`). Only the `nexent-web` Compose service was recreated with dependencies disabled. Its prior image ID was `sha256:3411162a5fdd9a4096efbdf389346341f267c531d60ffe0bbd69c3a65dcaaa3f`; backend service start times remained unchanged. Post-replacement smoke check returned HTTP 200 and the container log reported Ready on port3000.

## Follow-up selected knowledge-base visual reference — 2026-10-09

The user supplied a closer screenshot of one selected knowledge-base row. It clarifies the inner composition: a purple knowledge icon, name, a date plus “used” status, document count, and chunk count, separated by thin vertical rules, followed by settings and remove icons. Keep the previously inspector-confirmed602.5×48 shell,4px radius,1px `#DFDFDF` border,12px horizontal/8px vertical padding. Pixel sampling of the latest crop shows a white card with a light shadow; the accompanying two-card screenshot shows that the light gray fill belongs to the add entry. The screenshot itself is a crop without the source inspector, so icon and descendant typography sizes remain visual matches; use a24px icon tile with a16px glyph,12px/18 metadata, and the existing14px/22px name treatment. Keep metadata directly after the name with an 8px gap and leave the two 24px settings/remove hit targets adjacent at the right edge. Use available knowledge-base record date/count fields; “used” is a status label for the selected row, not fabricated usage history. Match the Chinese count labels without spaces (`7文档 | 18分块`) through Agent-card-specific locale strings so other knowledge-base pages retain their existing copy.

Final verification after this alignment: `npm run type-check`, `npm run build`, the D1 component suite (5 files,23 tests), formatting and diff checks all passed. The D4 browser layout suite passed both cases, including the 602.5×48 geometry, shell styles, icon, separators, action buttons, and compact Chinese count labels. The rebuilt `nexent/nexent-web:latest` image (`sha256:03ca3385a7c4010a2502ea5f6c4f9e6aa7e99a19c00beea398579d6158826433`) replaced only the `nexent-web` service; the running container uses the same image and `/zh/agents` returns HTTP200. No backend code changed.

## Background and spacing correction — 2026-10-09

The user noted that the selected card still differed from the high-fidelity screenshot. Pixel samples from the supplied single-row crop show the selected card is white with a subtle outside shadow; the two-card crop shows the light-gray fill belongs to the add entry. The selected card now uses white fill and a soft shadow. Its metadata follows the name at an 8px gap, while the settings and remove hit targets are adjacent at the right edge. Type-check, production image build, formatting, D1 (5 files,23 tests), and D4 (2 browser tests) pass. `nexent/nexent-web:latest` is deployed with image ID `sha256:cd6e501fe0f9e570d6fd0ed3a1a3bf17b759f0a78ae0fa37580c31b5ab8b576e`; `/zh/agents` returns HTTP200. No backend code changed.
