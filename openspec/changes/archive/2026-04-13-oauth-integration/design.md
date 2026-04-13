## Context

Nexent currently uses **Supabase Auth** for email + password authentication. The auth flow is:

1. User signs up/in via `POST /api/user/signin` or `POST /api/user/signup`
2. Backend calls Supabase Auth SDK (`client.auth.sign_in_with_password` / `client.auth.sign_up`)
3. Supabase returns JWT access_token + refresh_token
4. Tokens are set as HttpOnly cookies by `server.js` proxy (via Set-Cookie header)
5. Frontend stores user display info (id, email, role) in localStorage
6. All subsequent API requests include cookies automatically (same-origin)
7. Backend validates JWT via `get_current_user_id()` using `SUPABASE_JWT_SECRET`
8. User-tenant relationship is stored in `user_tenant_t` (PostgreSQL) with user_id, tenant_id, user_role, user_email

**Key constraints:**
- Supabase is the identity provider (user records live in Supabase `auth.users`)
- JWT tokens are signed by Supabase's GoTrue service
- Session management is cookie-based (HttpOnly), not localStorage tokens
- Frontend uses `AuthenticationProvider` context for auth state
- Login UI is modal-based (`AuthDialogs.tsx`), not a separate page
- Roles: SU, ADMIN, DEV, USER, SPEED (stored in `user_tenant_t.user_role`)
- Multi-tenant: users belong to tenants via `user_tenant_t`

## Goals / Non-Goals

**Goals:**
- Support GitHub OAuth 2.0 login (authorization code flow)
- Support WeChat OAuth 2.0 login (WeChat uses a slightly different OAuth2 flow with separate access_token and userinfo steps)
- OAuth login MUST produce the same Supabase JWT session as email login (transparent to downstream code)
- Allow users to link/unlink OAuth providers from their account settings
- Auto-create accounts for new OAuth users with default USER role
- Auto-link OAuth identity if the provider email matches an existing user
- Provider-agnostic design: easy to add more OAuth providers in the future

**Non-Goals:**
- OAuth-based API authentication (we already have AK/SK for that)
- Replacing Supabase Auth as the identity provider
- OpenID Connect discovery protocol
- Enterprise SSO (SAML)
- OAuth login for the Docker deployment setup wizard (only for authenticated users)
- Mobile app OAuth flows (only web for now)

## Decisions

### Decision 1: Use Supabase Auth native OAuth over custom implementation

**Choice:** Configure OAuth providers in Supabase dashboard and use Supabase's built-in OAuth endpoints.

**Rationale:**
- Supabase Auth already supports GitHub and WeChat OAuth natively
- Using native Supabase OAuth means the JWT tokens are identical to email login tokens
- No need for a separate `authlib` dependency or custom token management
- Session refresh, logout, and token validation remain unchanged
- The `server.js` proxy cookie handling works unchanged

**Alternative considered:** Custom OAuth with `authlib` library, where we exchange the OAuth code ourselves, create a Supabase user via admin API, and issue tokens manually. Rejected because it duplicates Supabase's built-in functionality and adds complexity for token lifecycle management.

**Implementation approach:**
- Configure GitHub and WeChat OAuth apps in Supabase dashboard (Client ID, Client Secret, callback URL)
- Backend exposes `/api/user/oauth/authorize` that redirects to Supabase's OAuth URL (`SUPABASE_URL/auth/v1/authorize?provider=github`)
- Supabase handles the full OAuth flow and redirects to our callback URL
- Backend callback endpoint receives the Supabase session tokens, sets cookies via `server.js`, and creates `user_tenant_t` record if needed

### Decision 2: OAuth callback handled by backend, not frontend

**Choice:** The OAuth redirect goes through the backend (`/api/user/oauth/callback`), which sets the HttpOnly cookies and redirects the browser to the frontend.

**Rationale:**
- Consistent with existing pattern where `server.js` manages cookies
- Supabase's PKCE flow requires server-side token exchange
- Frontend never handles raw tokens (security best practice)
- Clean separation: backend handles auth, frontend handles UI

**Flow:**
1. Frontend: `window.location.href = '/api/user/oauth/authorize?provider=github'`
2. Backend: 302 redirect to `SUPABASE_URL/auth/v1/authorize?provider=github&redirect_to=BACKEND_CALLBACK`
3. User authorizes on GitHub/WeChat
4. Supabase redirects to our backend callback with session tokens (access_token, refresh_token in URL fragment or query)
5. Backend extracts tokens, creates user_tenant record if needed, sets HttpOnly cookies
6. Backend 302 redirects browser to frontend (e.g., `/chat`)
7. Frontend reads user info from localStorage (set by existing login flow) or fetches via `/api/user/current_user_info`

