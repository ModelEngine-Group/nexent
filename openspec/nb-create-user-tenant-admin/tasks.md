# Task 计划 — 北向创建用户接口（仅租户管理员可调用）

> 变更名：`nb-create-user-tenant-admin`
> 流程模式：Full
> 基准分支：`feat-nb-create-user-tenant-admin`（基于 `origin/develop` @ `86d75923d`）

## 基本信息

| 项目 | 内容 |
| ---- | ---- |
| 需求单号 | Issue https://github.com/ModelEngine-Group/nexent/issues/3822 |
| 需求分析文档 | `openspec/nb-create-user-tenant-admin/proposal.md` |
| 设计文档 | `openspec/nb-create-user-tenant-admin/design.md` |
| 创建时间 | 2026-08-31 |

## Task 清单

| ID | 标题 | 描述 | 优先级 | 预估工时 | 依赖 | 状态 |
| ---- | ---- | ---- | ------ | -------- | ---- | ---- |
| TASK-001 | 新增服务层 `create_user_as_tenant_admin` | 在 `user_management_service.py` 新增创建用户的服务函数：角色白名单 → 密码强度 → 邮箱预检 → Supabase admin 创建 → `insert_user_tenant` | 高 | 0.5d | - | 已完成 |
| TASK-002 | 新增北向 app 与端点 | 新增 `backend/apps/northbound_user_app.py`：请求/响应模型、`_require_tenant_admin_context`、`POST /nb/v1/users` 及错误映射 | 高 | 0.5d | TASK-001 | 已完成 |
| TASK-003 | 注册路由 | 在 `northbound_base_app.py` 追加 import 与 `include_router` | 高 | 0.1d | TASK-002 | 已完成 |
| TASK-004 | 服务层单测 | 追加 `TestCreateUserAsTenantAdmin`：成功路径、弱密码、邮箱已存在、角色白名单拒绝（`SU`/未知）、admin client 不可用 | 高 | 0.5d | TASK-001 | 已完成 |
| TASK-005 | 端点层单测 | 新增 `test/backend/app/test_northbound_user_app.py`：管理员 201、非管理员 403、缺租户角色行 403、弱密码 400、非法角色 400、邮箱冲突 409、参数校验 422、DB 异常 500 | 高 | 0.5d | TASK-002 | 已完成 |
| TASK-006 | 运行验证 | 跑新增测试 + 既有 `test_user_management_service.py` 回归；冒烟校验 `POST /nb/v1/users` 已注册 | 高 | 0.3d | TASK-003, TASK-004, TASK-005 | 已完成 |
| TASK-007 | 提交本轮交付 commit | 一轮 AI 编码交付一次 commit，`Refs #3822` | 高 | 0.1d | TASK-006 | 已完成 |

## Task 详情

### TASK-001：新增服务层 `create_user_as_tenant_admin`

**描述**：
在 `backend/services/user_management_service.py` 新增：

```python
async def create_user_as_tenant_admin(
    tenant_id: str,
    email: EmailStr,
    initial_password: str,
    created_by: str,
    name: Optional[str] = None,
    role: str = "USER",
) -> Dict[str, Any]:
```

- 角色归一化后校验白名单 `{USER, DEV, ADMIN}`，`SU` 与未知值抛 `ValueError`
- `validate_password_strength` 不通过抛 `AppException(ErrorCode.PROFILE_PASSWORD_WEAK, ...)`
- 惰性 import `find_supabase_user_id_by_email` 做邮箱预检，命中抛 `UserRegistrationException`
- `get_supabase_admin_client()` 为空抛 `RuntimeError`
- `auth.admin.create_user({email, password, email_confirm: True, user_metadata})`
- `insert_user_tenant(user_id, tenant_id, role, email, created_by=created_by)`
- 返回 `{user_id, user_email, user_role, tenant_id}`

**验收标准**：
- [ ] 函数存在且可被单独调用
- [ ] 密码不进入任何日志语句
- [ ] 异常类型与设计文档 §6.2 表格一致

**备注**：
- 复用文件顶部已有 import：`get_supabase_admin_client`、`validate_password_strength` 同文件定义

---

### TASK-002：新增北向 app 与端点

