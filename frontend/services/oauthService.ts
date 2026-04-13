import { API_ENDPOINTS } from "@/services/api";
import { fetchWithAuth } from "@/lib/auth";
import log from "@/lib/logger";

export interface OAuthProvider {
  name: string;
  display_name: string;
  icon: string;
  enabled: boolean;
}

export interface OAuthAccount {
  provider: string;
  provider_username: string | null;
  provider_email: string | null;
  linked_at: string | null;
}

export const oauthService = {
  getEnabledProviders: async (): Promise<OAuthProvider[]> => {
    try {
      const response = await fetch(API_ENDPOINTS.oauth.providers);
      if (!response.ok) {
        log.warn("Failed to fetch OAuth providers");
        return [];
      }
      const data = await response.json();
      return data.data || [];
    } catch (error) {
      log.error("Failed to fetch OAuth providers:", error);
      return [];
    }
  },

  startOAuthLogin: (provider: string): void => {
    window.location.href = `${API_ENDPOINTS.oauth.authorize}?provider=${provider}`;
  },

  startOAuthLink: (provider: string): void => {
    window.location.href = `${API_ENDPOINTS.oauth.link}?provider=${provider}`;
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
      const response = await fetchWithAuth(API_ENDPOINTS.oauth.unlink(provider), {
        method: "DELETE",
      });
      return response.ok;
    } catch (error) {
      log.error(`Failed to unlink ${provider} account:`, error);
      return false;
    }
  },
};
