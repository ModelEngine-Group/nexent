import { API_ENDPOINTS, fetchWithErrorHandling } from "./api";
import { GlobalConfig } from "@/types/modelConfig";
import { getAuthHeaders } from "@/lib/auth";

/**
 * Config Service
 * Provides methods to fetch and save configuration data from backend API
 * This service only handles API communication, no localStorage or caching
 */
export class ConfigService {
  /**
   * Fetch config from backend API
   * @returns Raw config data from backend
   */
  async fetchConfig(): Promise<unknown> {
    const response = await fetchWithErrorHandling(API_ENDPOINTS.config.load, {
      method: "GET",
      headers: getAuthHeaders(),
    });

    const result = await response.json();
    return result.config;
  }

  /**
   * Save config to backend API
   * @param config GlobalConfig to save
   */
  async fetchRuntimeFrontendConfig(): Promise<{ shareBaseUrl?: string }> {
    const response = await fetch(API_ENDPOINTS.config.frontend, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`Request failed: ${response.status}`);
    }
    return response.json();
  }

  async saveConfig(config: GlobalConfig): Promise<void> {
    const app = { ...config.app } as Record<string, unknown>;
    delete app.appName;
    delete app.appDescription;

    await fetchWithErrorHandling(API_ENDPOINTS.config.save, {
      method: "POST",
      headers: getAuthHeaders(),
      body: JSON.stringify({ ...config, app }),
    });
  }
}

// Export singleton instance
export const configService = new ConfigService();
