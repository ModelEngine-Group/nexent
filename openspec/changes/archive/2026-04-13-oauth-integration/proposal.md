## Why

Currently, Nexent only supports email + password authentication via Supabase Auth. Users must manually register with an email and password, which creates friction for onboarding and limits access for users who prefer social login. Adding OAuth support (GitHub, WeChat) enables one-click login, reduces signup friction, and aligns with modern SaaS authentication expectations. This is especially important for a developer-facing platform where GitHub is the natural identity provider.

## What Changes

- Add OAuth 2.0 login flow for GitHub and WeChat as authentication providers
- Create a new `user_oauth_account_t` database table to link OAuth provider identities to internal user accounts
- Add backend OAuth endpoints: authorization URL generation (`GET /api/user/oauth/authorize`), callback handling (`GET /api/user/oauth/callback`), and account linking/unlinking (`POST/DELETE /api/user/oauth/accounts`)
- Integrate with existing Supabase Auth session management so OAuth login produces the same JWT tokens and cookie-based session as email login
- Add OAuth login buttons to the frontend login dialog (GitHub and WeChat icons)
- Add an OAuth account management section in user settings (view linked accounts, link/unlink)
- Support automatic account creation for new OAuth users (with default USER role and default tenant)
- Support account linking: if an OAuth email matches an existing user, link the OAuth identity to that user

## Capabilities

### New Capabilities
- `oauth-provider-integration`: OAuth 2.0 provider configuration, authorization flow, token exchange, and user identity resolution for GitHub and WeChat
- `oauth-account-linking`: Database model and business logic for linking OAuth identities to internal user accounts, including automatic creation and linking

### Modified Capabilities

## Impact

- **Backend**: New OAuth service (`services/oauth_service.py`), new OAuth app routes (`apps/oauth_app.py`), new DB model (`user_oauth_account_t`), new env vars in `consts/const.py`
- **Frontend**: Modified `AuthDialogs.tsx` to add OAuth buttons, new `oauthService.ts` for OAuth API calls, modified `AuthenticationProvider.tsx` to handle OAuth callback
- **Server proxy** (`frontend/server.js`): New proxy route for OAuth callback endpoint
- **Database**: New migration for `user_oauth_account_t` table
- **Dependencies**: New Python dependency `authlib` for OAuth 2.0 client
- **Environment**: New env vars for GitHub OAuth (client_id, client_secret) and WeChat OAuth (app_id, app_secret)
- **API**: New public endpoints under `/api/user/oauth/*` (no auth required for authorize/callback)
