# 版本信息管理

Nexent 项目采用统一的版本管理策略，确保前端和后端版本信息的一致性。本文档介绍如何管理和更新项目版本信息。

## 版本号格式

Nexent 使用语义化版本控制：

- **格式**: `vMAJOR.MINOR.PATCH` 或 `vMAJOR.MINOR.PATCH.BUILD` (例如：v1.1.0 或 v1.1.0.1)
- **MAJOR**: 不兼容的 API 修改
- **MINOR**: 向下兼容的功能性新增
- **PATCH**: 向下兼容的问题修正
- **BUILD**: 可选的小版本号，用于更细粒度的 bugfix 版本

### 版本号示例

- `v1.2.0` - 功能更新版本
- `v1.2.0.1` - 包含小版本号的 bugfix 版本

## 前端版本管理

### 版本信息位置

前端版本信息通过接口从后端获取。

- **接口**: `GET /api/tenant_config/deployment_version`
- **服务**: `frontend/services/versionService.ts`

### 版本更新流程

1. **在代码中更新后端版本**

编辑 `backend/consts/const.py` 更新 `APP_VERSION`：

```python
# backend/consts/const.py
APP_VERSION="v1.1.0"
```

2. **验证版本显示**

   ```bash
   # 启动前端服务
   cd frontend
   npm run dev

   # 在页面底部检查应用版本显示
   ```

### 版本显示

前端版本信息在以下位置显示：

- 位置：页面底部导航栏，位于页面左下角
- 版本格式：`v1.1.0`

## 后端版本管理

### 版本信息位置

后端版本信息在 `backend/consts/const.py` 中以代码形式定义：

```python
# backend/consts/const.py
APP_VERSION = "v1.0.0"
```

### 版本配置

版本通过直接修改 `backend/consts/const.py` 中的 `APP_VERSION` 配置。

### 版本显示

后端启动时会在日志中打印版本信息：

```python
# backend/main_service.py
logger.info(f"APP version is: {APP_VERSION}")
```

### 版本更新流程

1. **在代码中更新版本**

```python
# 编辑 backend/consts/const.py
APP_VERSION="v1.1.0"
```

2. **验证版本显示**

   ```bash
   # 启动后端服务
   cd backend
   python main_service.py

   # 查看启动日志中的版本信息
   # 输出示例：APP version is: v1.1.0
   ```
