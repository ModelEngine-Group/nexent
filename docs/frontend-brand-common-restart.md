# Frontend brand and common components restart

## Baseline and scope

- New branch: `xyq/brand-common`.
- Base: local `develop` at `d289f67ef`.
- Workspace: `C:/xuyaqi/spec-develop/.worktrees/nexent/brand-common`.
- The previous `xyq/shadcn-radix` worktree is retained for comparison. No reset, cherry-pick or migration files have been applied to this baseline.
- This document records the baseline assessment and implementation. The preview on port 3108 now serves this worktree; the previous migration worktree is retained.
- Existing Ant Design and shadcn components are supported. Replacing a component library or making every page import from common is not an objective.

## Ownership

1. Brand presentation belongs in a central theme: the approved Nexent palette, semantic states, base radii and component tokens. Ant Design ConfigProvider consumes that theme; custom controls consume matching semantic variables or useToken. A single primary seed does not reproduce the approved hover, active and selection colors automatically: map these roles explicitly.
2. Use the original component directly when the theme and its native props cover the requirement. Do not add a common component solely to rename an import, set a color, or pass through props.
3. Keep common components for a concrete reusable composition or interaction contract. A short implementation can still be valuable when it centralizes meaningful accessibility, layout or interaction decisions. Length and caller count alone do not establish value.
4. Business components own domain columns, data, permissions, API operations, confirmation content and refresh rules. Common can own selection presentation and invoke callbacks without implementing deletion or hardcoding endpoints.
5. Avoid parallel implementations of loading buttons, inputs, pagination or tables. Do not replace mature table/form capabilities with locally maintained implementations to obtain theme consistency.

## Audit of all ten Standard components

Production caller counts below are unique importing TSX files, excluding the component itself and tests. They are direct imports, not rendered-instance counts.

| Component | Production importing files | Current added responsibility | Decision |
| --- | ---: | --- | --- |
| StandardButton | 21 | Fixed 32px height, 4px radius, spacing and colors; disables CJK spacing; replaces AntD type/variant API | Remove after moving shared defaults to ConfigProvider. Migrate primary to native `type="primary"`, preserving disabled/loading/danger/link behavior. The current forced background classes should not become the brand mechanism. |
| StandardInput | 8 | Fixed 28px height, 4px radius and border | Replace with AntD Input after component tokens establish the approved defaults. Retain caller-specific differences through native props. |
| StandardPaginator | 5 | Font size, letter spacing and text color only | Replace with AntD Pagination; central theme covers the common defaults. Preserve controlled pagination and locale configuration. |
| StandardQuestionIcon | 1 | Exact forwarder of QuestionCircleOutlined | Remove and import the original icon directly. It adds no contract. |
| StandardCard | 2 | Borderless default and width/height/radius aliases over AntD Card | Remove after mapping actual callers to native variant/style props. Use Card component tokens for shared appearance; do not impose an accidental global borderless default. |
| StandardTable | 0 | Large descendant selectors and forced styles; no additional interaction | Remove the unused wrapper. Keep existing AntD business tables; centralize reusable appearance through Table tokens rather than this selector bundle. |
| StandardDrawer | 0 | Custom header/footer/close composition | No current production demand. Candidate for removal with its exclusively obsolete component fixtures after confirming no indirect usage. Do not invent callers to justify keeping it. |
| StandardModal | 2 | Controlled close requests, callback veto, common action layout, optional constrained scrolling, Escape behavior | Keep the meaningful contract. Simplify token-covered styles and button dependencies without removing close/scroll behavior. Rename only if a later API change makes that useful. |
| StandardCloseButton | 4 | Shared labeled close action and icon sizing | Retain as an internal shared action where useful; it is not an AntD pass-through. Review keyboard focus visibility and hit target rather than duplicating it in each modal. |
| StandardTour | 1 | Measured viewport clamping, observer cleanup, shared tour layout | Keep its real interaction contract. Domain targets and completion callbacks stay in the agent feature. Remove its local primary-color override when central theming is introduced. |

A production import from another common component is included in these counts. For example, StandardButton is used by StandardModal and StandardDrawer. Tests alone do not justify an unused production abstraction. Existing behavior evidence must be preserved or deliberately mapped when removing wrappers; no new test suite is requested for this restart.

CopyButton, ExpandEditModal and SliderStepper illustrate meaningful common capabilities: clipboard feedback/error handling, expanded editing with save/cancel/read-only behavior, and bounded slider/stepper interaction respectively. They are not equivalent to styling-only input wrappers. Their current implementations are retained pending any separate defects or domain-boundary findings.

