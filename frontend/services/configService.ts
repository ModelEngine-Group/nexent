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
      const response = await fetch(API_ENDPOINTS.config.save, {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify(config),
      });

      if (!response.ok) {
        const errorData = await response.json();
        log.error('Failed to save configuration:', errorData);
        return false;
      }

      await response.json();
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
        // Use the conversion function of configStore
        const frontendConfig = ConfigStore.transformBackend2Frontend(config);

        // Write to localStorage separately
        if (frontendConfig.app) {
          localStorage.setItem('app', JSON.stringify(frontendConfig.app));
        }
        if (frontendConfig.models) {
          localStorage.setItem('model', JSON.stringify(frontendConfig.models));
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