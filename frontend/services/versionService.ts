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
      const response = await fetchWithErrorHandling(
        API_ENDPOINTS.tenantConfig.deploymentVersion
      );

      if (response.status !== STATUS_CODES.SUCCESS) {
        log.warn("Failed to fetch app version, using fallback");
        return APP_VERSION;
      }

      const data: DeploymentVersionResponse = await response.json();
      const version = data.app_version || data.content?.app_version;

      if (version) {
        return version;
      }

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
