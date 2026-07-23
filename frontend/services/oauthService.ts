import { API_ENDPOINTS } from "@/services/api";
import { fetchWithAuth } from "@/lib/auth";
import log from "@/lib/logger";

export interface OAuthProvider {
  name: string;
  display_name: string;
  icon: string;
  enabled: boolean;
}

export interface OAuthConfig {
  enabled: boolean;
  login_mode: "button" | "force" | "disabled";
  auto_login_provider: string | null;
  providers: OAuthProvider[];
}

interface GetOAuthConfigOptions {
  forceRefresh?: boolean;
}

export interface OAuthAccount {
  provider: string;
  provider_username: string | null;
  provider_email: string | null;
  linked_at: string | null;
}

export interface PendingOAuthInfo {
  provider: string;
  provider_username: string;
  provider_email: string;
  email_required: boolean;
}

export interface CompleteOAuthRequest {
  email?: string;
  password: string;
  invite_code: string;
}

export interface CompleteOAuthResponse {
  session: {
    expires_at: number;
    expires_in_seconds?: number;
  };
}

export type OAuthErrorKey =
  | "auth.oauthPendingExpired"
  | "auth.oauthEmailAlreadyExists"
  | "auth.oauthAccountAlreadyBound"
  | "auth.invalidEmailFormat"
  | "auth.emailRequired"
  | "auth.passwordMinLength"
  | "auth.inviteCodeInvalid"
  | "auth.oauthCompleteFailed";

function getOAuthErrorKey(
  errorMessage: string,
  status?: number
): OAuthErrorKey {
  const normalized = errorMessage.toLowerCase();

  if (
    status === 401 ||
    normalized.includes("completion session") ||
    normalized.includes("pending")
  ) {
    return "auth.oauthPendingExpired";
  }
  if (normalized.includes("email already exists")) {
    return "auth.oauthEmailAlreadyExists";
  }
  if (normalized.includes("already bound")) {
    return "auth.oauthAccountAlreadyBound";
  }
  if (normalized.includes("invalid email")) {
    return "auth.invalidEmailFormat";
  }
  if (normalized.includes("email is required")) {
    return "auth.emailRequired";
  }
  if (normalized.includes("password")) {
    return "auth.passwordMinLength";
  }
  if (normalized.includes("invitation") || normalized.includes("invite")) {
    return "auth.inviteCodeInvalid";
  }

  return "auth.oauthCompleteFailed";
}

export interface SSOCheckResult {
  sso_enabled: boolean;
  provider: string;
  linked: boolean;
  has_token: boolean;
}

export interface SSOReauthorizeResult {
  sso_enabled: boolean;
  provider: string;
  reauthorize_url: string | null;
}

const disabledConfig: OAuthConfig = {
  enabled: false,
  login_mode: "disabled",
  auto_login_provider: null,
  providers: [],
};

const SUCCESS_CACHE_TTL_MS = 5 * 60 * 1000;
const FAILURE_CACHE_TTL_MS = 30 * 1000;

let cachedConfig: OAuthConfig | null = null;
let cacheExpiresAt = 0;
let inFlightConfigPromise: Promise<OAuthConfig> | null = null;

const cacheConfig = (config: OAuthConfig, ttlMs: number) => {
  cachedConfig = config;
  cacheExpiresAt = Date.now() + ttlMs;
};

