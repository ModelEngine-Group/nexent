# Agent Configuration Empty-State Layout Analysis (2026-10-09)

## Scope and evidence

This is the first analysis pass requested before development. The visual reference is the **智能体配置_空状态** artboard on the already-open Huawei Design **智能体创建** page, viewed through WeMeeting remote control. Inspection used left-click layer selection and scrolling within the same design page. No design-page navigation, application form submission, or product implementation is part of this pass.

All confirmed dimensions below are source pixels read from the right-hand inspector, not measurements inferred from the 57% shared-screen preview. Layer names can repeat on neighboring artboards: measurements apply only to the empty-state artboard ancestry. An earlier selection of the neighboring model card showed 398px height; that value is excluded here. The correctly selected empty-state model card is 268px high.

The 2026-10-08 handoff is historical evidence, not the complete specification for this empty state. Existing uncommitted frontend and test changes are preserved. This file is a design-analysis handoff, not a formal proposal/design/task SPEC set or a claim of implemented parity.

## Meaning of the empty state

The design already shows an Agent name, avatar, draft metadata, permission selection, and editable configuration fields. "Empty" means that the Agent exists but models and resources have not yet been added. It does not mean that no Agent is selected.

The current frontend has a separate no-Agent placeholder in `frontend/app/[locale]/agents/[agentId]/agent-config.tsx:368`. That placeholder removes the form entirely and must remain a distinct state. A valid draft Agent with empty model/resource associations is the relevant implementation state for this artboard.

## Outer-to-inner hierarchy

```text
1920 × 1080 artboard, background #F3F3F3
├── 64 × 1080 application navigation
└── 1856 × 1080 content container, x = 64
    ├── 561 × 1080 development-assistant conversation
    └── 1296 × 1008 configuration panel, local x = 561
        ├── 1296 × 64 page-tab navigation
        └── 1295 × 1898 content, local y = 64
            ├── 1261 × 74 Agent identity / mode / publish row
            └── 1261 × 1824 card stack, local y = 74, gap = 12
                ├── 1261 × 224 basic information
                ├── 1261 × 1056 model-and-resources group, gap = 12
                │   ├── 1261 × 268 model and prompt card
                │   └── 1261 × 776 shared resource card, gap = 16
                │       ├── knowledge base
                │       ├── welcome message and preset questions
                │       ├── skills
                │       ├── tools
                │       └── child Agents
                └── 1261 × 520 permissions and advanced settings
```

The inspector reports 1856px for the parent, while the two children total 1857px. If the parent's reported 18px right padding participates in this horizontal layout, the available width would instead be 1838px, leaving a 19px discrepancy. The padding's participation and any overflow therefore need a box-model check. The inspector also reports a 0.5px horizontal offset for the 1295px content inside the 1296px panel. Preserve these source values; do not silently change a measured width to make the sum fit.

The artboard is 1080px high but its configuration content is 1898px high and visibly extends below the artboard in the design canvas. This supports an internal content-scroll implementation, but the static canvas does not prove sticky behavior or the intended bottom 72px treatment. The configuration panel's 1008px height alone is insufficient evidence for a 72px action footer.

## Confirmed outer geometry

| Region / empty-state layer        | Inspector values                                                                         | Tailwind mapping or implementation implication                                                                                                                  |
| --------------------------------- | ---------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Artboard                          | 1920 × 1080; background #F3F3F3; inspector gap 32                                        | `bg-[#f3f3f3]`; artboard canvas coordinates are not CSS offsets. The 32px gap is not assigned to application columns.                                           |
| Application navigation / 91336734 | 64 × 1080; top/left 0; padding L8 / T8 / B16 / R8; even distribution; background #F0F0F0 | `w-16 px-2 pt-2 pb-4 bg-[#f0f0f0]`; inspect navigation children separately.                                                                                     |
| Content / 226427                  | 1856 × 1080; top 0; left 64; right padding 18                                            | `min-w-0`; preserve the inspector width discrepancy rather than imposing unrelated page gaps.                                                                   |
| Conversation                      | 561 × 1080; top/left 0 relative to content; bottom padding 120; white background         | Desktop reference width 561; the visible ambient gradient needs its own effect-layer inspection.                                                                |
| Configuration / 73897             | 1296 × 1008; top 0; left 561 relative to content                                         | Desktop reference width 1296; no measured outer 24px margin or 16px panel gap.                                                                                  |
| Page-tab navigation               | 1296 × 64; bottom inside solid 1px border #DFDFDF; padding L16 / T12 / B12 / R18; gap 4  | `h-16 border-b border-[#dfdfdf] pl-4 pr-[18px] py-3 gap-1`. This is the top tab strip, not the Agent identity row.                                              |
| Content / 91336857                | 1295 × 1898; top 64; left 0.5; padding L16 / R18                                         | `pl-4 pr-[18px]`; 1898 is expanded content height, not a browser viewport height.                                                                               |
| Identity and mode row / 71382     | 1261 × 74; top 0; left 16; vertical padding 10; even distribution                        | `py-[10px]`; Agent identity at left, configuration/debug/publish mode switch in the middle, publish action at right. Individual controls remain to be measured. |
| Card stack / 226438               | 1261 × 1824; top 74; left 16; gap 12                                                     | `flex flex-col gap-3`.                                                                                                                                          |
| Model/resource group / 226523     | 1261 × 1056; top 236; left 0; gap 12                                                     | `flex flex-col gap-3`; this grouping contains two separate white cards.                                                                                         |

