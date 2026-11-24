# Pages and localization

- User-facing pages participate in `[locale]` routing. Use `page.tsx`, `layout.tsx`, and `loading.tsx` for their App Router roles; new route segments use kebab-case.
- Make `page.tsx` express the page as a whole. Keep the overall structure, the composition of its main sections, and page-wide interactions visible there. For example, a tabbed page can define its tabs and manage tab switching in `page.tsx` while composing their content.
- Keep straightforward page-specific content inline. Extract a section into a feature component when its complexity, reuse, or need for independent testing justifies a separate component. A page that can be expressed directly in `page.tsx` needs no separate page component.
- Prefer nested layouts to passing layout state through many levels.
- Use existing `react-i18next` / i18next integration. Inspect `frontend/app/[locale]/i18n.tsx`, locale providers, and nearby routes. The project does not declare `next-intl`; do not copy the former Cursor import example.
- Client components use `useTranslation` and descriptive feature/namespace keys. Server Components must use the current server-compatible locale-loading path, not client hooks.
- Prefer Server Components for initial fetching where compatible with the route; set server fetch caching deliberately. Client fetching belongs in hooks using shared-query conventions.
- Provide loading/error states, keep page-specific state local, and use Context/custom hooks for shared state.
- Use Next.js metadata APIs in server-compatible layouts or page exports when needed. Preserve responsive layout and log through `frontend/lib/logger.ts`.