### Decision 3: New `user_oauth_account_t` table for provider linking

**Choice:** Create a new database table to track which OAuth providers are linked to which users.

**Rationale:**
- Enables account linking/unlinking functionality
- Supports multiple providers per user (e.g., GitHub + WeChat)
- Independent of Supabase's internal identity tracking
- Allows admin visibility into which providers users have linked

**Schema:**
```sql
CREATE TABLE ag.user_oauth_account_t (
    oauth_account_id SERIAL PRIMARY KEY,
    user_id VARCHAR(100) NOT NULL,        -- Supabase user UUID
    provider VARCHAR(30) NOT NULL,         -- 'github', 'wechat'
    provider_user_id VARCHAR(200) NOT NULL, -- Provider's user ID
    provider_email VARCHAR(255),           -- Email from provider
    provider_username VARCHAR(200),        -- Display name from provider
    provider_avatar_url VARCHAR(500),      -- Avatar URL from provider
    access_token TEXT,                     -- Encrypted provider access token
    refresh_token TEXT,                    -- Encrypted provider refresh token (if applicable)
    token_expires_at TIMESTAMP,            -- Token expiration time
    tenant_id VARCHAR(100),                -- Tenant ID at time of linking
    create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    delete_flag CHAR(1) DEFAULT 'N',
    UNIQUE(provider, provider_user_id)
);
```

### Decision 4: Auto-create user on first OAuth login

**Choice:** When a user logs in via OAuth for the first time, automatically create a `user_tenant_t` record with default USER role in the default tenant.

**Rationale:**
- Frictionless onboarding (no manual account creation step)
- Consistent with the existing signup flow that also auto-creates tenant records
- The Supabase user record is created automatically by Supabase's OAuth flow

**Email collision handling:** If a user with the same email already exists in `user_tenant_t`, link the OAuth account to the existing user instead of creating a new record. This handles the case where a user initially signed up with email+password and later wants to link GitHub.

### Decision 5: Frontend uses simple redirect-based OAuth, not popup

**Choice:** OAuth login uses full-page redirect (not popup window or iframe).

**Rationale:**
- Simpler implementation
- Works better with mobile browsers
- Avoids popup blocking issues
- Consistent with how most OAuth flows work on the web
- WeChat OAuth in particular works best with full redirect

## Risks / Trade-offs

- **[WeChat OAuth requires ICP filing]** → WeChat OAuth callback URLs must be registered with a verified domain that has ICP filing in China. For self-hosted deployments, users must configure this themselves. The feature will be behind a feature flag (`ENABLE_WECHAT_OAUTH`).
- **[Supabase OAuth provider availability]** → Not all Supabase plans support all OAuth providers. GitHub is available on all plans. WeChat may require a self-hosted Supabase instance with custom configuration. Document this in deployment guide.
- **[Email mismatch between providers]** → Users may have different emails on GitHub vs WeChat. Each OAuth identity maps to the same Supabase user only if emails match. Otherwise, separate accounts are created. This is documented behavior, not a bug.
- **[Account takeover via email linking]** → If a malicious user controls an email that belongs to another user's account, they could link their OAuth to that account. Mitigation: Only auto-link on first login when no `user_tenant_t` record exists for the Supabase user ID. Require explicit confirmation for linking to existing accounts.
- **[Token storage security]** → Provider access/refresh tokens are stored in the database. Mitigation: Encrypt tokens at rest using AES-256 with a server-side encryption key (env var `OAUTH_TOKEN_ENCRYPTION_KEY`).

## Migration Plan

1. **Database migration**: Add `user_oauth_account_t` table via Alembic migration
2. **Backend deployment**: Deploy new OAuth routes alongside existing auth routes (no breaking changes)
3. **Supabase configuration**: Admin configures OAuth providers in Supabase dashboard
4. **Environment variables**: Add new env vars (GitHub/WeChat OAuth credentials, encryption key)
5. **Frontend deployment**: Deploy updated AuthDialogs with OAuth buttons
6. **Rollback**: Disable OAuth by removing OAuth buttons from UI and removing provider configs from Supabase. No database changes need to be reverted (empty table is harmless).

## Open Questions

- Should we support OAuth-only accounts (no password set), or require users to set a password after OAuth signup for security?
- Should the OAuth callback URL be configurable per deployment (for self-hosted users with custom domains)?
- Do we need rate limiting on the OAuth authorize endpoint to prevent abuse?