## Card geometry and vertical rhythm

| Card                                       | Width × empty-state height | Local position               | Radius / padding / inner gap | Confirmed fill |
| ------------------------------------------ | -------------------------- | ---------------------------- | ---------------------------- | -------------- |
| Basic information / 226513                 | 1261 × 224                 | y0 in card stack             | Radius8; L/R24; T/B18; gap8  | #FFFFFF        |
| Model and prompt / 226435                  | 1261 × 268                 | y0 in model/resource group   | Radius8; L/R24; T/B16; gap8  | #FFFFFF        |
| Shared resources / 226521                  | 1261 × 776                 | y280 in model/resource group | Radius8; L/R24; T/B16; gap16 | #FFFFFF        |
| Permissions and advanced settings / 226522 | 1261 × 520                 | y1304 in card stack          | Radius8; L/R24; T/B16; gap16 | #FFFFFF        |

Tailwind: basic card `rounded-lg bg-white px-6 py-[18px] flex flex-col gap-2`; model card `rounded-lg bg-white px-6 py-4 flex flex-col gap-2`; resource/advanced cards `rounded-lg bg-white px-6 py-4 flex flex-col gap-4`.

No stroke or shadow was reported for these selected card containers. The #C9C9C9 token visible among descendant colors in the advanced card does not establish an outer card border. Do not infer a universal border from the general component defaults.

The selected dimensions agree arithmetically:

- Model/resource group: `268 + 12 + 776 = 1056`.
- Card stack: `224 + 12 + 1056 + 12 + 520 = 1824`.
- Configuration content: `74 + 1824 = 1898`.

These heights describe this empty state and reference width. They should not become fixed heights that clip populated data or translated copy.

## Shared resource card, from outside to inside

All five child modules have a measured 1213px width, starting 24px from the card's left edge. They have an 8px internal gap and 16px between modules.

| Module / layer               | Width × height | Top within shared card | Visible composition                                                                        |
| ---------------------------- | -------------- | ---------------------- | ------------------------------------------------------------------------------------------ |
| Knowledge base / 226431      | 1213 × 106     | 16                     | Heading and description, right-side new-library link/settings control, add-resource row.   |
| Welcome information / 226436 | 1213 × 260     | 138                    | Heading and description, welcome textarea, preset-question count/input, add-question link. |
| Skills / 226448              | 1213 × 106     | 414                    | Heading and description, new-skill link at right, add-skill row.                           |
| Tools / 226449               | 1213 × 102     | 536                    | Heading and description, new-tool link at right, add-tool row.                             |
| Child Agents / 226460        | 1213 × 106     | 654                    | Heading and description, third-party-Agent link at right, add-Agent row.                   |

Card height check: `16 + 106 + 16 + 260 + 16 + 106 + 16 + 102 + 16 + 106 + 16 = 776`.

The tools module is 4px shorter. Its text/effect descendants require inspection before attributing this difference to a specific line height. A shared module component must allow such per-module differences.

### Confirmed knowledge-base header

- Header group 226451: 1213 × 50, top/left0, gap4.
- Knowledge-base title: 80 × 24, top0, left32 in its title row.
- Description: 360 × 22, top28, left0.
- New-library link component: 90 × 22, top1, left1095, gap4, blue #2673E5. Its text font and embedded icon dimensions have not yet been individually selected.

