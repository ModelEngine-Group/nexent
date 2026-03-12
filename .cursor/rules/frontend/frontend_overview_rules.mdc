---
globs: frontend/**/*.{ts,tsx}
description: Frontend overview - directory structure, layer responsibilities, and dependency rules
alwaysApply: false
---

# Frontend Overview

## Directory Structure

```
frontend/
├── app/[locale]/              # Routes with i18n (Next.js App Router)
│   ├── layout.tsx, page.tsx    # Root layout and home
│   ├── i18n.tsx                # i18n config
│   └── {feature}/              # e.g. chat, agents, knowledges, models
│       ├── page.tsx            # Page entry (thin wrapper)
│       ├── components/         # Feature-specific components
│       └── {submodule}/        # e.g. versions/
├── components/                 # Cross-feature reusable components
│   ├── auth/                   # Auth-related UI
│   ├── providers/              # Global context providers
│   └── ...                     # Base UI: use Ant Design; avoid custom wrappers
├── hooks/                      # Custom hooks (organized by domain)
│   ├── auth/                   # useSessionManager, useAuthentication, etc.
│   ├── agent/                  # useAgentList, useAgentInfo, etc.
│   ├── chat/                   # useConversationManagement, etc.
│   └── ...
├── services/                   # API calls (api.ts, *Service.ts)
├── lib/                        # Utilities (logger, session, utils, etc.)
├── types/                      # Shared type definitions
├── const/                      # Constants and config
├── stores/                     # Global state stores (if any)
├── styles/                     # Global styles (theme, reset, AntD overrides)
└── public/                     # Static assets
```

## Layer Responsibilities

| Directory | Purpose | Notes |
|-----------|---------|-------|
| `app/[locale]/{feature}/page.tsx` | Route entry, auth guard, config load | Thin wrapper; delegate UI to internal/components |
| `app/.../components/` | Feature-only UI pieces | Ant Design first; Lucide icons primary, `@ant-design/icons` fallback |
| `components/` | Shared UI across features | Ant Design first; Lucide icons primary, `@ant-design/icons` fallback |
| `hooks/` | State and side-effects | Shared API data: use TanStack React Query (`useQuery`); client-side filter/sort: `useMemo` on query data; mutations: `useMutation` + `queryClient.invalidateQueries` |
| `services/` | API calls | — |
| `lib/` | Pure utilities | — |
| `types/` | Type definitions only | `interface`, `type` only; do not store constants |
| `const/` | Runtime constants | Literals, enums, config objects, status codes; do not store `interface`/`type` |
| `styles/` | Global styles | Theme vars, reset, AntD overrides only; component-specific CSS: colocate in component (e.g. `*.module.css`) |

## General Principles

- **Avoid over-engineering**: Before abstracting code (extracting hooks, components, utils), confirm there is a concrete need (reuse, testability, or complexity). Prefer simple, inline solutions until the need is clear.

## Dependency Rules

- **No cross-feature imports**: Feature-level code (`components/` under a feature) must not import from other features. Use shared `components/` for cross-feature reuse.
- **Infrastructure does not depend on UI**: `services/`, `lib/`, `types/` must not import from `app/` or `components/`.
- **Minimize CSS**: Prefer Tailwind + Ant Design. Use CSS only when necessary; keep component-specific styles colocated (e.g. `*.module.css` next to the component).

## Path Aliases

- `@/*` → `frontend/*`
- `@/app/*` → `frontend/app/[locale]/*` (import without `[locale]` segment)

Example: `import { ChatInterface } from "@/app/chat/internal/chatInterface"`

## Where to Put New Code

| If you are adding... | Put it in |
|----------------------|-----------|
| A new route | `app/[locale]/{feature}/page.tsx` |
| Core feature logic | `app/[locale]/{feature}/internal/` |
| UI used only by one feature | `app/[locale]/{feature}/components/` |
| UI used by multiple features | `components/` (auth/, providers/, etc.); base UI from Ant Design |
| State/effect logic | `hooks/{domain}/` |
| API call | `services/` |
| Pure helper | `lib/` |
| Shared type | `types/` |
| Shared constant value | `const/` |
| Global styles (theme, reset) | `styles/` |
