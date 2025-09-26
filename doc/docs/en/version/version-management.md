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

Frontend version information is read from the `frontend/package.json` file:

```json
{
  "name": "nexent",
  "version": "v1.0.0",
  "private": true
}
```

Version information is automatically read in the `frontend/components/ui/versionDisplay.tsx` component:

```typescript
import packageJson from "../../package.json";

const version = `${packageJson.version}`;
```

### Version Update Process

1. **Update package.json version**

   ```bash
   # Edit frontend/package.json, modify the version field value
   {
     "version": "v1.1.0"
   }
   ```

2. **Verify Version Display**

   ```bash
   # Start the frontend service
   cd frontend
   npm run dev

   # Check the application version display at the bottom of the page
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