The left title group and right action group are separate. Preserve the title-adjacent collapse chevron position; do not automatically move it to the far right of every card.

### Confirmed add-resource control

- Grid 226524: 1213 × 48, top58 in the knowledge-base module, left0, gap8.
- Add-card child: 602.5 × 48, top/left0; radius8; padding L/R12 and T/B8; background #191919 at 3% opacity.
- Visible centered icon/label group: 134 × 32; top8, left234.25 within the add card. Its actual icon-to-label gap is 12px.
- Plus icon: 24 × 24; top4, left0 within the visible group; color #191919.
- Label container: 98 × 22; top5, left36 within the visible group. Text is "点击添加知识库".
- The second grid column is empty in this empty state. Keep the first entry in the left column rather than stretching it across the entire row.
- Tailwind container: `grid grid-cols-2 gap-2 h-12`.
- Tailwind add-card: `h-12 rounded-lg bg-[#191919]/[0.03] px-3 py-2`.
- Visible group: `inline-flex h-8 items-center gap-3`; icon `size-6`; label `text-sm font-normal leading-[22px] tracking-[0px] text-[#191919]`.

This is an actionable add entry, not an inert empty-state illustration or a full-width dashed placeholder. Use an Ant Design button/control with the measured styling when implemented. Hover, focus, and disabled states remain unmeasured. The reused component also contains hidden description/alternative descendants; their styles must not override the visible label values above. Other resource types still require their own label checks.

## Confirmed typography

| Selected text              | Font family       | Weight      | Size / line height | Tracking / alignment | Color   | Tailwind values                                                    |
| -------------------------- | ----------------- | ----------- | ------------------ | -------------------- | ------- | ------------------------------------------------------------------ |
| Knowledge-base title       | HarmonyOS Sans SC | Medium 500  | 16 / 24            | 0; left              | #191919 | `text-base font-medium leading-6 tracking-[0px] text-[#191919]`    |
| Knowledge-base description | Huawei Sans       | Regular 400 | 12 / 22            | 0; left              | #808080 | `text-xs font-normal leading-[22px] tracking-[0px] text-[#808080]` |
| Add-knowledge-base label   | Huawei Sans       | Regular 400 | 14 / 22            | 0; left              | #191919 | `text-sm font-normal leading-[22px] tracking-[0px] text-[#191919]` |

These selected fonts are different. Do not apply one font family or bold700 indiscriminately to every position. Other titles, labels, placeholders, counts, mode controls, Agent name, and conversation copy still require individual checks before claiming complete typography parity.

The repository has no Huawei Sans or HarmonyOS Sans SC font assets or declarations. The observed font names must remain in the design record; a CSS family name alone cannot guarantee matching rendered glyphs. Font-resource availability is a pending implementation dependency. Existing default font-stack behavior is not proof of the design font.

## Function differences and frontend mapping

In this and the following section, abbreviated editor paths are relative to `frontend/app/[locale]/agents/[agentId]/`; component paths are relative to its `components/` directory.

