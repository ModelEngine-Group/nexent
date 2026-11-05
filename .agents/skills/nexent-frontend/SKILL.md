---
name: nexent-frontend
description: Use when implementing, debugging, or reviewing Nexent frontend pages, React components, hooks, API services, TypeScript types, styling, or localization under frontend/. Includes UI requests without file paths. Skip backend-only work, Python tests, and documentation-only changes with no frontend behavior.
---

# Nexent frontend changes

Repository paths below are relative to the root; reference links resolve from this skill.

1. Read [architecture](references/architecture.md), the affected feature, and `frontend/package.json` before choosing APIs or dependencies. For frontend visual work, read [the theme contract](references/components/theme.md) and the relevant English component references. The approved shadcn/Radix migration and Nexent brand-color supersede legacy Ant Design implementation and fixed primary colors; preserve unaffected business layouts and behavior. For the complete color categories and interaction states, also consult the single [UI specification](references/components/style.md) and its [color tokens](references/components/color-tokens.css).
2. Load relevant detailed rules only.

| Work                                                               | Reference                                                                                                                |
| ------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------ |
| Route entries, layouts, loading UI, localization                   | [Pages](references/pages.md)                                                                                             |
| Components, visual layout, forms, modals, icons, user-visible copy | [Components and UI](references/components-ui.md), then the relevant documents under [components](references/components/) |
| State, effects, shared API data, mutations                         | [Hooks](references/hooks.md)                                                                                             |
| Requests, responses, endpoint configuration                        | [API services](references/api-services.md)                                                                               |
| Shared types, constants, runtime guards                            | [Types](references/types.md)                                                                                             |

3. Before writing frontend UI, follow the [component decision workflow](references/architecture.md#component-decision-before-implementation): inspect existing common/ui components, assess requirement coverage and brand adaptation, then choose reuse, extension or a new shared component. Make this decision before implementing the business page, not as cleanup afterward. Keep route entries thin.
4. Verify affected behavior, including loading/error states and localization for UI changes. Select checks from `frontend/package.json`; use `npm run check-all` for broad verification when warranted. Do not install dependencies solely because obsolete examples name them.
5. Report references consulted, checks run, and blocked checks. Do not enforce these conventions by changing unrelated legacy code.

## UI source synchronization

- Use shadcn/ui's Radix implementation for new basic UI. Nexent brand-color supplies the brand palette through semantic theme variables; do not introduce Radix Themes or Base UI.
- Translate every first-level heading into one English Markdown reference under `references/components/`; keep nested headings in that reference.
- Follow the [three component layers](references/architecture.md#component-layers): preserve upstream ui sources, centralize shared brand presentation and generic interactions in common, and compose business behavior in its domain. Prefer an existing common component over repeating its adaptations in pages.
- Maintain adopted shadcn/Radix component sources directly; do not store duplicate upstream snapshots, a synchronization manifest or a per-file legacy import budget. Preserve the MIT license in `frontend/components/ui/LICENSE.md`. Review upstream updates before applying them. Run `npm run check:ui` and relevant component/tool tests when changing these boundaries.
- Keep all color specification categories in the single [UI specification](references/components/style.md), with shared values in [color tokens](references/components/color-tokens.css). The [theme contract](references/components/theme.md) defines the approved migration overrides; preserve documented roles outside that scope.
- Extract visual rules into text and tables; do not retain uploaded screenshots in maintained skill documentation.
- Keep user-facing default text localized through the existing translation namespace. Create component test pages only as explicitly requested temporary local debug entries; do not add them to Nexent feature routes or navigation, and remove them after debugging is complete.

## Component decision before implementation

For every frontend UI change, first inspect the actual components and contracts in `components/common` and `components/ui`. Decide:

1. Can an existing common component cover the required appearance and behavior as-is?
2. If only an upstream shadcn/ui primitive covers it, does the requirement need Nexent brand styling, defaults or shared interactions?
3. If common falls short, can its existing contract be extended cleanly instead of adding page-local overrides or a parallel component?
4. If there is no suitable common component but project adaptation is needed, should a new common component compose/adapt the ui primitives?

Prefer the existing common component when it fits. Direct ui use is appropriate when no project adaptation is needed. Create or extend common for meaningful project-wide presentation/interaction needs, then let business components consume it; keep genuinely domain-specific composition local. Record the choice briefly in the normal implementation reasoning, without adding a separate approval gate. See [the workflow and decision criteria](references/architecture.md#component-decision-before-implementation).

## Component layers

- `components/ui`: add shadcn/ui Radix primitives on demand, pin their provenance and periodically review upstream updates. Keep source adaptations limited to import paths, copyright headers and formatting.
- `components/common`: own reusable Nexent brand styling, defaults and generic interactions. Evolve the shared contract to meet real requirements rather than repeatedly adapting primitives inside business pages.
- Business components: compose the chosen components and supply domain data, conditions and operation callbacks.

See [architecture](references/architecture.md#component-layers) for ownership boundaries and the relevant component reference for its actual implemented capabilities.
