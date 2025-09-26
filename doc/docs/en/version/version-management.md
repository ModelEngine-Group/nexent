# Version Information Management

The Nexent project adopts a unified version management strategy to ensure consistency between frontend and backend version information. This document describes how to manage and update project version information.

## Version Number Format

Nexent uses Semantic Versioning:

- **Format**: `vMAJOR.MINOR.PATCH` or `vMAJOR.MINOR.PATCH.BUILD` (e.g., v1.1.0 or v1.1.0.1)
- **MAJOR**: Incompatible API changes
- **MINOR**: New functionality in a backwards-compatible manner
- **PATCH**: Backwards-compatible bug fixes
- **BUILD**: Optional minor version number for more granular bugfix versions

### Version Number Examples

- `v1.2.0` - Feature update release
- `v1.2.0.1` - Bugfix release with minor version number

## Frontend Version Management

### Version Information Location

Frontend version information is fetched from the backend via API.

- **Endpoint**: `GET /api/tenant_config/deployment_version`
- **Service**: `frontend/services/versionService.ts`

```startLine:endLine:nexent/frontend/services/versionService.ts
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
```

The version is displayed in the footer, falling back to `APP_VERSION` if the API fails:

```startLine:endLine:nexent/frontend/app/[locale]/page.tsx
<span className="ml-1">· {appVersion || APP_VERSION}</span>
```

`APP_VERSION` default value is defined at:

```startLine:endLine:nexent/frontend/const/constants.ts
export const APP_VERSION = "v1.0.0";
```

### Version Update Process

1. **Update backend environment variable**

   The frontend now reflects the backend deployment version. Update the backend `APP_VERSION` to change the displayed version:

   ```bash
   # .env or .env.example
   APP_VERSION=v1.1.0
   ```

2. **Verify Version Display**

   ```bash
   # Start the frontend service
   cd frontend
   npm run dev

   # Check the application version displayed at the bottom of the page
   ```

### Version Display

Frontend version information is displayed at the following location:

- **Location**: Bottom navigation bar, located at the bottom left corner of the page.
- **Version Format**: `v1.1.0`

## Backend Version Management

### Version Information Location

Backend version information is managed through the environment variable `APP_VERSION`:

```python
# backend/consts/const.py
APP_VERSION = os.getenv("APP_VERSION", "v1.0.0")
```

### Version Configuration

Version information is configured in environment variables:

```bash
# .env or .env.example
APP_VERSION=v1.0.0
```

### Version Display

Backend startup will print version information in the logs:

```python
# backend/main_service.py
logger.info(f"APP version is: {APP_VERSION}")
```

### Version Update Process

1. **Update Environment Variable**

   ```bash
   # Edit .env file, modify the value of APP_VERSION
   APP_VERSION=v1.1.0
   ```

2. **Verify Version Display**

   ```bash
   # Start the backend service
   cd backend
   python main_service.py

   # Check the version information in the startup logs
   # Output example: APP version is: v1.1.0
   ```