| Design element                                                | Existing implementation                                                                                            | Interpretation and next implementation constraint                                                                                                                                                                                                                                                  |
| ------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Name/avatar/draft identity row above cards                    | Agent details and edit state in `page.tsx`; name/avatar fields also in `components/agent-info.tsx`                 | The design's basic card chiefly exposes description/avatar. Existing variable name, author, tags, and validation cannot simply be discarded; determine their new placement before development.                                                                                                     |
| Configuration / debug / publish modes plus top publish action | Separate debug/version panels and bottom actions in `page.tsx` / `agent-config.tsx`                                | These are workflow modes, distinct from the old Basic / Tools / Advanced category tabs. Selection styling does not prove navigation mechanics. Keep existing debug/publish validation and autosave behavior.                                                                                       |
| Add model and one visible prompt area                         | `components/agent-prompt.tsx` supports multiple models, priority/settings, responsibility/constraint/Few-shot tabs | The static empty view does not prove removal of multiple-model support or prompt fields. The visible optimization action needs a separate behavior check.                                                                                                                                          |
| Shared resource card                                          | Five currently independent configuration sections                                                                  | Group visuals without merging data ownership or removing the existing section-focus targets. The design orders skills before tools; current code orders tools before skills.                                                                                                                       |
| Add vs. new resource                                          | Existing selection dialogs and resource creation/management actions                                                | Current inference from the labels and existing code: add associates an existing resource, while the right-side new-resource link creates/manages it. Preserve this likely distinction; exact dialogs/navigation and creation flows remain to be checked. No links were executed during inspection. |
| Preset questions (0/5)                                        | `components/agent-guide.tsx` currently allows six                                                                  | Material product-rule difference. Do not silently impose five or pretend six matches the artboard. Resolve the display/limit contract before implementation of this field.                                                                                                                         |
| Permissions before advanced options in one card               | `agent-deployment.tsx` and `agent-run-policy.tsx` are separate sections, ordered differently                       | Keep existing permission and run-policy contracts; regroup the presentation. Private/user/group semantics need mapping to existing user-group and permission fields.                                                                                                                               |
| Visible advanced choices                                      | Existing run-summary, metadata, protocol/self-check, main-Agent/A2A settings                                       | Identify exact checkbox correspondence from labels and current behavior before changing field semantics.                                                                                                                                                                                           |
| No visible guardrail section in this artboard                 | Existing guardrail capability is supported                                                                         | Absence in this static design is insufficient evidence to delete the capability. Its new placement remains pending.                                                                                                                                                                                |

Existing frontend services cover Agent detail/update, models, tools, skills, knowledge-base retrieval-tool parameters, child/A2A associations, greeting/questions, run policy, and publication. Reuse those contracts. If a required new frontend behavior lacks an available interface, use a clearly bounded frontend mock as requested; do not modify the backend or fabricate persistent success.

## Differences from the current frontend layout

The source audit is read-only and does not establish runtime rendering:

- `page.tsx:306` currently adds 24px outer padding and 16px between panels. Its `PanelCard` at line100 adds border, radius, and shadow. Those wrappers do not correspond directly to the measured contiguous desktop columns.
- `page.tsx:580` has a separate return/version strip. The measured 64px page-tab navigation and 74px identity/mode row are separate design layers.
- `agent-config.tsx:110` applies a 1px #C9C9C9 border, bold title, and largely uniform 18px/8px padding to all ten cards. The selected design has four white cards with two padding contracts and a shared resource-card structure.
- `agent-info.tsx:120` includes name/variable-name, author, description, tags, and a 72px avatar; a fixed 130px basic-card content row has not been reconciled with those fields.
- Existing knowledge-base/child-Agent empty states use at least80px dashed placeholders; tool/skill empty states use40px vertical padding. They differ from the measured 48px add-entry row.
- Current module title text is bold700 / #1A1A1A. The selected knowledge-base title is Medium500 / #191919.
- Bottom debug/publish placement and the green publish button differ from the visible top blue publish action. Source evidence must be reconciled without bypassing permissions or publication validation.

## Pending detail measurements before production implementation

1. Conversation heading, guidance list, input panel, ambient gradient, icons, and interaction states.
2. Identity row children: avatar/name/edit icon, draft metadata, mode-control sizes, top publish button.
3. Basic card text/textarea/avatar selection children, form labels, counters, and exact asset dimensions.
4. Model add control, prompt textarea, optimization action, required marker, and remaining nested prompt capability placement.
5. All welcome/question fields and the 0/5 vs. six-question behavior difference.
6. Tool description descendants that explain the 102px height; add-entry label and icon metrics for the other resource types.
7. Permission radio options, advanced inputs, units, checkbox sizing/spacing, and hover/focus/disabled styles.
8. Design font files and remaining font positions; icon assets and shadows where applicable.
9. Sticky/scroll behavior, bottom72px treatment, narrow viewport behavior, and supported localization.

This pass freezes the measured hierarchy, source geometry, card grouping, selected typography, and add-entry structure. It does not assert that all high-fidelity details are complete. Continue measuring pending details before the affected production change.

## References and verification

Consulted: the computer-use skill and its guidance/API/confirmation references; Nexent frontend architecture, components/UI, pages/hooks/API and applicable component references; `frontend/package.json`; `../docs/前端ui.md`; Nexent SPEC coding and SPEC maintenance guidance; the existing 2026-10-08 handoff and current Agent editor source.

