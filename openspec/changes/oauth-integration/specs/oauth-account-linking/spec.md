## ADDED Requirements

### Requirement: OAuth account database model
The system SHALL maintain an `user_oauth_account_t` table that stores the mapping between OAuth provider identities and internal Nexent user accounts. Each record MUST include: user_id (Supabase UUID), provider name, provider-specific user ID, provider email, provider username, provider avatar URL, encrypted access token, encrypted refresh token, token expiration time, and tenant_id.

#### Scenario: OAuth account record created on first login
- **WHEN** a user logs in via OAuth for the first time and no `user_oauth_account_t` record exists for (provider, provider_user_id)
- **THEN** the system creates a new record in `user_oauth_account_t` with the provider identity information and the user's Supabase user ID

#### Scenario: Duplicate OAuth identity prevented
- **WHEN** an OAuth login completes and a `user_oauth_account_t` record already exists for (provider, provider_user_id)
- **THEN** the system updates the existing record's token and profile information instead of creating a duplicate

### Requirement: Automatic user creation on first OAuth login
When a user completes OAuth login and the Supabase user ID does not exist in `user_tenant_t`, the system SHALL automatically create a `user_tenant_t` record with the default USER role and default tenant ID. The user_email in `user_tenant_t` SHALL be set to the email returned by the OAuth provider.

#### Scenario: New OAuth user gets default tenant
- **WHEN** a user logs in via OAuth and their Supabase user ID has no corresponding `user_tenant_t` record
- **THEN** the system creates a `user_tenant_t` record with user_role='USER' and tenant_id from DEFAULT_TENANT_ID, and creates a `user_oauth_account_t` record linking the provider identity

#### Scenario: OAuth user already has tenant record
- **WHEN** a user logs in via OAuth and their Supabase user ID already exists in `user_tenant_t`
- **THEN** the system skips user creation and only ensures the `user_oauth_account_t` record exists and is up to date

### Requirement: List linked OAuth accounts
The system SHALL expose a `GET /api/user/oauth/accounts` endpoint that returns all OAuth providers linked to the authenticated user's account. The response MUST include provider name, provider username, provider email, provider avatar URL, and the date the account was linked.

#### Scenario: User with linked GitHub account
- **WHEN** an authenticated user requests their linked OAuth accounts and has a GitHub account linked
- **THEN** the response includes a GitHub entry with the provider username, email, avatar URL, and link date

#### Scenario: User with no linked accounts
- **WHEN** an authenticated user requests their linked OAuth accounts and has no linked providers
- **THEN** the response returns an empty list

### Requirement: Unlink OAuth account
The system SHALL expose a `DELETE /api/user/oauth/accounts/{provider}` endpoint that removes the link between an OAuth provider and the authenticated user's account. The provider access/refresh tokens MUST be deleted. The user MUST still be able to log in via other methods (email/password or other linked OAuth providers).

#### Scenario: Unlink GitHub account
- **WHEN** an authenticated user requests to unlink their GitHub account
- **THEN** the system soft-deletes the `user_oauth_account_t` record for (user_id, 'github') and returns success

#### Scenario: Unlink last authentication method
- **WHEN** a user attempts to unlink their only remaining authentication method (no password set, no other OAuth providers linked)
- **THEN** the system rejects the request with an error indicating the user must have at least one authentication method

#### Scenario: Unlink non-existent provider
- **WHEN** a user attempts to unlink a provider that is not linked to their account
- **THEN** the system returns a 404 error

### Requirement: Frontend OAuth account management UI
The frontend SHALL display linked OAuth accounts in the user settings/profile section. Each linked account MUST show the provider icon, username, and email. An unlink button MUST be provided for each linked account, with a confirmation dialog before unlinking.

#### Scenario: View linked accounts in settings
- **WHEN** an authenticated user navigates to their account settings
- **THEN** they see a section listing all linked OAuth providers with provider icon, username, and email

#### Scenario: Unlink account with confirmation
- **WHEN** a user clicks the unlink button for a linked provider
- **THEN** a confirmation dialog appears explaining that the provider account will be unlinked, and upon confirmation, the unlink API is called and the UI updates

#### Scenario: No linked accounts display
- **WHEN** a user has no linked OAuth accounts
- **THEN** the account management section shows a message indicating no third-party accounts are linked, with a prompt to link one

### Requirement: Provider token encryption at rest
OAuth provider access tokens and refresh tokens stored in the database MUST be encrypted at rest using AES-256 encryption. The encryption key MUST be configured via the `OAUTH_TOKEN_ENCRYPTION_KEY` environment variable. Tokens MUST be decrypted only when needed for API calls to the provider.

#### Scenario: Token stored encrypted
- **WHEN** the system stores an OAuth access token in `user_oauth_account_t`
- **THEN** the token is encrypted using AES-256 before being written to the database

#### Scenario: Token decrypted for use
- **WHEN** the system needs to use an OAuth access token (e.g., for provider API calls)
- **THEN** the token is decrypted from the database using the configured encryption key
