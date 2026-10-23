---
name: nexent-frontend
description: Use when implementing, debugging, or reviewing Nexent frontend pages, React components, hooks, API services, TypeScript types, styling, or localization under frontend/. Includes UI requests without file paths. Skip backend-only work, Python tests, and documentation-only changes with no frontend behavior.
---

# Nexent frontend changes

Repository paths below are relative to the root; reference links resolve from this skill.

1. Read [architecture](references/architecture.md), the affected feature, and `frontend/package.json` before choosing APIs or dependencies.
2. Load relevant detailed rules only.

| Work | Reference |
| --- | --- |
| Route entries, layouts, loading UI, localization | [Pages](references/pages.md) |
| Components, visual layout, forms, modals, icons, user-visible copy | [Components and UI](references/components-ui.md) |
| State, effects, shared API data, mutations | [Hooks](references/hooks.md) |
| Requests, responses, endpoint configuration | [API services](references/api-services.md) |
| Shared types, constants, runtime guards | [Types](references/types.md) |

3. Keep route entries thin, reuse existing shared UI, and extract abstractions when reuse or complexity warrants it.
4. Verify affected behavior, including loading/error states and localization for UI changes. Select checks from `frontend/package.json`; use `npm run check-all` for broad verification when warranted. Do not install dependencies solely because obsolete examples name them.
5. Report references consulted, checks run, and blocked checks. Do not enforce these conventions by changing unrelated legacy code.