Verification for this analysis is inspector selection, source inspection, link/path checks, and the dimension sums above. No frontend/backend implementation, application test run, container replacement, deployment, or publication is claimed for this pass.

## Implementation measurements and decisions recorded after the analysis

The preceding sections preserve the initial analysis. The user subsequently authorized development against the same artboard. Further left-click inspection and frontend implementation established the following values; these supersede the corresponding pending measurements above.

| Area                | Inspector contract                                                                     | Implementation                                                                                                                                                                |
| ------------------- | -------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Desktop composition | 1920×1080; navigation64; conversation561; tab64; identity74                            | Remaining editor width1295 avoids the source's1px width inconsistency; header stays outside the internal card scroll                                                          |
| Basic card          | Height224; horizontal padding24, vertical18; content130; equal columns598.5 with gap16 | Description outer100, avatar preview100 with radius8 and1px #C9C9C9 stroke; display name, variable name, author, and tags are shown directly below the description/avatar row |
| Model card          | Height268; padding24/16; body178                                                       | Model selection78, gap16, prompt84; primary textarea outer54; multiple-model parameters and constraint/few-shot fields remain available                                       |
| Resource card       | Height776; padding24/16; gap16                                                         | Knowledge106, guidance260, skill106, tool102, child106; tool heading-to-entry gap4, other add-entry gaps8                                                                     |
| Guidance            | Greeting outer64; added question input564×32; question section92                       | Empty default has no question input; clicking Add creates an empty input row at564×32; additions stop at5; existing larger arrays stay intact; greeting limit200              |
| Advanced card       | Height520; padding24/16; permission110, gap16, run362                                  | Existing permission semantics,10/4096 defaults and five run options are preserved; protocol repair/guardrail remain in More Settings                                          |
| Mode selector       | 318×32; padding2; gap4; radius6; background #191919 at5%                               | Each button102×28, radius4, horizontal16/vertical3 padding; selected white/shadow0,1,6,0 black8%; text HarmonyOS Sans SC14/22 regular400, selected #0067D1, inactive #777777  |
| Left welcome        | 512×100 at y348; title28/36 weight700, description16/24 weight400                      | Composer512×164 at y448, radius20, padding16, gap8; cold-start prompts remain real composer actions                                                                           |
| Composer            | White fill; outside stroke0.5 #191919 at8%; shadow0,1,6,0 black16%                     | Send40×40 radius26 and default disabled opacity30%; existing attachments, voice and actual conversation runtime are retained                                                  |
| Text entry          | Description200; greeting200; primary prompt1000                                        | Oversized persisted text is displayed completely and permits shortening; default legacy component limits are preserved                                                        |

Inspector text selections confirmed the Chinese knowledge/tool/skill/child/permission descriptions, full description/prompt placeholders and greeting placeholder. Description, prompt and greeting text use HarmonyOS Sans SC14/22 regular400, placeholder #AEAEAE; module descriptions use Huawei Sans12/22 regular400 #808080. Titles use HarmonyOS Sans SC16/24 medium500 #191919. Exact localized copy is stored in `frontend/public/locales/zh/common.json`; English equivalents are maintained separately.

The shared `ResourceAddButton` uses Ant Design and the measured48px height, radius8, two equal columns with8px gap,24px plus icon and14/22 label. The style contract is recorded in `.agents/skills/nexent-frontend/references/components/resource-add-button.md`. Existing resource association/creation callbacks and backend contracts are reused. Deterministic mock HTTP responses are restricted to formal browser verification; production has no fabricated persistent success. No backend file was changed.

## Follow-up UI corrections — 2026-10-09

Before the follow-up implementation, the user clarified that Agent identity fields should be visible inline rather than behind the hidden “补充信息” disclosure, and that preset questions should start with no input. The preset-question inspector measurement remains564×32px; that width and height apply to each created question row. The add action appends one empty question, whose row is then rendered; the 0/5 count and add action remain visible in the empty state. Existing six-item legacy data remains readable and unchanged, while new high-fidelity additions remain capped at five.

The selected knowledge-base card was inspected in the populated resource artboard. Its shell is602.5×48px with1px solid `#DFDFDF`,4px corner radius,12px left/right and8px top/bottom padding, centered/distributed content, and `#191919` at3% fill. In the populated two-column grid this is the same width as `(1213px - 8px gap) / 2`. The supplied screenshot establishes the visual order: book icon, name, date/document/chunk metadata, configure, then remove. Text/icon descendant measurements are not asserted as inspector values unless individually selected.

