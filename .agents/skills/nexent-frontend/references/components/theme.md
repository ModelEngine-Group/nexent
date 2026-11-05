# Theme and component layers

- Use shadcn/ui Radix controls and Nexent brand-color. Do not install Radix Themes or change to Base UI by default.
- `frontend/styles/brand.css` owns primary, hover, active, focus and brand-soft values from the official light/dark palette. `globals.css` maps them to Tailwind semantic utilities. Primary/ring/sidebar-primary/sidebar-ring are complete CSS colors; remaining historical HSL-channel tokens retain their existing representation.
- ui primitives consume semantic theme tokens. Common components centralize reusable Nexent styling and interaction defaults; shared brand adaptation is a valid reason for this layer. Keep raw colors in shared tokens, reuse the canonical common component, and do not create a component per button color or override destructive/neutral variants with primary styling.
- `frontend/const/brand.ts` exposes the same official palette to the temporary Ant Design provider bridge. Nested legacy providers still require migration; do not claim all legacy colors are unified.
- Basic controls and presentation primitives live in `components/ui`. Shared behavior such as pending submission or controlled pagination lives in `components/common`. Domain requests, permissions and state stay in their domain. One-off compositions remain local.
- `common/Button` owns project button defaults and caller-owned loading state. Submit with explicit `type="submit"`; there is no separate SubmitButton. Domain selection controls use the same semantic primary/hover/active tokens. Primary light color is brand-50 (`#0067D1`); never override it with a legacy page-local blue.
- Standard compatibility adapters have been removed; use the canonical component APIs directly. The common directory has no Ant Design or @ant-design/icons imports. Do not recreate compatibility-only entry points. Business pages and domain components still require incremental migration.
- Run `npm run check:ui` to enforce component dependency layers. Legacy business consumers remain supported without a per-file import budget. Review updates to adopted shadcn/Radix sources before applying them.

- The source of truth is `xyq/update_skills` at `45cd133de`, `references/components/style.md` and `color-tokens.css`. `styles/brand.css` integrates the brand subset, retaining all ten raw brand shades and independent semantic roles.
- Default: brand-50 `#0067D1`; hover: brand-40 `#2E86DE`; selected: brand-50; pressed: brand-60 `#004EA8`; disabled: brand-20 `#8ABEF3`; soft selection: brand-05 `#E6F2FD`. Hover intentionally becomes lighter. Preserve actual disabled semantics and do not fade the whole primary control in addition to its disabled fill.
- The source defines Light only. The app currently inherits these brand roles in Dark; this is a fallback, not an approved Dark palette. Do not invent Dark color scales.
- Keyboard focus-visible uses the ring independently of persistent selected/checked state. Do not change upstream UI primitives to apply project colors.

- The current migration scope prioritizes ordinary controls under `/agents`. Retain existing Ant Design Table and Form behavior where it already meets requirements; full dependency removal is not a prerequisite for consistent brand styling. Keep the provider bridge while these consumers remain.
