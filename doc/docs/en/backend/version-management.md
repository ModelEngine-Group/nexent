# Version Information Management

The Nexent project adopts a unified version management strategy to ensure consistency between frontend and backend version information. This document describes how to manage and update project version information.

## 📋 Version Number Format

Nexent uses Semantic Versioning:

- **Format**: `vMAJOR.MINOR.PATCH` or `vMAJOR.MINOR.PATCH.BUILD` (e.g., v1.1.0 or v1.1.0.1)
- **MAJOR**: Incompatible API changes
- **MINOR**: New functionality in a backwards-compatible manner
- **PATCH**: Backwards-compatible bug fixes
- **BUILD**: Optional minor version number for more granular bugfix versions

### 🏷️ Version Number Examples

- `v1.2.0` - Feature update release
- `v1.2.0.1` - Bugfix release with minor version number

## 🖥️ Frontend Version Management

### 📍 Version Information Location

Frontend version information is fetched from the backend via API.

- **Endpoint**: `GET /api/tenant_config/deployment_version`
- **Service**: `frontend/services/versionService.ts`

### 🔄 Version Update Process

1. **Update backend version in code**

Edit `backend/consts/const.py` to update `APP_VERSION`:

```python
# backend/consts/const.py
APP_VERSION="v1.1.0"
```

2. **Verify Version Display**

   ```bash
   # Start the frontend service
   cd frontend
   npm run dev

   # Check the application version displayed at the bottom of the page
   ```

### 📺 Version Display

Frontend version information is displayed at the following location:

- **Location**: Bottom navigation bar, located at the bottom left corner of the page.
- **Version Format**: `v1.1.0`

## ⚙️ Backend Version Management

### 📍 Version Information Location

Backend version information is defined in code in `backend/consts/const.py`:

```python
# backend/consts/const.py
APP_VERSION = "v1.0.0"
```

### 🔧 Version Configuration

Version is configured directly in `backend/consts/const.py`.

### 📺 Version Display

Backend startup will print version information in the logs:

```python
# backend/config_service.py
logger.info(f"APP version is: {APP_VERSION}")
```

### 🔄 Version Update Process

1. **Update Version in Code**

```python
# Edit backend/consts/const.py
APP_VERSION="v1.1.0"
```

2. **Verify Version Display**

   ```bash
   # Start the backend service
   cd backend
   python config_service.py

   # Check the version information in the startup logs
   # Output example: APP version is: v1.1.0
   ```

