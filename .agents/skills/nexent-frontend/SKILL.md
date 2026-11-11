---
name: nexent-frontend
description: Use when implementing, debugging, or reviewing Nexent frontend pages, React components, hooks, API services, TypeScript types, styling, or localization under frontend/. Includes UI requests without file paths. Skip backend-only work, Python tests, and documentation-only changes with no frontend behavior.
---

# Nexent frontend changes

Repository paths below are relative to the root; reference links resolve from this skill.

1. Read [architecture](references/architecture.md), the affected feature, and `frontend/package.json` before choosing APIs or dependencies. For frontend visual work, read the authoritative sibling document `../docs/前端ui.md` from the repository root when it is available, then apply the linked English component references. For colors and interaction states, also read [UI specification](references/components/style.md), which consolidates UI color rules, including functional-color Light state tables, in one document. Use [brand theme](references/components/theme.md) for the existing application theme integration.
2. Load relevant detailed rules only.

| Work                                                               | Reference                                                                                                                |
| ------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------ |
| Route entries, layouts, loading UI, localization                   | [Pages](references/pages.md)                                                                                             |
| Components, visual layout, forms, modals, icons, user-visible copy | [Components and UI](references/components-ui.md), then the relevant documents under [components](references/components/) |
| State, effects, shared API data, mutations                         | [Hooks](references/hooks.md)                                                                                             |
| Requests, responses, endpoint configuration                        | [API services](references/api-services.md)                                                                               |
| Shared types, constants, runtime guards                            | [Types](references/types.md)                                                                                             |

3. Before implementing UI, inspect native component capabilities, central theme coverage and existing common contracts. Prefer native Ant Design with theme tokens when it covers the requirement. Extend/create common only for a concrete reusable composition or interaction; keep business data, permissions, API execution and refresh callbacks in the feature. See [architecture](references/architecture.md#theme-and-common-ownership).
4. Verify affected behavior, including loading/error states and localization for UI changes. Select checks from `frontend/package.json`; use `npm run check-all` for broad verification when warranted. Do not install dependencies solely because obsolete examples name them.
5. Report references consulted, checks run, and blocked checks. Do not enforce these conventions by changing unrelated legacy code.

## UI source synchronization

- Treat `../docs/前端ui.md` as the visual source of truth. Do not invent visual values that it does not define; use the existing frontend references only for unspecified defaults.
- The single [UI specification](references/components/style.md) contains UI-role, chart-color, gradient, company-palette, software-product, auxiliary-color, and functional-color Light rules. It supplements the existing UI source. If specifications explicitly disagree on the same property, report the discrepancy before applying that conflicting value; do not silently replace either specification.
- Keep all UI color specification categories in the single [UI specification](references/components/style.md); do not split them into separate documents. For other UI source material, translate every first-level heading into one English Markdown reference under `references/components/` and keep nested headings in that reference.
- Extract visual rules into text and tables; do not retain uploaded screenshots or reference them in maintained skill documentation.
- Define all documented color roles as shared CSS variables using [color tokens](references/components/color-tokens.css); add missing variables in the application global stylesheet and consume them in components instead of color literals. Keep the CSS definitions synchronized with the specification.
- Convert documented visual values to Tailwind CSS in the reference and implement reusable components under `frontend/components/common/` when the source defines a reusable component contract.
- Keep user-facing default text localized through the existing translation namespace. Create component test pages only as explicitly requested temporary local debug entries; do not add them to Nexent feature routes or navigation, and remove them after debugging is complete.
