# 北向创建用户接口（仅租户管理员可调用）— 需求分析文档

> 变更名：`nb-create-user-tenant-admin`
> 流程模式：Full
> 目标仓：`ModelEngine-Group/nexent`（远端默认分支 `develop`）
> 关联 Issue：https://github.com/ModelEngine-Group/nexent/issues/3822
> 目标分支：`feat-nb-create-user-tenant-admin`（基于 `origin/develop` @ `86d75923d`）

## 1. 需求概述

### 1.1 业务背景

nexent 当前创建用户只有一条路径：带邀请码的自注册
（`backend/services/user_management_service.py:155` `signup_user_with_invitation`）。

北向（Northbound）API 侧已有知识库、文件、A2A 等能力
（`backend/apps/northbound_app.py` / `northbound_knowledge_app.py` / `northbound_base_app.py`），
但**缺少用户管理类端点**。在集成 / 运营场景下，租户管理员需要直接为用户开通账号
（指定邮箱 + 初始密码），而不必先生成并分发邀请码。

### 1.2 需求目标

新增一个北向 HTTP 端点，允许**租户管理员**创建归属于本租户的用户。

### 1.3 需求范围

**包含：**
- 新增北向端点 `POST /nb/v1/users`
- 复用既有北向 API Key 鉴权解析调用者身份
- 权限门禁：仅租户管理员可调用
- 管理员指定初始密码，经既有密码强度校验
- 新用户落到调用者所在租户
- 邮箱冲突检测
- 单元测试 + OpenAPI 文档自动生成

**不包含：**
- 不修改邀请码自注册流程
- 不做批量创建 / Excel 导入
- 不支持跨租户创建（新用户只能落在调用者本租户）
- 不发激活 / 通知邮件
- 不做租户工具 / 技能列表初始化（见 §8 待确认事项 2）

## 2. 功能描述

### 2.1 核心功能点

| 功能点 | 优先级 | 描述 |
| ------ | ------ | ---- |
| 北向创建用户端点 | 高 | `POST /nb/v1/users`，Bearer API Key 鉴权 |
| 租户管理员权限门禁 | 高 | 调用者在本租户 `user_role == "ADMIN"`，否则 403 |
| 初始密码强度校验 | 高 | 复用 `validate_password_strength`，不满足返回 400 |
| 角色白名单 | 中 | 可选指定 `USER` / `DEV` / `ADMIN`，默认 `USER`，拒绝 `SU` |
| 邮箱冲突检测 | 高 | 邮箱已被注册返回 409 |
| OpenAPI 文档 | 低 | FastAPI 由路由与 Pydantic 模型自动生成，无需手写 |

### 2.2 业务流程

1. 调用方携带 `Authorization: Bearer <northbound_api_key>` 请求 `POST /nb/v1/users`
2. `_get_northbound_context` 解析 API Key → `ctx.user_id` / `ctx.tenant_id`；失败 → 401
3. `get_user_role_by_tenant(ctx.user_id, ctx.tenant_id)` 查询调用者角色；非 `ADMIN` → 403
4. Pydantic 校验请求体；不合法 → 422
5. 服务层：角色白名单校验 → 密码强度校验 → 邮箱存在预检 → 创建 Supabase 用户 → 写入租户关系
6. 返回 `201 { user_id, user_email, user_role, tenant_id }`

### 2.3 输入/输出

| 输入 | 来源 | 输出 | 描述 |
| ---- | ---- | ---- | ---- |
| `Authorization` 头 | 调用方 | 401 / 继续 | 北向 API Key（Bearer） |
| `email` | 请求体 | — | 必填，`EmailStr` |
| `initial_password` | 请求体 | — | 必填，≥8 位且含大小写字母与数字 |
| `name` | 请求体 | — | 可选，写入 Supabase `user_metadata.full_name` |
| `role` | 请求体 | — | 可选，默认 `USER`，白名单 `USER`/`DEV`/`ADMIN` |
| — | 系统 | 201 + 用户摘要 | 创建成功 |
| — | 系统 | 403 / 400 / 409 / 500 | 各类失败 |

## 3. 非功能需求

### 3.1 性能要求

- 响应时间：单次创建无强约束；邮箱预检走 Supabase 分页 `list_users`，用户量大时该调用是主要开销
- 并发数：租户用户数上限由 `MAX_USERS_PER_TENANT` 兜底，本端点不额外限流

### 3.2 安全要求

- **最小权限**：只有本租户 `ADMIN` 可调用；`SU`（平台超管）不放宽，也不允许被创建
- **不提权**：角色白名单显式排除 `SU`，避免北向接口成为提权入口
- **密码处理**：密码仅用于创建，不写日志、不出现在任何响应中
- **凭证**：Supabase 服务角色密钥只经 `get_supabase_admin_client()` 获取，不硬编码
- **审计**：`insert_user_tenant(created_by=...)` 记录创建者

### 3.3 兼容性要求

- 不改动既有邀请码自注册流程与既有北向端点
- 新增端点走 `/nb/v1` 前缀，与既有北向端点风格一致

## 4. 约束条件

### 4.1 技术约束

