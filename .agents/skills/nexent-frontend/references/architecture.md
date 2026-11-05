# Frontend architecture

- `app/[locale]/{feature}/page.tsx` is a thin entry for routing, auth/configuration, and feature composition. Substantial feature logic follows the feature's existing internal structure.
- Feature-only UI belongs in `app/[locale]/{feature}/components/`; cross-feature UI belongs in `components/`. Auth UI uses `components/auth/`; providers use `components/providers/`.
- Feature code must not import another feature's private code. Promote genuine reuse into shared modules.
- Apply the [component layers](#component-layers): upstream primitives in ui, shared brand adaptations and reusable interactions in common, and business composition in the appropriate domain.
- The Nexent brand-color uses semantic tokens from `styles/brand.css`; see [theme.md](components/theme.md).
- `hooks/{domain}/` owns reusable state/effects; `services/` owns API calls; `lib/` owns utilities. `services/`, `lib/`, and `types/` must not depend on `app/` or `components/`.
- `types/` contains exported interfaces/type aliases. Runtime constants, enums, config, and status values belong in `const/`; executable guards belong in `lib/` or an appropriate runtime module.
- `styles/` contains global theme/reset/AntD overrides. Colocate necessary component CSS; use shadcn/Radix and semantic Tailwind utilities for migrated UI.
- Use `frontend/lib/logger.ts` for logging, never direct `console.log` in new or changed code.
- `frontend/tsconfig.json` maps `@/*` to `frontend/*` and `@/app/*` to `frontend/app/[locale]/*`; omit `[locale]` with the latter alias.
- Shared client API data uses TanStack React Query, derived filter/sort uses `useMemo`, and mutations use `useMutation` with relevant query invalidation.
- Keep abstractions proportional to concrete reuse, complexity, or testability needs.

## Component decision before implementation

Apply this workflow before implementing or changing any frontend UI, whether it is a business page, feature component or shared control. Component choice, brand adaptation and reuse are implementation inputs, not a refactoring exercise left until after the page is built.

1. **Identify the requirement.** Establish the needed presentation, interactions, states and business responsibilities. Check the Nexent theme/component references for brand defaults instead of inventing page-specific styling.
2. **Inspect existing components.** Search `components/common`, `components/ui` and the relevant references; read the actual props and implementation of candidates. Distinguish upstream capabilities from project additions and unimplemented plans. Do not assume a familiar component name proves coverage.
3. **Reuse when covered.** If common already satisfies the requirement, use it directly. If a ui primitive satisfies it without further project adaptation, use that primitive directly; semantic theme tokens may already supply the required brand color.
4. **Extend common when appropriate.** If an existing common component is close but lacks a reusable styling or interaction capability, extend its contract and migrate the caller to that capability. Keep existing consumers compatible where possible. Avoid repeatedly overriding the same component in pages, copying it into a feature, or introducing a parallel common implementation for a minor difference.
5. **Create common when needed.** If no suitable common component exists and the requirement needs reusable Nexent styling, defaults or interactions, compose/adapt existing ui primitives in a new common component. Add missing upstream primitives on demand from shadcn/ui with reviewed source changes. A concrete shared project contract can justify the first common implementation; it need not wait for duplicated page code. A pure rename or speculative abstraction does not justify one.
6. **Compose the business scenario.** The feature consumes the selected common/ui components and provides its data, business conditions and operation callbacks. Keep one-off domain composition local rather than forcing every requirement into common.

Briefly explain the selected component, the coverage gap and the adaptation location in the existing implementation reasoning. This is a coding decision, not a mandatory new document, global component audit or user-approval step. When more than one approach fits, choose the smallest coherent contract that meets the current requirement.

## Component layers

1. **Upstream primitives — `components/ui/`.** Add shadcn/ui Radix components only as needed. Maintain the adopted sources directly without duplicate snapshots or a synchronization manifest. Review upstream changes before applying them and preserve the MIT license in `frontend/components/ui/LICENSE.md`. Brand and business changes do not belong here.
2. **Project components — `components/common/`.** Compose/adapt ui primitives to provide reusable Nexent colors, styling, defaults and interactions. Shared brand presentation is meaningful value even without business logic. Centralize these adaptations so later business pages reuse the same contract. Extend capabilities when concrete requirements justify them, without trying to anticipate every future scenario.
3. **Business composition — domain directories.** Feature-local components and domain directories such as `components/agent`, `components/chat` and `components/resources` own domain content, data, conditions and callbacks. Prefer the applicable common component; extend its reusable contract instead of copying presentation or interaction logic into another page. Direct ui use is valid when no project adaptation is needed. Do not recreate a shared directory or Standard compatibility layer.

### Generic interaction and business execution

Common may own transient interaction state, expose controlled state/change callbacks, render configurable action areas, and invoke supplied callbacks. Business callers provide data, labels, eligibility, pending/disabled conditions and operation implementations. Common must not hardcode domain-specific endpoints, permission rules, confirmation copy or refresh logic. Use props, slots and callbacks to expose the reusable capability; keep domain execution in the owning feature/services/hooks.

### Proportional reuse

Do not require a common wrapper around every ui primitive, create several components for different colors/actions of the same control, or add speculative options without a real use. When creating or extending common, make its shared presentation/interaction value and state/callback ownership explicit. Preserve agreed behavior when simplifying styles; a visual comparison alone does not authorize removing interaction capabilities.