Current-turn computer-use inventory exposed no shared-design application or remote-control window. The visual comparison therefore uses the user's supplied populated-state screenshot and the source measurements already recorded above; no design page was switched. These corrections do not change backend contracts.

### Remaining visual limits

Huawei Sans/HarmonyOS Sans SC font files and original avatar/background/icon exports are unavailable locally. CSS declares the observed families with fallbacks. Default avatar circles and the ambient background are approximations; module symbols use the existing Lucide library with matching conceptual shapes. Exact glyph, bitmap and icon-path parity is not claimed. Unspecified hover/focus behavior uses existing Ant Design defaults. The source cold-start block extends below1080px; the implementation allows scrolling rather than clipping its last item. Numerical layout acceptance does not establish a screenshot pixel-diff against unavailable source exports.

### Delivery verification

Canonical SPEC is the sibling `nexent-doc/docs/Developing/agt-editor-empty-configuration-layout/`; formal cases are `AGENT-CONFIG-D1-001` through `004` and `AGENT-CONFIG-D4-001`. Commands, current results, global asset-gate exception and final evidence are recorded in that SPEC's `task.md`. Browser screenshots are `test/artifacts/agent-config-empty-1920.png` and `test/artifacts/agent-config-advanced-1920.png`. Mock browser evidence proves frontend layout/save/validation/read-only behavior, not live provider execution or real publication.

## Frontend image replacement after implementation delivery — 2026-10-09

The user authorized replacing the local frontend image and subsequently supplied an account for actual verification. Built the existing web Dockerfile successfully, tagged `nexent/nexent-web:agent-config-20261009-1218` and `latest`, and recreated only `nexent-web` with the original Compose environment/ports/mounts. All other container IDs remained unchanged. The previous image remains available as `nexent/nexent-web:rollback-20261009-1218`.

Deployment checks PASS: server ready on port3000, three real page/resource URLs return200, and the existing AGENT-CONFIG-D4-001 Mock journeys pass against the deployed image (2 tests,10.1s). Separate Real Smoke PASS: actual account login, four-item inventory, existing Agent configuration loading, header74/conversation561 geometry, resource/advanced sections, internal scroll, More Settings open/close and authenticated reload. No page runtime error or business mutation was observed. Existing POST group-list/Agent-search operations were confirmed to be reads. No configuration was saved and no version was published.

Exact image/build/container IDs, commands, rollback information and sanitized evidence are in `test/artifacts/agent-config-frontend-image-replacement.md`; logs are `agent-config-docker-build.log`, `agent-config-docker-replace.log`, `agent-config-docker-d4-mock.log` and `agent-config-docker-real-smoke.log`. Credentials and authentication storage state were not persisted. This adds real login/editor smoke evidence; it does not establish live provider execution or remove the earlier visual-resource/formal-validator limits.

## Left welcome-panel scrollbar fix — 2026-10-09

The user reported an unwanted scrollbar in the default left conversation panel. Browser measurements showed the welcome panel content height exceeded its client height by30px: the four-question suggestions block ended at y=1110 in a1080 viewport and y=1340 in a1310 viewport. The last suggestion itself remained inside the viewport. Set only the default welcome root's vertical overflow to hidden; all measured content positions remain unchanged, the last button is fully visible, and this panel has no vertical scrolling surface.

Verified on both the deployed real page and at1920×1080 and1790×1310 using the supplied account: welcome root has `overflow-y:hidden`, welcome-specific scroll-container count0, last suggestion bottom is1062/1080 and1292/1310. Login, real Agent editing panel, internal configuration scrolling and More Settings remain available. No page runtime errors or business mutations. Validation: type check PASS; existing AGENT-CONFIG-D4-001 deployed-image Mock browser journeys PASS (2 tests,10.9s); Next Docker image build PASS.

Deployed image: `nexent/nexent-web:agent-config-scrollfix-20261009` / `latest`, ID `sha256:3411162a5fdd9a4096efbdf389346341f267c531d60ffe0bbd69c3a65dcaaa3f`; frontend container `02983c9198d3`. Rollback image: `nexent/nexent-web:rollback-scrollfix-20261009`. Detailed image build/replacement logs and viewport measurements are under `test/artifacts/agent-config-scrollfix-*.log`.
