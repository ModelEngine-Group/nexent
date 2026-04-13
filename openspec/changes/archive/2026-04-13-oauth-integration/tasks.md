## 1. Environment and Configuration

- [x] 1.1 Add OAuth environment variables to `backend/consts/const.py`: `GITHUB_OAUTH_CLIENT_ID`, `GITHUB_OAUTH_CLIENT_SECRET`, `ENABLE_WECHAT_OAUTH`, `WECHAT_OAUTH_APP_ID`, `WECHAT_OAUTH_APP_SECRET`, `OAUTH_TOKEN_ENCRYPTION_KEY`, `OAUTH_CALLBACK_URL`
- [x] 1.2 Add OAuth configuration variables to `.env.example` and `docker/.env.example` with documentation comments
- [x] 1.3 Add `authlib` dependency to `backend/pyproject.toml` (if needed for WeChat custom flow; Supabase native OAuth may not require it)

## 2. Database Schema

- [x] 2.1 Create Alembic migration for `user_oauth_account_t` table with columns: oauth_account_id (PK), user_id, provider, provider_user_id, provider_email, provider_username, provider_avatar_url, access_token, refresh_token, token_expires_at, tenant_id, plus audit fields (create_time, update_time, created_by, updated_by, delete_flag)
- [x] 2.2 Add unique constraint on (provider, provider_user_id) and index on user_id
- [x] 2.3 Add SQLAlchemy ORM model `UserOAuthAccount` in `backend/database/db_models.py` extending `TableBase`
- [x] 2.4 Create `backend/database/oauth_account_db.py` with CRUD operations: insert, get_by_user_id, get_by_provider_and_provider_user_id, update_tokens, soft_delete, list_by_user_id

## 3. Token Encryption Utility

- [x] 3.1 Create `backend/utils/token_encryption.py` with AES-256 encrypt/decrypt functions using `OAUTH_TOKEN_ENCRYPTION_KEY` env var
- [x] 3.2 Add unit tests for encryption/decryption round-trip
- [x] 10.1 Write unit tests for `backend/services/oauth_service.py` (provider registry, authorize URL generation, callback handling, account creation/linking)
- [x] 10.2 Write unit tests for `backend/database/oauth_account_db.py` (CRUD operations)
- [x] 10.3 Write unit tests for `backend/utils/token_encryption.py` (encrypt/decrypt round-trip)
- [x] 10.4 Write integration tests for OAuth API endpoints (`GET /user/oauth/authorize`, `GET /user/oauth/callback`, `GET /user/oauth/accounts`, `DELETE /user/oauth/accounts/{provider}`)
- [x] 10.5 Write frontend unit tests for `oauthService.ts` and OAuth UI components