- 角色枚举由数据层决定：`SU` / `ADMIN` / `DEV` / `USER`
- 邮箱唯一性由 Supabase Auth 全局保证（一个邮箱 = 一个 Supabase 用户），
  因此邮箱唯一范围是**全局**而非"租户内"
- `insert_user_tenant` 内建 `_validate_user_tenant_limit`，自动执行
  `MAX_USERS_PER_TENANT` / `MAX_ADMINS_PER_TENANT` 硬限额

### 4.2 外部依赖

| 依赖项 | 说明 |
| ------ | ---- |
| Supabase Auth Admin API | `auth.admin.create_user` / `list_users`，依赖 `SERVICE_ROLE_KEY` |
| PostgreSQL（`user_tenant_t`） | 租户关系写入，由 `database.user_tenant_db` 封装 |

## 5. 角色与权限

### 5.1 角色清单

| 角色 | 描述 |
| ---- | ---- |
| `SU` | 平台超级管理员，全局唯一性受限（`MAX_SUPER_ADMIN_COUNT`） |
| `ADMIN` | 租户管理员，本接口的目标调用者 |
| `DEV` | 开发者 |
| `USER` | 普通用户，新用户默认角色 |

### 5.2 权限矩阵

| 调用者角色 | 可创建 `USER` | 可创建 `DEV` | 可创建 `ADMIN` | 可创建 `SU` |
| ---------- | ------------- | ------------ | -------------- | ----------- |
| `ADMIN`（本租户） | ✅ | ✅ | ✅（受管理员数上限） | ❌ 400 |
| `DEV` / `USER`（本租户） | ❌ 403 | ❌ 403 | ❌ 403 | ❌ 403 |
| `SU` | ❌ 403 | ❌ 403 | ❌ 403 | ❌ 403 |
| 无有效 API Key | ❌ 401 | ❌ 401 | ❌ 401 | ❌ 401 |

> 说明：需求原文为"只有租户管理员才能调用"，故 `SU` 不享受豁免；`SU` 走平台自有通道。

## 6. 需求拆分

### 6.1 特性清单（FE）

| FE 编号 | 特性名称 | 优先级 |
| ------- | -------- | ------ |
| FE1 | 北向创建用户端点 + API Key 鉴权 | 高 |
| FE2 | 租户管理员权限门禁 | 高 |
| FE3 | 用户创建服务（密码强度 / 角色白名单 / 邮箱冲突） | 高 |
| FE4 | 单元测试与错误码映射 | 中 |

### 6.2 UserStory 清单（US）

| US 编号 | UserStory | 验收标准 |
| ------- | --------- | -------- |
| US1 | 作为租户管理员，我要通过北向 API 直接创建用户 | 携带管理员 API Key 调用返回 201，返回新用户 `user_id`/`user_email`/`user_role`/`tenant_id` |
| US2 | 作为系统，我要阻止非管理员创建用户 | 非 `ADMIN` 调用返回 403，且不产生任何用户 |
| US3 | 作为系统，我要保证弱密码不能通过 | 不满足强度要求返回 400，且不产生任何用户 |
| US4 | 作为系统，我要阻止重复邮箱 | 邮箱已注册返回 409，且不产生任何用户 |
| US5 | 作为系统，我要阻止通过本接口提权 | 请求 `role=SU` 或未知角色返回 400 |

## 7. 验收标准

- [ ] `POST /nb/v1/users` 可通过北向 API Key 访问，并出现在 `/openapi.json`
- [ ] 非租户管理员调用返回 `403`
- [ ] 租户管理员可创建归属本租户的用户
- [ ] 弱密码返回 `400`；重复邮箱返回 `409`；非法角色返回 `400`
- [ ] 密码由 Supabase Auth 哈希存储，初始密码不出现在日志与响应中
- [ ] 单元测试覆盖：管理员成功 / 非管理员 403 / 弱密码 400 / 邮箱冲突 409 / 角色白名单拒绝
- [ ] 新增测试全部通过，且既有 `test_user_management_service.py` 不回归

## 8. 待确认事项

| 序号 | 问题 | 状态 | 备注 |
| ---- | ---- | ---- | ---- |
| 1 | 邮箱全局唯一 vs 租户内唯一 | 已确认：全局唯一 | Supabase Auth 决定，冲突即 409 |
| 2 | 创建后是否初始化租户工具 / 技能列表 | 已确认：不初始化 | `init_tool_list_for_tenant` 等按租户幂等，与单用户创建无必然关联 |
| 3 | 是否需要通知邮件 | 已确认：不需要 | 本仓无现成邮件通道 |
| 4 | `SU` 是否可调用 / 可被创建 | 已确认：均不允许 | 需求限定"只有租户管理员" |

## 9. 附录

### 9.1 原始需求描述

> 提供北向创建用户接口，只有租户管理员才能调用此接口

### 9.2 参考资料

- 既有北向端点：`backend/apps/northbound_app.py`、`backend/apps/northbound_knowledge_app.py`
- 既有注册流程：`backend/services/user_management_service.py:155`
- 租户关系数据层：`backend/database/user_tenant_db.py`
- 异常与错误码：`backend/consts/exceptions.py`、`backend/consts/error_code.py`
- Issue：https://github.com/ModelEngine-Group/nexent/issues/3822
