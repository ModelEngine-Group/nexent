import { API_ENDPOINTS } from './api';

import { GlobalConfig } from '@/types/modelConfig';

import { fetchWithAuth, getAuthHeaders } from '@/lib/auth';
import { ConfigStore } from '@/lib/config';
import log from "@/lib/logger";
// @ts-ignore
const fetch = fetchWithAuth;

export class ConfigService {
  // Save global configuration to backend
  async saveConfigToBackend(config: GlobalConfig): Promise<boolean> {
    try {
      let modelEngineApiKey = "";
      try {
        if (config && (config as any).modelengine && typeof (config as any).modelengine.apiKey === "string") {
          modelEngineApiKey = (config as any).modelengine.apiKey || "";
        }
      } catch (e) {
        // ignore
      }

      const payload: any = {
        ...config,
        modelengine: {
          apiKey: modelEngineApiKey || "",
        },
      };

      const response = await fetch(API_ENDPOINTS.config.save, {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        const errorData = await response.json();
        log.error('Failed to save configuration:', errorData);
        return false;
      }

      // Persist ModelEngine API key into localStorage so subsequent operations can use cached value.
      try {
        if (typeof window !== "undefined") {
          if (modelEngineApiKey) {
            // persist as plain string (single API key)
            localStorage.setItem("model_engine_api_key", modelEngineApiKey);
          } else {
            // clear any previously persisted key when saving an empty apiKey
            localStorage.removeItem("model_engine_api_key");
          }
        }
      } catch (e) {
        log.error("Failed to persist ModelEngine API Key after saveConfig:", e);
      }

      return true;
    } catch (error) {
      log.error('Save configuration request exception:', error);
      return false;
    }
  }

  // Add: Load configuration from backend and write to localStorage
  async loadConfigToFrontend(): Promise<boolean> {
    try {
      const response = await fetch(API_ENDPOINTS.config.load, {
        method: 'GET',
        headers: getAuthHeaders(),
      });
      if (!response.ok) {
        const errorData = await response.json();
        log.error('Failed to load configuration:', errorData);
        return false;
      }
      const result = await response.json();
      const config = result.config;
      if (config) {
        // Use the conversion function of ConfigStore to adapt backend shape to frontend
        const frontendConfig = ConfigStore.transformBackend2Frontend(config);

        // Update in-memory ConfigStore with the converted frontend config so callers can read modelengine
        try {
          const cs = ConfigStore.getInstance();
          cs.updateConfig(frontendConfig as any);
        } catch (e) {
          // fallback to writing to localStorage keys if updateConfig fails
          if (frontendConfig.app) {
            localStorage.setItem('app', JSON.stringify(frontendConfig.app));
          }
          if (frontendConfig.models) {
            localStorage.setItem('model', JSON.stringify(frontendConfig.models));
          }
        }
        // Persist ModelEngine API key ONLY from backend load_config (may be empty).
        // IMPORTANT: do not overwrite a locally cached API key with an empty backend value.
        try {
          const backendKey = (config && config.modelengine && config.modelengine.apiKey) || "";
          if (typeof window !== "undefined") {
            // Only update localStorage if backend provides a non-empty key.
            if (backendKey) {
              localStorage.setItem("model_engine_api_key", backendKey);
            } else {
              // Preserve any existing local cached key when backend does not return one.
              // This avoids clearing the user's locally-entered API key during frontend-only saves.
            }
          }
        } catch (e) {
          log.error("Failed to persist ModelEngine API Key in loadConfigToFrontend:", e);
        }

        // Trigger configuration reload and dispatch event
        if (typeof window !== 'undefined') {
          const configStore = ConfigStore.getInstance();
          configStore.reloadFromStorage();
        }

        return true;
      }
      return false;
    } catch (error) {
      log.error('Load configuration request exception:', error);
      return false;
    }
  }
}

// Export singleton instance
export const configService = new ConfigService();
