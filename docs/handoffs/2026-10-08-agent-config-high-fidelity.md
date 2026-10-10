# Agent Configuration High-Fidelity Design Record (2026-10-08)

## Scope

This record captures the confirmed values from the shared Huawei Design canvas and maps them to the existing Agent editor. The reference stayed on the **Agent Creation** page; no other design page was opened. The shared canvas is the visual source of truth. This document is an implementation handoff, not a replacement for the separate Nexent SPEC repository.

- In scope: the Agent configuration panel and its section navigation, scrolling, and fixed actions.
- Preserved: the Agent generation conversation, agent data contracts, form validation, draft autosave, read-only/unlock behavior, availability refresh, debug, version management, publishing, and NL2Agent section focus.
- Excluded: backend changes, new endpoints, data model changes, and unrelated Agent list or creation-modal changes.
- Typography keeps the browser's existing font stack; do not add `font-family`.
- Unspecified values remain unasserted. Do not derive exact sizes from the scaled screenshot.

## Confirmed Canvas Measurements

The values below come from the design inspector and are source pixels, not the 44% canvas preview scale.

| Region                                                   | Measured value                                         | Confirmed layout                                                                                             | Tailwind mapping                                                                                   |
| -------------------------------------------------------- | ------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------- |
| Design artboard                                          | `1920 × 1080px`                                        | Desktop composition                                                                                          | —                                                                                                  |
| App navigation                                           | `64 × 1080px`                                          | Fixed left navigation                                                                                        | `w-16 h-[1080px]`                                                                                  |
| Generation conversation                                  | `561 × 1080px`                                         | Beside the configuration panel                                                                               | `w-[561px] h-[1080px]`                                                                             |
| Configuration panel                                      | `1296 × 1008px`, top `0px`                             | Right-side panel                                                                                             | `w-[1296px] h-[1008px]`                                                                            |
| Wide-screen split ratio                                  | `561:1296`                                             | Apply the artboard proportion on `2xl` viewports; retain a roomier `1:2` split on narrower screens           | `flex-1` / `flex-[2] 2xl:flex-[2.31]`                                                              |
| Configuration header                                     | `1296 × 64px`                                          | Bottom divider `1px #DFDFDF`; left padding `16px`, right `18px`, vertical `12px`                             | `h-16 border-b border-[#dfdfdf] pl-4 pr-[18px] py-3`                                               |
| Configuration scroll area                                | width `1295px`; inspector height `2358px`              | Content scrolls inside the panel below its header                                                            | `min-h-0 flex-1 overflow-y-auto`                                                                   |
| Top information row                                      | width `1261px`; inspector height `74px`                | Vertical padding `10px`; distributed across the row                                                          | `w-full py-[10px]`                                                                                 |
| Main configuration group (layer `226523`)                | `1261 × 1438px`, top `236px`                           | Vertical stack with `12px` inter-item gap                                                                    | `w-full flex flex-col gap-3`                                                                       |
| First section card (layer `226513`)                      | width `1261px`; inspector height `224px`               | Radius `8px`; horizontal padding `24px`; vertical padding `18px`; white fill; inner gap `8px`                | `w-full rounded-[8px] bg-white px-6 py-[18px] flex flex-col gap-2`                                 |
| First section heading/description group (layer `226458`) | `132 × 50px`                                           | At top `18px`, left `24px`; title line `24px`, then `4px` gap and a `22px` description line                  | `h-6` + `gap-1` + `h-[22px]`                                                                       |
| Description text                                         | `132 × 22px`                                           | `12px`, weight `400`, line-height `22px`, letter spacing `0`, left aligned, `#808080`                        | `text-xs font-normal leading-[22px] tracking-[0px] text-[#808080]`                                 |
| First card content row (layer `226520`)                  | `1213 × 130px`                                         | At top `76px`, left `24px`; gap `16px`; centered distribution                                                | `w-full flex items-center gap-4`                                                                   |
| Lower configuration card (layer `226522`)                | width `1261px`; inspector height `598px`; top `1686px` | Radius `8px`; padding left/right `24px`, top/bottom `16px`; gap `16px`; white fill; default border `#C9C9C9` | `w-full rounded-[8px] border border-solid border-[#c9c9c9] bg-white px-6 py-4 flex flex-col gap-4` |

The measured first card's vertical rhythm is internally consistent: `18 + 50 + 8 + 130 + 18 = 224px`. The screenshot's preview scale is not used as an additional source of measurements.

## Visual Decisions

