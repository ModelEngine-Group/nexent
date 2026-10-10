# Selected tools and child Agents — 2026-10-10

## Frozen analysis before implementation

The user clarified that the defect is the populated display in the Agent configuration page, and supplied a cropped high-fidelity image. The image shows three selected tools followed by the add-tool entry in one two-column grid, and one selected child Agent followed by the add-Agent entry. This change does not restyle selection drawers or modify backend contracts. Knowledge-base management keeps its existing implementation and serves as the consistent selected-row presentation reference.

The earlier shared-screen session did not yield new inspector measurements and was stopped by the user. The attached crop establishes composition and appearance, not new exact source-pixel measurements. The numeric shell below reuses the already documented, inspector-confirmed knowledge-row contract; descendant details are explicit screenshot-based implementation choices, not claims of inspector evidence.

| Region | Frozen implementation |
| --- | --- |
| Grid | Two equal desktop columns, 8px row and column gaps; one column below the small-screen breakpoint. Preserve selected-resource order and append one add entry after all visible rows. |
| Selected-row shell | 48px high, white background, 4px radius, 1px solid #DFDFDF, horizontal padding 12px, vertical padding 8px, matching the current knowledge-base shell and its soft outside shadow. |
| Name | 14px / 22px, regular 400, tracking 0, #191919, one line with ellipsis and a tooltip containing the complete name. No monospace styling. |
| Tool icon | 24px blue resource mark; reuse a Lucide resource glyph with blue treatment because the original raster artwork is not present in the repository. Exact artwork parity is unverified. |
| Child icon | 32px square avatar; reuse the existing Agent avatar resolver for uploaded icons and the application's existing fallback. No fabricated avatar URL. |
| Metadata | Neutral inline tags directly after the name, with 8px spacing. 12px / 18px, #777777, light gray fill, 4px radius, compact horizontal padding. Render actual catalog labels only. |
| Tool actions | Settings and trash icons always visible at the right edge, 14px glyphs inside 24px Ant Design text-button targets, #777777. Retain configuration prerequisites, warnings, and read-only disabling. |
| Child actions | One always-visible trash icon at the right edge using the same button contract. Preserve internal/external removal callbacks and saved version metadata in a tooltip. |
| Section layout | Retain the existing 16px resource-module gap and title/description typography. Use the same 8px content spacing as knowledge/child modules. |
| Add entry | Reuse ResourceAddButton unchanged: 48px high, 8px radius, 3% dark fill, centered 24px plus and 14px label. |

## Responsibilities and compatibility

Create a shared presentation-only SelectedResourceRow under frontend/components/common. It owns the shell, icon/name/metadata/actions arrangement and tooltip; it contains no API or store mutation. Tools keep managed-resource filtering, real labels, canonical parameter hydration, availability warnings, and the existing configure/remove controller. Child Agents keep separate internal/external IDs, saved version snapshots, relation services, current-Agent exclusions and confirmation timing. Existing non-high-fidelity consumers retain their presentation. Opening, rendering or closing controls must not mutate associations.

All current functionality already has frontend interfaces, so production mock data is unnecessary. Deterministic frontend test fixtures supply populated and read-only states for validation. Missing tool labels or child tags remain absent rather than being replaced with the screenshot's sample text.

Long tool labels and child tags show at most two actual values plus a count whose title contains remaining values. Availability warnings stay in the fixed action region so truncated metadata cannot hide them. High-fidelity external rows follow saved selection IDs and retain any additional relation-only entries; the default controller and legacy presentation are unchanged.

## Verification plan

Strengthen AGENT-CONFIG-D1-003 for real populated tool/child component behavior and AGENT-CONFIG-D4-001 for browser geometry, neutral typography, action alignment, add-entry order, narrow screens and unchanged knowledge-base rendering. Verify read-only mutation gates, managed-tool preservation, real configuration callbacks and saved child version behavior. Run the design validator before production editing, then focused component/browser suites, TypeScript and scoped formatting/lint checks. Keep exact artwork/font parity separate from numeric layout acceptance.

## Final implementation and verification

The shared presentation is implemented in `frontend/components/common/SelectedResourceRow.tsx`. High-fidelity tool and child consumers compose selected rows and the add control in one grid. Their default presentations and existing selection, parameter and relation controllers remain compatible. The Agent avatar accepts an optional styling class; the published Agent mapper forwards actual optional string tags. No backend or HTTP request contract changed.

Verification environment: Windows PowerShell, Node v24.18.0, npm 11.16.0, Python 3.11.15. Browser HTTP boundaries use the Mock profile on the task-owned source server at `http://localhost:4010`.

| Verification | Final result | Evidence |
| --- | --- | --- |
| `node test/automation/d1/run_agent_config_layout_test.mjs` | PASS: 45 tests / 8 files, 32.83s | `test/artifacts/selected-tool-child-d1.log` |
| `NEXENT_E2E_BASE_URL=http://localhost:4010 node test/automation/d4/run_agent_config_layout_e2e.mjs` | PASS: 3 journeys, 31.7s | `test/artifacts/agent-config-selected-resources-d4.log` |
| `npm run type-check` and `npm run build` in frontend | Both PASS | `test/artifacts/selected-tool-child-typecheck.log`; `selected-tool-child-build.log` |
| Scoped UI ESLint, Prettier, diff check | PASS | `test/artifacts/selected-tool-child-eslint.log`; `selected-tool-child-format.log` |
| Agent service ESLint comparison to HEAD | No new diagnostics; existing 25 errors / 2 warnings remain | `test/artifacts/selected-tool-child-service-eslint-before.json`; `selected-tool-child-root-eslint.json` |
| Design validator and regenerated Excel drift check | PASS | `test/generated/Nexent_测试基线.xlsx` |
| Implementation validator | Only the pre-existing unrelated CMSR-D2-001 hash is blocked; Agent-config bindings validate | `test/artifacts/selected-tool-child-assets-validation.log` |

The final resource-card screenshot is `test/artifacts/agent-config-selected-resources-1920.png`. Browser checks prove 1920px geometry, 1280px and 620px responsive composition, actual optional metadata, saved versions, unchanged knowledge rows, configuration hydration, captured removal/save/relation payloads and reopened data. No page runtime error occurred. Chromium serializes explicit zero letter-spacing as `normal`; the fixed test verifies the generated zero tracking value and normalizes that serialization. Existing AntD Form/Drawer warnings remain outside this correction.

Only D1-003 and D4-001 manifest bindings/hashes were refreshed. Formal AC-SELECTED-001/002 are PASS under Mock verification in the canonical SPEC task. Source server 4010 was stopped before build. No deployment, backend/SDK modification, commit or push was performed. Exact original font and artwork parity remains unverified; numerical layout acceptance does not claim complete pixel parity.
