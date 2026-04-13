## ADDED Requirements

### Requirement: OAuth provider configuration management
The system SHALL support configuring OAuth 2.0 providers (GitHub, WeChat) via environment variables centralized in `backend/consts/const.py`. Each provider configuration MUST include: provider name, client ID, client secret, authorization URL, token URL, and userinfo URL. WeChat OAuth SHALL be behind a feature flag (`ENABLE_WECHAT_OAUTH`).

#### Scenario: GitHub OAuth configured
- **WHEN** `GITHUB_OAUTH_CLIENT_ID` and `GITHUB_OAUTH_CLIENT_SECRET` environment variables are set
- **THEN** GitHub OAuth login is enabled and the GitHub login button is visible in the login dialog

#### Scenario: GitHub OAuth not configured
- **WHEN** `GITHUB_OAUTH_CLIENT_ID` or `GITHUB_OAUTH_CLIENT_SECRET` environment variables are not set
- **THEN** GitHub OAuth login is disabled and the GitHub login button is hidden

#### Scenario: WeChat OAuth feature flag disabled
- **WHEN** `ENABLE_WECHAT_OAUTH` environment variable is not set to `"true"`
- **THEN** WeChat OAuth login is disabled regardless of whether WeChat credentials are configured

### Requirement: OAuth authorization endpoint
The system SHALL expose a `GET /api/user/oauth/authorize` endpoint that redirects the browser to the OAuth provider's authorization page. This endpoint MUST accept a `provider` query parameter (values: `github`, `wechat`) and redirect to Supabase Auth's authorize URL with the correct provider and redirect_to callback URL.

#### Scenario: Valid OAuth provider authorization
- **WHEN** a user navigates to `/api/user/oauth/authorize?provider=github`
- **THEN** the system responds with a 302 redirect to the Supabase Auth authorize URL for GitHub, including the backend callback URL as the `redirect_to` parameter

#### Scenario: Invalid OAuth provider
- **WHEN** a user navigates to `/api/user/oauth/authorize?provider=invalid_provider`
- **THEN** the system responds with a 400 error indicating the provider is not supported

#### Scenario: Disabled OAuth provider
- **WHEN** a user navigates to `/api/user/oauth/authorize?provider=wechat` and WeChat OAuth is disabled
- **THEN** the system responds with a 400 error indicating the provider is not available

### Requirement: OAuth callback endpoint
The system SHALL expose a `GET /api/user/oauth/callback` endpoint that handles the OAuth provider's redirect after user authorization. This endpoint MUST extract the Supabase session tokens from the callback URL, create a `user_tenant_t` record if the user is new, create a `user_oauth_account_t` record, set HttpOnly cookies (access_token, refresh_token, expires_at), and redirect the browser to the frontend application.

#### Scenario: First-time OAuth login creates new user
- **WHEN** a user completes OAuth authorization and the Supabase user ID does not exist in `user_tenant_t`
- **THEN** the system creates a new `user_tenant_t` record with the default USER role and default tenant ID, creates a `user_oauth_account_t` record, sets HttpOnly cookies, and redirects to the frontend

#### Scenario: Returning OAuth login links existing user
- **WHEN** a user completes OAuth authorization and the Supabase user ID already exists in `user_tenant_t`
- **THEN** the system updates the existing `user_oauth_account_t` record if needed, sets HttpOnly cookies, and redirects to the frontend without creating a duplicate user record

#### Scenario: OAuth email matches existing email user
- **WHEN** a user completes OAuth authorization and the email from the OAuth provider matches an existing `user_tenant_t.user_email` but the Supabase user IDs differ
- **THEN** the system creates a new `user_tenant_t` record for the new Supabase user (does NOT merge accounts to prevent account takeover)

#### Scenario: OAuth callback with error
- **WHEN** the OAuth provider redirects back with an error parameter (e.g., user denied access)
- **THEN** the system redirects to the frontend login page with an error query parameter explaining the failure

### Requirement: OAuth session consistency with email login
OAuth login MUST produce the same session format as email login. The Supabase JWT access_token and refresh_token MUST be set as HttpOnly cookies with the same names (`nexent_access_token`, `nexent_refresh_token`, `nexent_token_expires_at`) and attributes as the existing email login flow. Downstream code MUST NOT be able to distinguish between an OAuth session and an email session.

#### Scenario: OAuth session works with existing auth middleware
- **WHEN** a user logs in via OAuth and makes an API request to any authenticated endpoint
- **THEN** the request succeeds using the same `get_current_user_id()` function used by email login

#### Scenario: OAuth session refresh works
- **WHEN** an OAuth session's access_token expires
- **THEN** the existing token refresh mechanism (`POST /api/user/refresh_token`) works identically to email login sessions

### Requirement: Provider-specific OAuth flow for WeChat
WeChat OAuth uses a two-step flow: first exchange authorization code for access_token via WeChat's `/sns/oauth2/access_token` endpoint, then fetch user info via `/sns/userinfo`. The system SHALL handle this WeChat-specific flow correctly when WeChat OAuth is enabled.

#### Scenario: WeChat OAuth access token exchange
- **WHEN** a user completes WeChat OAuth authorization
- **THEN** the system exchanges the authorization code for an access_token using WeChat's `/sns/oauth2/access_token` endpoint, then fetches user info from `/sns/userinfo`, and stores the provider user ID and profile information

#### Scenario: WeChat OAuth with Open Platform appid
- **WHEN** WeChat OAuth is configured
- **THEN** the system uses the `WECHAT_OAUTH_APP_ID` and `WECHAT_OAUTH_APP_SECRET` environment variables for the OAuth flow

### Requirement: Frontend OAuth login buttons
The frontend login dialog SHALL display OAuth login buttons for each configured and enabled provider. Each button MUST include the provider's icon and label. Clicking a button MUST redirect the browser to `/api/user/oauth/authorize?provider=<provider>`.

#### Scenario: GitHub login button visible
- **WHEN** GitHub OAuth is configured and the login dialog is open
- **THEN** a GitHub-branded button with a GitHub icon is displayed in the login dialog between the email/password form and the GitHub repo link

#### Scenario: WeChat login button visible when enabled
- **WHEN** WeChat OAuth is enabled and configured and the login dialog is open
- **THEN** a WeChat-branded button with a WeChat icon is displayed in the login dialog

#### Scenario: No OAuth buttons when no providers configured
- **WHEN** no OAuth providers are configured
- **THEN** no OAuth buttons are displayed in the login dialog and the dialog layout is unchanged

#### Scenario: OAuth login button redirects
- **WHEN** a user clicks the GitHub login button
- **THEN** the browser navigates to `/api/user/oauth/authorize?provider=github` (full-page redirect)

### Requirement: Frontend OAuth callback handling
The frontend SHALL handle the OAuth callback redirect from the backend. After the backend sets cookies and redirects to the frontend, the frontend MUST detect the OAuth login success, fetch user info, update auth state, and navigate to the chat page.

#### Scenario: Successful OAuth callback
- **WHEN** the browser is redirected to the frontend after a successful OAuth callback
- **THEN** the frontend fetches user info from `/api/user/current_user_info`, updates the authentication context, and navigates to the chat page

#### Scenario: OAuth callback with error
- **WHEN** the browser is redirected to the frontend with an OAuth error query parameter
- **THEN** the frontend displays an error message in the login dialog explaining the OAuth login failure
