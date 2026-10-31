# Components and UI

- Use TypeScript functional components with typed prop interfaces. Prefer controlled components and appropriate defaults for optional props.
- Keep local state local. Use Context for cross-cutting state, composition for nested content/callbacks, and hooks for shared logic. Around 7 to 10 props or repeated pass-through layers is a signal to review the interface, not an automatic rewrite requirement.
- Keep component files below roughly 1,000 lines; extract cohesive colocated subcomponents/hooks as complexity grows. Group props only when they form a coherent concern.

## Component organization and references

- Put cross-feature UI in `frontend/components/`. Put feature-only UI in `frontend/app/[locale]/{feature}/components/`; do not import another feature's private components. Promote genuinely reusable UI into the shared component area.
- Keep reusable components focused on presentation and interaction. Put API calls in `frontend/services/`, reusable state/effects in `frontend/hooks/`, and shared types in `frontend/types/` instead of coupling a shared component to a feature page.
- Detailed component constraints and component-specific Markdown references live under `references/components/`. Read this file first, then read the relevant document in that directory before creating, changing, or reviewing a component.
- Create one English Markdown document for each first-level heading in the authoritative UI source. Keep nested sections and their constraints in that same document; do not split child headings into separate component documents.
- When a component has non-obvious public API, state ownership, interaction, accessibility, or styling constraints, add or update its corresponding Markdown reference under `references/components/`.
- Use [component-contracts.md](components/component-contracts.md) as the baseline for new component documentation and review decisions. Keep component-specific documents focused on constraints that are not already covered by this file.

## Authoritative UI source

- For visual component work, use `../docs/前端ui.md` relative to the repository root as the source of truth when it is available. Do not add visual rules that are not stated there.
- Translate every documented visual value into Tailwind CSS in the English component references. Keep user-facing text localized and use Ant Design first for component behavior.
- Use the reusable components documented by [button.md](components/button.md) and [drawer.md](components/drawer.md) instead of recreating their contracts in feature code.
- Use the reusable components documented by [modal.md](components/modal.md), [card.md](components/card.md), [icon.md](components/icon.md), [paginator.md](components/paginator.md), and [input.md](components/input.md) instead of recreating their contracts in feature code.

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
