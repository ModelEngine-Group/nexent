import { API_ENDPOINTS, fetchWithErrorHandling } from "./api";
import log from "@/lib/logger";

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

      if (response.status !== 200) {
        log.warn("Failed to fetch app version, using fallback");
        return "v1.0.0"; // Fallback version
      }

      const data: DeploymentVersionResponse = await response.json();

      // Extract app_version from response
      const version = data.app_version || data.content?.app_version;

      if (version) {
        return version;
      }

      log.warn("App version not found in response, using fallback");
      return "v1.0.0"; // Fallback version
    } catch (error) {
      log.error("Error fetching app version:", error);
      return "v1.0.0"; // Fallback version
    }
  }
}

// Export singleton instance
export const versionService = new VersionService();
