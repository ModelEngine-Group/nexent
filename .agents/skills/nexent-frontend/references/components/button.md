# Buttons

- `components/ui/button.tsx` is the adopted shadcn/Radix primitive. Do not change it for project defaults.
- `components/common/Button.tsx` is the single project implementation: 40px default height, normal tracking, pointer cursor, brand-color hover/active tokens, safe `type="button"`, optional icon and loading state. Loading disables the native button and exposes `aria-busy`; callers own requests.
- Submit with `<Button type="submit" loading={pending}>`. There is no separate SubmitButton component.
- StandardButton has been removed. Migrated callers explicitly select `variant="outline"` or `variant="default"`, shadcn sizes and native `type`. Button supports `href` with disabled/loading link guards.
- CopyButton belongs in `components/common` because it owns clipboard interaction and localized feedback, rather than another button theme.
- Color and size are variants/props, not separate component files. Domain controls are justified by behavior (clipboard or sidebar toggling) or a reused domain layout. Bare close icons use Button directly.
