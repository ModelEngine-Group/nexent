# Components and UI

- Use TypeScript functional components with typed prop interfaces. Prefer controlled components and appropriate defaults for optional props.
- Keep local state local. Use Context for cross-cutting state, composition for nested content/callbacks, and hooks for shared logic. Around 7 to 10 props or repeated pass-through layers is a signal to review the interface, not an automatic rewrite requirement.
- Keep component files below roughly 1,000 lines; extract cohesive colocated subcomponents/hooks as complexity grows. Group props only when they form a coherent concern.

## Visual conventions

- Use Ant Design first for forms, data display, buttons, modals, and complex interactions. Avoid unnecessary wrappers around base controls.
- Prefer AntD Layout (`Header`, `Sider`, `Content`, `Footer`), responsive Grid, and Flex where appropriate. Tailwind handles modest spacing/layout/styling. Special inline styles and scoped global AntD overrides remain available when necessary.
- Use theme tokens/CSS variables, responsive layouts, accessible focus states, and necessary error boundaries. Colocate component CSS.
- Prefer `lucide-react`; use `@ant-design/icons` when an equivalent Lucide icon is unavailable.
- Use centered AntD `Modal` for custom content and `frontend/hooks/useConfirmModal.ts` for simple confirmations. Use `common.cancel` / `common.confirm` translation keys. Destructive confirmations use a primary danger button and the established warning icon/title layout; ordinary actions should not inherit destructive styling from the old delete example.

## Copy and behavior

- Localize user-facing text through `useTranslation`, with descriptive keys grouped by feature/namespace and the project's fallback behavior. Use `Trans` for structured/rich translated text.
- Provide meaningful async loading/error states. Log through `frontend/lib/logger.ts`.
- Check interactions, narrow-screen layout, focus, and localized text. Keep handlers/labels consistent when extracting components.
