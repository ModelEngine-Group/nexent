import { API_ENDPOINTS, fetchWithErrorHandling } from "./api";
import log from "@/lib/logger";
import {APP_VERSION} from "@/const/constants";
import {STATUS_CODES} from "@/const/auth";

export interface DeploymentVersionResponse {
  app_version?: string;
  content?: {
    app_version?: string;
  };
}

export class VersionService {
  /**
   * Get application version from deployment API
   * @returns Promise<string> App version number
   */
  async getAppVersion(): Promise<string> {
    try {
      // Reuse a global promise to deduplicate deployment_version calls across the app
      if (!(globalThis as any).__deploymentVersionPromise) {
        (globalThis as any).__deploymentVersionPromise = (async () => {
          try {
            const response = await fetchWithErrorHandling(
              API_ENDPOINTS.tenantConfig.deploymentVersion
            );
            if (response.status !== STATUS_CODES.SUCCESS) {
              return null;
            }
            const data: DeploymentVersionResponse = await response.json();
            return data.app_version || data.content?.app_version || null;
          } catch (e) {
            log.error("Error fetching app version (inner):", e);
            return null;
          }
        })();
      }

      const version = await (globalThis as any).__deploymentVersionPromise;
      if (version) return version;
      log.warn("App version not found in response, using fallback");
      return APP_VERSION;
    } catch (error) {
      log.error("Error fetching app version:", error);
      return APP_VERSION;
    }
  }
}

// Export singleton instance
export const versionService = new VersionService();