**描述**：
新增 `backend/apps/northbound_user_app.py`：
- `router = APIRouter(prefix="/nb/v1", tags=["northbound"])`
- `CreateUserRequest`（`EmailStr`、`initial_password`、`name?`、`role?` 默认 `USER`）
- `CreateUserResponse`（`user_id`、`user_email`、`user_role`、`tenant_id`）
- `_require_tenant_admin_context(request)`：`_get_northbound_context` → `get_user_role_by_tenant` → 非 `ADMIN` 抛 403
- `POST /users`，`status_code=201`，按设计文档 §6.2 表格映射异常

**验收标准**：
- [ ] 端点路径精确为 `/nb/v1/users`
- [ ] 非管理员返回 403，且未调用服务层
- [ ] 401/403/400/409/422/500 均有对应分支

**备注**：
- 风格对齐 `northbound_knowledge_app.py`（`HTTPStatus` 常量、`logger`、docstring 说明受限范围）

---

### TASK-003：注册路由

**描述**：
在 `backend/apps/northbound_base_app.py` 追加：
```python
from .northbound_user_app import router as northbound_user_router
...
northbound_app.include_router(northbound_user_router)
```

**验收标准**：
- [ ] 仅追加必要行，不改动既有逻辑
- [ ] 冒烟校验 `POST /nb/v1/users` 出现在 `app.routes`

**备注**：
- FastAPI `include_router` 是惰性路由解析，`app.routes` 在 include 后即包含；端点单测用 `TestClient` 验证

---

### TASK-004：服务层单测

**描述**：
在 `test/backend/services/test_user_management_service.py` 追加 `TestCreateUserAsTenantAdmin`。

**验收标准**：
- [ ] 成功路径（默认 USER、显式 ADMIN）
- [ ] 弱密码 → `AppException` 且 `error_code == PROFILE_PASSWORD_WEAK`
- [ ] 邮箱已存在 → `UserRegistrationException`
- [ ] `role=SU` / 未知角色 → `ValueError`
- [ ] admin client 不可用 → `RuntimeError`
- [ ] `create_user` 返回无 user → `UserRegistrationException`

**备注**：
- 用 `sys.modules` 打桩，避免拉入重量级依赖链

---

### TASK-005：端点层单测

**描述**：
新增 `test/backend/app/test_northbound_user_app.py`，用 `TestClient` 打桩 `_get_northbound_context` 与 `get_user_role_by_tenant`。

**验收标准**：
- [ ] 管理员 → 201 且响应字段齐全
- [ ] 非 ADMIN → 403；缺租户角色行（返回 `""`）→ 403
- [ ] 弱密码 → 400；非法 role → 400
- [ ] 邮箱冲突 → 409
- [ ] 缺字段 / 非法邮箱 → 422
- [ ] DB 查询异常 → 500

**备注**：
- 参考 `test/backend/app/test_northbound_knowledge_app.py` 的打桩风格

---

### TASK-006：运行验证

**描述**：
- 跑 `test/backend/services/test_user_management_service.py`（含新增）
- 跑 `test/backend/app/test_northbound_user_app.py`
- 冒烟：导入 `northbound_user_app.router`，确认 `POST /nb/v1/users` 已注册

**验收标准**：
- [ ] 新增测试全绿
- [ ] 既有测试无回归

---

### TASK-007：提交本轮交付 commit

**描述**：
一轮 AI 编码交付 = 一次 commit；spec 三件套需 `git add -f`（`.gitignore` 第 63 行屏蔽 `openspec/`）。

**验收标准**：
- [ ] commit message 符合规范（type(scope): summary，含 `Refs #3822`、`Co-authored-by`、`Generated-by`）
- [ ] `openspec/` 下三个文件已随 commit 提交

---

## 优先级定义

| 优先级 | 说明 |
| ------ | ---- |
| 高 | 必须完成，影响主线 |
| 中 | 重要，可以延后 |
| 低 | 可选，非关键路径 |

## 依赖关系处理

1. 独立任务：无依赖，可并行执行
2. 顺序依赖：TASK-002 → TASK-003；TASK-001 → TASK-004
3. 阻塞依赖：TASK-006 需 TASK-003/004/005 全部完成
