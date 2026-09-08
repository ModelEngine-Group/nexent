# Frontend architecture

- `app/[locale]/{feature}/page.tsx` is a thin entry for routing, auth/configuration, and feature composition. Substantial feature logic follows the feature's existing internal structure.
- Feature-only UI belongs in `app/[locale]/{feature}/components/`; cross-feature UI belongs in `components/`. Auth UI uses `components/auth/`; providers use `components/providers/`.
- Feature code must not import another feature's private code. Promote genuine reuse into shared modules.
- `hooks/{domain}/` owns reusable state/effects; `services/` owns API calls; `lib/` owns utilities. `services/`, `lib/`, and `types/` must not depend on `app/` or `components/`.
- `types/` contains exported interfaces/type aliases. Runtime constants, enums, config, and status values belong in `const/`; executable guards belong in `lib/` or an appropriate runtime module.
- `styles/` contains global theme/reset/AntD overrides. Colocate necessary component CSS; prefer Ant Design with modest Tailwind layout/spacing utilities.
- Use `frontend/lib/logger.ts` for logging, never direct `console.log` in new or changed code.
- `frontend/tsconfig.json` maps `@/*` to `frontend/*` and `@/app/*` to `frontend/app/[locale]/*`; omit `[locale]` with the latter alias.
- Shared client API data uses TanStack React Query, derived filter/sort uses `useMemo`, and mutations use `useMutation` with relevant query invalidation.
- Keep abstractions proportional to concrete reuse, complexity, or testability needs.