## Theme findings

RootProvider currently supplies popup and mask defaults but no shared brand theme. Several nested ConfigProviders override primary colors independently (`agent-space`, `mcp-space`, `skill-space`, agent configuration and chat agent landing). Updating only RootProvider would leave these overrides active.

Use the approved Light brand palette from `xyq/update_skills` at `45cd133de`: brand-05 #E6F2FD, 10 #B8D9F9, 20 #8ABEF3, 30 #5CA2E9, 40 #2E86DE, 50 #0067D1, 60 #004EA8, 70 #003D83, 80 #002E6A, 90 #00214B. Default primary is brand-50, hover brand-40 and active brand-60. Selection surfaces are distinct from a solid checked-control accent. The base control radius is 4px; do not apply it blindly to every surface with a separate documented specification. No approved Dark palette is inferred.

Ant Design supports global and component tokens and inheritance through nested themes. Static message/notification/Modal methods do not inherit context in the same way; use the existing App/context APIs where theme inheritance is required. Reference: https://ant.design/docs/react/customize-theme/.

## Implementation scope

1. Introduce the central brand source and AntD theme in this clean baseline. Wire existing custom controls to matching semantic roles, remove conflicting nested primary overrides and verify actual hover/active/disabled states. Preserve unrelated layouts and API behavior.
2. Migrate and remove the five styling-only/pass-through wrappers (Button, Input, Paginator, QuestionIcon, Card), then remove the unused Table and assess the unused Drawer. Preserve native AntD props rather than introducing another compatibility API.
3. Retain and simplify meaningful compositions (Modal, close action, Tour, CopyButton, expanded editing, SliderStepper) based on their actual responsibilities. Keep business callbacks outside common.
4. Keep the existing agent AntD table and form. Move reusable table theme settings centrally. Extract resizing/selection presentation only when there is concrete shared demand; preserve AntD's table contract, fixed-column and scrolling behavior. The previous shadcn table, resize allocator and UI boundary tooling are not carried over.
5. Verify the changed surface with scoped static checks and direct visual interaction, respecting the user's request not to add frontend tests. Record what was actually checked; do not claim the old preview demonstrates the new branch.

## Assessment validation

Read every Standard implementation and searched TS/TSX references across frontend, including tests. Reviewed the root provider, nested theme locations, existing frontend architecture/component rules, and native AntD theme documentation. This restart assessment changes no application behavior, so application test suites are unnecessary for this document-only step.

## Delivery status (2026-11-05)

- Implemented central brand palette, native AntD theme/defaults and custom-control CSS variables from the same TypeScript source. Root theme also supplies legacy static portal styling. Nested primary overrides in repository pages, agent configuration, chat landing, onboarding and knowledge selection were removed; AIDP theme references the same source.
- Removed seven wrappers: StandardButton, StandardInput, StandardPaginator, StandardQuestionIcon, StandardCard, unused StandardTable and unused StandardDrawer. All production imports were migrated to native APIs. Existing wrapper-only assertions were removed; existing modal behavior and CJK spacing coverage were retained/adapted. No new tests were added or run, as requested.
- Retained StandardModal, StandardCloseButton and StandardTour, along with existing CopyButton, ExpandEditModal and SliderStepper. Modal uses native buttons; the shared close action now has a visible keyboard focus outline. Business services and callbacks remain in their original domains.
- The agents table remains AntD with original fixed action column, scrolling and feature-owned resizing. Its common theme settings moved to NEXENT_THEME; agent list brand literals use semantic variables. The previous migration's custom table and bulk operations were not copied into this clean baseline.
- Full TypeScript check passed. Copyright checks passed for the changed source files. Scoped ESLint reported 43 errors and 35 warnings; all seven error-bearing files were compared against HEAD, with identical per-file/per-rule error counts. These existing any/Hooks/display-name findings were not broadened into unrelated fixes. New theme/provider/common code has no lint errors.
- Browser confirmed authenticated agents loaded, switched grid/list presentation, opened and closed the creation modal without submitting, and read primary #0067D1, 32px button height and 4px radius from actual computed styles. Preview connects to config 5010 and runtime 5014. No product data was created or deleted.
- Screenshot: artifacts/checks/2026-11-05/agents-brand-common.png. Formal and unit suites were not executed, following the user's explicit frontend verification preference. No backend behavior or formal D1-D5 assets changed.

This is a central theming foundation and the agreed wrapper cleanup, not a claim that every historical page-local color in the repository has been audited or converted. Existing unrelated layouts remain.
