---
name: nexent-frontend
description: Use when implementing, debugging, or reviewing Nexent frontend pages, React components, hooks, API services, TypeScript types, styling, or localization under frontend/. Includes UI requests without file paths. Skip backend-only work, Python tests, and documentation-only changes with no frontend behavior.
---

# Nexent frontend changes

Repository paths below are relative to the root; reference links resolve from this skill.

1. Read [architecture](references/architecture.md), the affected feature, and `frontend/package.json` before choosing APIs or dependencies. For frontend visual work, read the authoritative sibling document `../docs/前端ui.md` from the repository root when it is available, then apply the linked English component references.
2. Load relevant detailed rules only.

| Work                                                               | Reference                                                                                                                |
| ------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------ |
| Route entries, layouts, loading UI, localization                   | [Pages](references/pages.md)                                                                                             |
| Components, visual layout, forms, modals, icons, user-visible copy | [Components and UI](references/components-ui.md), then the relevant documents under [components](references/components/) |
| State, effects, shared API data, mutations                         | [Hooks](references/hooks.md)                                                                                             |
| Requests, responses, endpoint configuration                        | [API services](references/api-services.md)                                                                               |
| Shared types, constants, runtime guards                            | [Types](references/types.md)                                                                                             |

3. Keep route entries thin, reuse existing shared UI, and extract abstractions when reuse or complexity warrants it.
4. Verify affected behavior, including loading/error states and localization for UI changes. Select checks from `frontend/package.json`; use `npm run check-all` for broad verification when warranted. Do not install dependencies solely because obsolete examples name them.
5. Report references consulted, checks run, and blocked checks. Do not enforce these conventions by changing unrelated legacy code.

## UI source synchronization

- Treat `../docs/前端ui.md` as the visual source of truth. Do not invent visual values that it does not define; use the existing frontend references only for unspecified defaults.
- Translate every first-level heading into one English Markdown reference under `references/components/`; keep nested headings in that reference.
- Convert documented visual values to Tailwind CSS in the reference and implement reusable components under `frontend/components/common/` when the source defines a reusable component contract.
- Keep user-facing default text localized through the existing translation namespace. Create component test pages only as explicitly requested temporary local debug entries; do not add them to Nexent feature routes or navigation, and remove them after debugging is complete.
