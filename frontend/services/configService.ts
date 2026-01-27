import { API_ENDPOINTS } from "./api";

import { GlobalConfig } from "@/types/modelConfig";

import { fetchWithAuth, getAuthHeaders } from "@/lib/auth";
import { ConfigStore } from "@/lib/config";
import log from "@/lib/logger";
// @ts-ignore
const fetch = fetchWithAuth;

export class ConfigService {
  // In-flight dedupe and short-term cache for loadConfigToFrontend
  private _loadInFlight: Promise<boolean> | null = null;
  private _lastLoadTs: number | null = null;
  private readonly _LOAD_TTL_MS = 5 * 1000; // 5 seconds

  // Save global configuration to backend
  async saveConfigToBackend(config: GlobalConfig): Promise<boolean> {
    try {
      const response = await fetch(API_ENDPOINTS.config.save, {
        method: "POST",
        headers: getAuthHeaders(),
        body: JSON.stringify(config),
      });

      if (!response.ok) {
        const errorData = await response.json();
        log.error("Failed to save configuration:", errorData);
        return false;
      }

      await response.json();
      return true;
    } catch (error) {
      log.error("Save configuration request exception:", error);
      return false;
    }
  }

  // Add: Load configuration from backend and write to localStorage
  async loadConfigToFrontend(): Promise<boolean> {
    // Dedupe concurrent calls and avoid repeat calls within short TTL
    if (this._loadInFlight) return this._loadInFlight;
    const now = Date.now();
    if (this._lastLoadTs && now - this._lastLoadTs < this._LOAD_TTL_MS) {
      return Promise.resolve(true);
    }

    this._loadInFlight = (async () => {
      try {
        const response = await fetch(API_ENDPOINTS.config.load, {
          method: "GET",
          headers: getAuthHeaders(),
        });
        if (!response.ok) {
          const errorData = await response.json();
          log.error("Failed to load configuration:", errorData);
          this._lastLoadTs = Date.now();
          return false;
        }
        const result = await response.json();
        const config = result.config;
        if (config) {
        // Use the conversion function of configStore
        const frontendConfig = ConfigStore.transformBackend2Frontend(config);

        // Write to localStorage separately
        if (frontendConfig.app) {
          localStorage.setItem("app", JSON.stringify(frontendConfig.app));
        }
        if (frontendConfig.models) {
          localStorage.setItem("model", JSON.stringify(frontendConfig.models));
        }

        // Trigger configuration reload and dispatch event
        if (typeof window !== "undefined") {
          const configStore = ConfigStore.getInstance();
          configStore.reloadFromStorage();
        }

        this._lastLoadTs = Date.now();
        return true;
      }
      } catch (error) {
        log.error("Load configuration request exception:", error);
        this._lastLoadTs = Date.now();
        return false;
      } finally {
        // clear in-flight after completion
        this._loadInFlight = null;
      }
    })();

    return this._loadInFlight;
  }
}

// Export singleton instance
export const configService = new ConfigService();