1. Replace the outer **Basic / Tools & Skills / Advanced** tab switcher with one vertically ordered configuration area, because the high-fidelity canvas presents the modules in a continuous panel.
2. Keep the configuration content in one internal scroll area; keep the existing bottom action area outside that scroll area.
3. Present each section title and its description on separate lines. Use the measured `24px` title line, `4px` gap, and `22px` description line in the first card as the section-header rhythm.
4. Use the documented default border `#C9C9C9`, white fill, and `8px` radius for section cards. Use the confirmed `12px` spacing between stacked modules.
5. Render the existing sections expanded initially to match the visible reference composition. Keep the ability to collapse each section.
6. Keep nested prompt tabs inside the model/prompt module; the reference change removes only the outer category tabs.
7. Do not introduce placeholder icons or custom font families. Keep icons from the existing feature components until a measured asset-specific replacement is available.

Values inside individual fields, lower modules, and narrow viewports that were not individually selected in the inspector remain unverified; reuse existing field behavior and avoid claiming exact pixel parity for those details.

## Existing Capability Map

| Section              | Existing implementation                                | Compatibility requirement                                                                             |
| -------------------- | ------------------------------------------------------ | ----------------------------------------------------------------------------------------------------- |
| Display information  | `AgentInfo`                                            | Preserve name/description validation, icon upload, tag management, and draft updates.                 |
| Model and prompts    | `AgentPrmopt`                                          | Preserve model selection, model priority/settings, nested prompt tabs, validation, and draft updates. |
| Knowledge base       | `KnowledgeBaseConfig` and `KnowledgeBaseConfigActions` | Preserve associations and all current actions.                                                        |
| Conversation guide   | `AgentGuide`                                           | Preserve greeting and example-question editing.                                                       |
| Tools                | `AgentToolCapability`                                  | Preserve tool selection and management.                                                               |
| Skills               | `AgentSkillCapability`                                 | Preserve skill selection, editing, and management.                                                    |
| Collaborative agents | `CollaborativeAgent` and its actions                   | Preserve current collaboration configuration.                                                         |
| Run strategy         | `AgentRunPolicy`                                       | Preserve strategy settings and validation.                                                            |
| Publish attributes   | `AgentDeployment`                                      | Preserve publication settings and existing publish validation.                                        |
| Guardrail            | `GuardrailConfigContent` and `GuardrailConfigActions`  | Preserve rules and their existing actions.                                                            |
| Bottom actions       | `AgentConfig` action area                              | Preserve unlock, debug, and publish callbacks and permission/disabled conditions.                     |

All listed capabilities use existing frontend state/services. No new backend interface or fabricated persistent data is needed for this layout change.

## Interaction and Verification Contract

- A request from the generation conversation opens and scrolls to its target configuration section. Tool/skill sub-targets remain supported.
- Collapsing a section does not clear its draft or change server state.
- The scrollable module list does not scroll the whole page or hide the fixed bottom actions.
- Read-only and unlock state, save guard, validation, debug, publish modal, version navigation, and post-publish refresh remain functional.
- Component coverage checks the unified section layout and expand/collapse behavior. Browser-level verification should cover opening an Agent editor, scrolling to a lower section, editing an existing field, using the bottom actions, and focusing a section from NL2Agent.
- No API request, payload, response, database, or backend change is introduced.

## Implementation Evidence

- `agentConfigLayout.test.tsx`: 3 component tests passed, covering the single scroll region, default-expanded/collapse/focus behavior, action callbacks, publish validation flow, and absence of new backend effects.
- Frontend type-check, targeted ESLint, and Prettier checks passed. The production Next.js build in the web image completed successfully.
- Replaced only the `nexent-web` container using the rebuilt `nexent/nexent-web:latest` image; the container is running and `http://localhost:3000/zh/agents` returned HTTP 200. Other application containers remained running.
- Browser verification on an existing draft confirmed all ten sections are expanded after reload, section collapse/reopen works, the content scrolls inside the configuration pane, and the bottom actions remain visible. No fields were edited and no save or publish action was triggered.
- Test-asset design validation and generated Excel drift check passed. The full implementation-phase asset gate remains blocked by the pre-existing stale implementation hash for unrelated case `CMSR-D2-001`; the new Agent configuration case hashes validate.

## Repository Note

The separate `nexent-doc` checkout referenced by repository workflow guidance was not present in the current workspace. This record stays under the existing product `docs/handoffs/` path and must not be represented as a formal SPEC proposal/design/task set.
