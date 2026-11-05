# Components and UI

- Use TypeScript functional components with typed prop interfaces. Prefer controlled components and appropriate defaults for optional props.
- Keep local state local. Use Context for cross-cutting state, composition for nested content/callbacks, and hooks for shared logic. Around 7 to 10 props or repeated pass-through layers is a signal to review the interface, not an automatic rewrite requirement.
- Keep component files below roughly 1,000 lines; extract cohesive colocated subcomponents/hooks as complexity grows. Group props only when they form a coherent concern.

## Component organization and references

Before implementing any UI, follow the [component decision workflow](architecture.md#component-decision-before-implementation): inspect common/ui coverage, assess brand adaptation, and choose reuse, common extension or a new meaningful common component before writing business-specific UI.

- Put cross-feature UI in `frontend/components/`. Put feature-only UI in `frontend/app/[locale]/{feature}/components/`; do not import another feature's private components. Promote genuinely reusable UI into the shared component area.
- Keep reusable components focused on presentation and interaction. Put API calls in `frontend/services/`, reusable state/effects in `frontend/hooks/`, and shared types in `frontend/types/` instead of coupling a shared component to a feature page.
- Detailed component constraints and component-specific Markdown references live under `references/components/`. Read this file first, then read the relevant document in that directory before creating, changing, or reviewing a component.
- Keep all UI color specification categories together in [UI specification](components/style.md). For other authoritative UI source material, create one English Markdown document for each first-level heading and keep nested sections and their constraints in that same document.
- When a component has non-obvious public API, state ownership, interaction, accessibility, or styling constraints, add or update its corresponding Markdown reference under `references/components/`.
- Use [component-contracts.md](components/component-contracts.md) as the baseline for new component documentation and review decisions. Keep component-specific documents focused on constraints that are not already covered by this file.

## Authoritative UI source

- For visual component work, use `../docs/前端ui.md` relative to the repository root as the source of truth when it is available. Do not add visual rules that are not stated there.
- Follow [theme.md](components/theme.md) for the approved Nexent brand-color and shadcn/Radix component layers. Keep user-facing text localized. Legacy references requiring Ant Design apply only to unmigrated components until their contract is replaced.
- For complete color categories and interaction states, consult the single [UI specification](components/style.md) and its shared color tokens, subject to the approved theme overrides.
- Use the reusable components documented by [button.md](components/button.md) and [drawer.md](components/drawer.md) instead of recreating their contracts in feature code.
- Use the reusable components documented by [modal.md](components/modal.md), [card.md](components/card.md), [icon.md](components/icon.md), [paginator.md](components/paginator.md), and [input.md](components/input.md) instead of recreating their contracts in feature code.

## Visual conventions

- Use shadcn/ui's Radix controls for new and migrated components. Keep Ant Design only in explicitly unmigrated consumers, without expanding the recorded import budget. Prefer applicable common components for shared project styling and interactions; avoid wrappers that only rename or forward an unchanged primitive.
- Use semantic HTML and Tailwind for new layouts. Existing AntD Layout/Grid and scoped legacy overrides remain during incremental migration.
- Use theme tokens/CSS variables, responsive layouts, accessible focus states, and necessary error boundaries. Colocate component CSS.
- Prefer `lucide-react`; do not add new `@ant-design/icons` imports.
- Use common Radix `Modal` for new shared content; existing unmigrated consumers may retain `frontend/hooks/useConfirmModal.ts` for simple confirmations. Use `common.cancel` / `common.confirm` translation keys. Destructive confirmations use a primary danger button and the established warning icon/title layout; ordinary actions should not inherit destructive styling from the old delete example.

## Copy and behavior

- Localize user-facing text through `useTranslation`, with descriptive keys grouped by feature/namespace and the project's fallback behavior. Use `Trans` for structured/rich translated text.
- Provide meaningful async loading/error states. Log through `frontend/lib/logger.ts`.
- Check interactions, narrow-screen layout, focus, and localized text. Keep handlers/labels consistent when extracting components.

## Component layers

Follow the [architecture contract](architecture.md#component-layers). Keep ui sources upstream-native, put shared brand styling/defaults and generic interaction capabilities in common, and keep business execution in domain components. Business pages should not repeatedly redefine presentation already owned by common. Extend common for real reusable requirements; use ui directly where no adaptation is needed.