export const oauthService = {
  getConfig: async (
    options: GetOAuthConfigOptions = {}
  ): Promise<OAuthConfig> => {
    const now = Date.now();
    if (!options.forceRefresh && cachedConfig && cacheExpiresAt > now) {
      return cachedConfig;
    }

    if (inFlightConfigPromise) {
      return inFlightConfigPromise;
    }

    inFlightConfigPromise = (async () => {
      try {
        const response = await fetch(API_ENDPOINTS.oauth.config);
        if (!response.ok) {
          log.warn("Failed to fetch OAuth config");
          cacheConfig(disabledConfig, FAILURE_CACHE_TTL_MS);
          return disabledConfig;
        }

        const data = await response.json();
        const responseConfig = data.data || {};
        const config: OAuthConfig = {
          ...disabledConfig,
          ...responseConfig,
          providers: Array.isArray(responseConfig.providers)
            ? responseConfig.providers
            : [],
        };
        cacheConfig(config, SUCCESS_CACHE_TTL_MS);
        return config;
      } catch (error) {
        log.warn("Failed to fetch OAuth config:", error);
        cacheConfig(disabledConfig, FAILURE_CACHE_TTL_MS);
        return disabledConfig;
      } finally {
        inFlightConfigPromise = null;
      }
    })();

    return inFlightConfigPromise;
  },

  getEnabledProviders: async (): Promise<OAuthProvider[]> => {
    const config = await oauthService.getConfig();
    return config.providers;
  },

  startOAuthLogin: (provider: string): void => {
    window.location.href = `${API_ENDPOINTS.oauth.authorize}?provider=${provider}`;
  },

  startOAuthLink: (provider: string): void => {
    window.location.href = `${API_ENDPOINTS.oauth.link}?provider=${provider}`;
  },

  getPendingOAuth: async (): Promise<PendingOAuthInfo | null> => {
    try {
      const response = await fetch(API_ENDPOINTS.oauth.pending);
      if (!response.ok) {
        log.warn("Failed to fetch pending OAuth info");
        return null;
      }
      const data = await response.json();
      return data.data || null;
    } catch (error) {
      log.error("Failed to fetch pending OAuth info:", error);
      return null;
    }
  },

  completeOAuth: async (
    payload: CompleteOAuthRequest
  ): Promise<{
    data?: CompleteOAuthResponse;
    error?: string;
    errorKey?: OAuthErrorKey;
  }> => {
    try {
      const response = await fetch(API_ENDPOINTS.oauth.complete, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      });
      const data = await response.json();
      if (!response.ok) {
        const error =
          data.detail || data.message || "Failed to complete OAuth account";
        return {
          error,
          errorKey: getOAuthErrorKey(error, response.status),
        };
      }
      return {
        data: {
          session: data.data.session,
        },
      };
    } catch (error) {
      log.error("Failed to complete OAuth account:", error);
      return {
        error:
          error instanceof Error
            ? error.message
            : "Failed to complete OAuth account",
        errorKey: "auth.oauthCompleteFailed",
      };
    }
  },

  getLinkedAccounts: async (): Promise<OAuthAccount[]> => {
    try {
      const response = await fetchWithAuth(API_ENDPOINTS.oauth.accounts);
      if (!response.ok) {
        log.warn("Failed to fetch linked OAuth accounts");
        return [];
      }
      const data = await response.json();
      return data.data || [];
    } catch (error) {
      log.error("Failed to fetch linked OAuth accounts:", error);
      return [];
    }
  },

  unlinkAccount: async (provider: string): Promise<boolean> => {
    try {
      const response = await fetchWithAuth(
        API_ENDPOINTS.oauth.unlink(provider),
        {
          method: "DELETE",
        }
      );
      return response.ok;
    } catch (error) {
      log.error(`Failed to unlink ${provider} account:`, error);
      return false;
    }
  },

  getSSOConfig: async (): Promise<{ sso_enabled: boolean; sso_provider: string; change_password_url: string } | null> => {
    try {
      const response = await fetch(API_ENDPOINTS.oauth.ssoConfig);
      if (!response.ok) {
        log.warn("Failed to fetch SSO config");
        return null;
      }
      const data = await response.json();
      return data.data || null;
    } catch (error) {
      log.error("Failed to fetch SSO config:", error);
      return null;
    }
  },

  getSSOStatus: async (): Promise<SSOCheckResult | null> => {
    try {
      const response = await fetchWithAuth(API_ENDPOINTS.oauth.ssoStatus);
      if (!response.ok) {
        log.warn("Failed to fetch SSO status");
        return null;
      }
      const data = await response.json();
      return data.data || null;
    } catch (error) {
      log.error("Failed to fetch SSO status:", error);
      return null;
    }
  },

  reauthorizeSSO: async (): Promise<SSOReauthorizeResult | null> => {
    try {
      const response = await fetchWithAuth(API_ENDPOINTS.oauth.ssoReauthorize);
      if (!response.ok) {
        log.warn("Failed to reauthorize SSO");
        return null;
      }
      const data = await response.json();
      return data.data || null;
    } catch (error) {
      log.error("Failed to reauthorize SSO:", error);
      return null;
    }
  },
};
