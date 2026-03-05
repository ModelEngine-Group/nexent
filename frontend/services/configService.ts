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
  async saveConfig(config: GlobalConfig): Promise<void> {
    await fetchWithErrorHandling(API_ENDPOINTS.config.save, {
      method: "POST",
      headers: getAuthHeaders(),
      body: JSON.stringify(config),
    });
  }
}

// Export singleton instance
export const configService = new ConfigService();
