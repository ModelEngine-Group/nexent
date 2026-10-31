# Nexent 管理面（Admin Console）资产盘点报告

- 日期：2026-10-08
- 作者：数析（Metric）· 数据分析师
- 范围：仅代码研究盘点，未修改任何代码
- 代码库：C:\code\nexent（backend/ FastAPI + frontend/ Next.js）

---

## 0. 总体规模感

| 层 | 管理面相关资产 | 规模（粗粒度） |
|---|---|---|
| 后端 apps | 13 个管理面相关 app | ~4,700 行（另有 quota_service 1,676 行、permissions 包 349 行） |
| 前端页面 | 4 个入口页面（owner-manage / resource-manage / users / models） | ~230 行壳代码 |
| 前端管理组件 | 18 个组件（resources/ 15 个 + 上层 3 个） | ~10,500 行 |
| 数据库 | 管理面核心表 8 张 + 配额以 KV 形式存在 tenant_config_t | — |

整体判断：管理面是**已成形的多租户资源管理台**，非原型；但监控、审计、计费三大企业级能力明显薄弱。

---

## 1. 角色与权限模型（理解管理面的前提）

### 1.1 角色体系（6 种）
`SU`（超级管理员，默认上限 1）、`ADMIN`（租户管理员）、`USER`、`SPEED`（平台运营/极速模式）、`DEV`、`ASSET_OWNER`（资产所有者，特性开关默认关闭 `ENABLE_ASSET_OWNER_ROLE=false`）。

### 1.2 RBAC + DAC 双层
- **backend/permissions/**（5 个文件，349 行）：
  - `rbac.py`：`init_rbac()` 从 DB 加载 role_permission_t，`has_permission(role, permission)` 判定；权限串格式 `type:subtype`（如 `kb.capacity:read`）
  - `dac.py`：资源级访问控制（ResourceAccessControl），角色集合：MANAGEMENT_ROLES={SU,ADMIN,SPEED,ASSET_OWNER}、GROUP_ACCESS_ROLES={USER,DEV}，支持 private/group 资源
  - `depends.py`：FastAPI 依赖 `authenticate` / `require(permission)`
  - `tenant_scope.py`：SU/SPEED 跨租户解析（个人 KB）
- **前端**：`components/permission/Can.tsx` / `Cannot.tsx`（声明式权限组件）+ `AuthorizationProvider`（角色上下文）

### 1.3 关键环境变量（backend/consts/const.py）

| 变量 | 默认值 | 含义 |
|---|---|---|
| MAX_TENANT_COUNT | 100 | 租户上限 |
| MAX_USERS_PER_TENANT | 10,000 | 租户用户上限 |
| MAX_GROUPS_PER_TENANT | 1,000 | 租户分组上限 |
| MAX_SUPER_ADMIN_COUNT | 1 | SU 上限 |
| MAX_ADMINS_PER_TENANT | 1,000 | 租户管理员上限 |
| MAX_KNOWLEDGE_BASES_PER_TENANT | 10,000 | KB 上限 |
| MAX_AGENTS_PER_TENANT / MAX_SKILLS_PER_TENANT | 1,000 | Agent/Skill 上限 |
| MAX_MCP_SERVICES_PER_TENANT | （代码内默认） | MCP 上限 |
| ENABLE_ASSET_OWNER_ROLE | false | ASSET_OWNER 角色总开关（关闭时阻止其邀请/注册/登录） |
| MONITORING_DASHBOARD_ALLOWED_ROLES | "SU,SPEED" | 监控面板可见角色 |
| CAS_ROLE_ATTRIBUTE / CAS_TENANT_ATTRIBUTE / CAS_ROLE_MAP_JSON 等 | — | CAS 属性映射 |
| SYSTEM_TENANT_ID | "system" | 系统租户 |

---

## 2. 管理面资产清单（模块 × API × 前端入口 × 数据表）

### 2.1 租户管理
- **后端** `tenant_app.py`（339 行）：
  - `GET /{tenant_id}`、`POST /tenant-list`（分页列表）、`PUT /{tenant_id}`、`DELETE /{tenant_id}`
- **前端**：`resource-manage` 页面内 `UserManageComp.tsx`（1,441 行）的左侧租户列表（TenantList 组件）：创建/编辑/删除租户、选中后切换 tab 上下文
- **数据表**：`tenant_config_t`（租户 KV 配置，含配额值）、`user_tenant_t`（用户-租户关系，426 行 DB 模块）
- **完整度**：✅ 基本完整（CRUD + 邀请联动）

### 2.2 用户与成员管理
- **后端**：
  - `user_management_app.py`（521 行）：signup / signin / refresh_token / logout / session / current_user_info / revoke / tokens GET·POST·DELETE / password PUT（账户自服务 + Token 管理）
  - `user_app.py`（233 行）：`POST /list`、`PUT /{user_id}`、`DELETE /{user_id}`（管理员侧用户管理）
  - `mock_user_management_app.py`：开发用 mock（用户自服务形态存在双轨）
- **前端**：`resources/UserList.tsx`（448 行）——租户内用户列表；`users/page.tsx` → `UserProfileComp.tsx`（736 行）——个人资料页
- **数据表**：`user_tenant_t`（Supabase auth 为主，本地表存角色映射）
- **完整度**：✅ 完整（列表/改角色/删除）；⚠️ 无批量导入（SCIM/CSV）【TBD-竞析：Dify/LangGraph 是否有】

### 2.3 邀请制入驻
- **后端** `invitation_app.py`（564 行）：`POST /list`、`POST ""`（创建）、`PUT/GET /{code}`、`GET /{code}/check`、`DELETE /{code}`、`GET /{code}/available`、`POST /{code}/use`、`POST /{code}/update-status`
- **前端**：`resources/InvitationList.tsx`（675 行）
- **数据表**：`tenant_invitation_code_t`、`tenant_invitation_record_t`
- **完整度**：✅ 完整且超出同类开源产品（有 check/use/状态机）；支持 ASSET_OWNER_INVITE 专用类型

### 2.4 分组（Group）
- **后端** `group_app.py`（783 行）：组 CRUD（GET/POST list/PUT/DELETE）、成员 CRUD（POST·GET·PUT `/{group_id}/members`、DELETE `/{group_id}/members/{user_id}`）、`POST /members/batch`（批量）、`GET/PUT /tenants/{tenant_id}/default`（默认组）
- **前端**：`resources/GroupList.tsx`（466 行）
- **数据表**：`tenant_group_info_t`、`tenant_group_user_t`
- **完整度**：✅ 完整（含批量与默认组）；分组用于 DAC 资源共享

### 2.5 API Key 管理
- **后端** `api_key_app.py`（131 行）：`GET ""`（分页列表）、`POST /refresh`（轮换）、`DELETE ""`（吊销）；有审计埋点（record_security_event）
- **前端**：`resources/ApiKeyList.tsx`（211 行）
- **数据表**：无独立表（Supabase token 体系 / api_key_service）
- **完整度**：✅ 够用；⚠️ 无 key 过期策略/作用域细分【TBD-竞析】

### 2.6 配额（Quota）——管理面最重的模块
- **后端** `quota_app.py`（759 行）+ `quota_service.py`（1,676 行），三个 router：
  - **租户级**（prefix `/tenants`）：`GET/PUT/DELETE /{tenant_id}/quota`（硬限额）、`GET /{tenant_id}/quota/usage`
  - **平台级**（prefix `/platform/quota`）：`GET /overview`、`PUT/DELETE /capacity`（平台总容量）、`PUT/DELETE /tenants/{tenant_id}`（SU/SPEED/ASSET_OWNER 分配）
  - **个人级**（prefix `/capacity/personal`）：`GET /me`、`GET /users`、`GET /users/{user_id}/kbs`、`GET /summary`、`PUT /users/{user_id}/quota`、`GET/PUT /default-quota`（默认个人配额）
  - 配额服务能力：硬限额/预警配置/KB 软配额/个人配额/用量聚合/写后检查（check_hard_limit_post_write）
- **前端**：`PlatformQuotaPanel.tsx`（660 行，平台容量分配面板）、`QuotaSettingsModal.tsx`（655 行）、`SuQuotaModal.tsx`（289 行，SU 专用）、`PersonalKnowledgeBaseCapacity.tsx`（1,173 行，个人 KB 容量管理）、`components/quota/QuotaWarningMonitor.tsx`（128 行，全局配额预警监控）
- **数据表**：无独立 quota 表 —— 配额值以 KV 存于 `tenant_config_t`；`knowledge_record_t.quota_limit_bytes`（v2.4 增加）
- **完整度**：✅ 三层配额（平台→租户→个人/KB）体系完整，超出多数开源竞品；⚠️ 仅覆盖**存储容量**维度，无 token/调用次数/算力计费维度【TBD-竞析：Dify 云版/Coze 的配额维度】

### 2.7 资源管理（Agent/KB/MCP/Skill/Model 的管理视图）
- **后端**：`model_managment_app.py`（1,334 行，注意文件名拼写 managment）：模型 CRUD、provider 批量、healthcheck（含 temporary/manage 变体）、`/suggest-capacity`、`/capacity-coverage`（模型能力覆盖）、`/catalog/*`（模型目录）。Agent/KB/MCP/Skill 管理分散在各自 app，此处为管理面聚合视图
- **前端**（resource-manage / owner-manage 共用组件）：
  - `AgentList.tsx`（818 行）、`KnowledgeList.tsx`（755 行）、`McpList.tsx`（1,079 行）、`SkillList.tsx`（861 行）、`ModelList.tsx`（558 行）、`ModelCapacityCoverageWidget.tsx`（66 行）
  - `models/page.tsx`（39 行）→ `ModelConfiguration.tsx`（118 行）+ `modelConfig.tsx`：面向普通用户的模型配置页
- **数据表**：`model_record_t`（含 capacity_source/capacity_fingerprint/tokenizer_family）、`model_monitoring_record_t`、各业务表
- **完整度**：✅ 管理视图完整；模型容量画像（capacity-coverage）是差异化亮点

### 2.8 两种管理入口（双形态）
| 入口 | 路由 | 目标角色 | 组件 |
|---|---|---|---|
| 租户资源管理 | `/[locale]/resource-manage` | SU/ADMIN | `UserManageComp.tsx`（租户选择器 + 9 个 tab + 项目配置 tab） |
| 资产所有者管理 | `/[locale]/owner-manage` | ASSET_OWNER | `AssetOwnerResourcesComp.tsx`（平台租户 + 平台配额 tab） |
| 个人资料 | `/[locale]/users` | 所有用户 | `UserProfileComp.tsx` |
| 模型配置 | `/[locale]/models` | 所有用户 | `ModelConfiguration.tsx` |

tab 清单（resource-manage）：users / apiKeys / groups / models / knowledge（AIDP 启用时移至统一入口）/ agents / mcp / skills / invitations / projectConfig（含 showPlatformQuota）。

### 2.9 认证集成（CAS / OAuth）
- **后端**：`cas_app.py`（177 行）：config/login/callback(GET·POST)/renew/renew_callback/logout_callback；`oauth_app.py`（393 行）：config/providers/authorize/link/callback/pending/complete/accounts + DELETE accounts/{provider}（账号绑定管理）
- **数据表**：`user_cas_session_t`（v2.2）、`user_oauth_account_t`（v2.0）
- **完整度**：✅ CAS 企业 SSO + OAuth 提供商均有；⚠️ 无 SAML/OIDC 通用协议【TBD-竞析：企业客户刚需度】

### 2.10 通知
- **后端** `notification_app.py`（82 行）：`GET ""`（列表）、`POST /read`；表 `notification_t` + `notification_receiver_t`（v2.3）
- **前端**：TopNavbar 通知铃铛
- **完整度**：⚠️ 极简（站内信）；无邮件/webhook 渠道【TBD-竞析】

### 2.11 监控（Monitoring）—— 明显薄弱
- **后端** `monitoring_app.py`（169 行）仅 2 个路由：
  - `GET /monitoring/models`（模型指标查询，基于 model_monitoring_record_t）
  - `GET /monitoring/status`（telemetry 状态 + dashboard URL）
- **前端**：**没有独立监控页面**，仅 TopNavbar 中一个外链（buildMonitoringUrl → 外部 telemetry dashboard，角色门槛 MONITORING_DASHBOARD_ALLOWED_ROLES）
- **完整度**：❌ 半成品/外部依赖。指标只覆盖模型调用；无系统健康、租户活跃、用量大盘

### 2.12 审计（Audit）—— 最薄弱
- **后端** `services/audit_service.py`（128 行）：`record_security_event()` 把 `[SEC_AUDIT]` 单行日志写入**日志文件**（audit.security logger），best-effort、只记成功操作
- **数据表**：**无审计表**（SQL 中无 security_event/audit_log 表；仅 memory_dreaming_audit_t 属于记忆功能）
- **前端**：无任何审计查看界面
- **完整度**：❌ 占位级。不可查询、不可检索、无管理界面——企业级合规硬伤

### 2.13 其他
- `tenant_config_app.py`（42 行）：`GET /deployment_version`（版本查询）
- `permission_utils.py`（32 行）：KB 读/写权限检查（业务侧工具函数）
- `config_app.py` / `config_sync_app.py`：系统配置（未详查，属相邻模块）

---

## 3. 数据表总览（管理面相关，deploy/sql/）

| 表名 | 迁移版本 | 用途 |
|---|---|---|
| tenant_config_t | v1 | 租户 KV 配置（**配额值也存这里**） |
| user_tenant_t | v1 | 用户-租户-角色 |
| tenant_invitation_code_t / record_t | v1 | 邀请码与使用记录 |
| tenant_group_info_t / user_t | v1 | 分组及成员 |
| role_permission_t | v1 起，多个版本持续 INSERT | RBAC 权限矩阵（category/type/subtype/parent_key） |
| user_token_usage_log_t | v1 | Token 用量日志 |
| model_record_t / model_monitoring_record_t | init / v2.0 | 模型与模型监控 |
| user_cas_session_t / user_oauth_account_t | v2.2 / v2.0 | SSO 会话与 OAuth 绑定 |
| notification_t / receiver_t | v2.3 | 站内通知 |
| knowledge_record_t.quota_limit_bytes | v2.4 | KB 软配额列 |
| aidp_kb_permission_t | v2.4 | AIDP 知识库权限（合作形态） |

---

## 4. 功能完整度评估汇总

| 能力 | 状态 | 依据 |
|---|---|---|
| 多租户 CRUD | ✅ 完整 | tenant_app 4 路由 + 前端租户选择器 |
| 用户/成员管理 | ✅ 完整 | user_app + UserList；无批量导入 |
| 角色权限（RBAC+DAC） | ✅ 完整 | permissions 包 + role_permission_t + 前端 Can/Cannot |
| 分组管理 | ✅ 完整 | group_app 11 路由（含批量/默认组） |
| 邀请制入驻 | ✅ 完整 | invitation_app 9 路由，带状态机 |
| API Key 管理 | ✅ 基本完整 | 列表/轮换/吊销 + 审计埋点 |
| 三层配额 | ✅ 完整（仅存储维度） | quota 三 router + 5 个前端组件；无 token/调用次数计费 |
| 模型管理 | ✅ 完整 + 差异化 | capacity-coverage 能力画像 |
| SSO（CAS/OAuth） | ✅ 完整 | 无 SAML/OIDC |
| 通知 | ⚠️ 极简 | 仅站内信 2 路由 |
| 监控大盘 | ❌ 半成品/外部化 | 仅 2 路由，无前端页面，外链 telemetry |
| 审计日志 | ❌ 占位级 | 仅日志文件，无表、无查询 API、无 UI |
| 计费/订阅 | ❌ 缺失 | 无任何相关代码 |
| 组织架构/部门树 | ❌ 缺失 | Group 是平的，无层级 |
| 数据合规/导出 | ❌ 缺失 | 无导出/擦除工具 |
| 单点管理台统一 | ⚠️ 双入口 | resource-manage（管理员）与 owner-manage（资产所有者）并存，组件复用 |

---

## 5. 与典型企业级管理面的差距分析（TBD 待竞析确认）

以典型企业级平台管理台（参考 Dify Cloud、Azure OpenAI Studio、Coze 企业版、LangSmith Org 管理面的常见能力基线）对照：

1. **审计与合规**：差距最大。行业基线通常有可查询审计日志（谁在何时改了什么配置/权限）+ 导出。Nexent 只有日志文件行。【TBD-竞析：Dify/LangGraph 的审计能力与呈现形式】
2. **用量/计费仪表盘**：企业客户预期有 token 消耗、按租户/用户/模型的用量报表。Nexent 配额只管存储字节。【TBD-竞析：各竞品计费维度与报表颗粒度】
3. **监控可观测性**：行业基线含服务健康、错误率、延迟、租户活跃度。Nexent 外链外部 telemetry，产品内无统一大盘。【TBD-竞析：内置 vs 外链的做法分布】
4. **SSO 协议覆盖**：企业采购常要求 SAML/OIDC/LDAP。Nexent 有 CAS+OAuth。【TBD-竞析：开源 Agent 平台普遍支持哪些协议】
5. **组织层级**：部门树/组织架构映射（HR 同步）。Nexent Group 为扁平结构。【TBD-竞析：是否普遍缺失（可能是开源产品共性短板=机会点）】
6. **细粒度权限自定义**：role_permission_t 为内置角色固定矩阵（SQL 硬编码 INSERT），无自定义角色/权限编辑 UI。【TBD-竞析：自定义角色的普遍性】
7. **配额维度**：企业级需要 token/RPM/并发维度，不只是存储。【TBD-竞析：Dify 云版的配额模型】
8. **已有优势**（竞析应重点验证的差异化）：三层配额体系（平台→租户→个人/KB）、邀请码状态机、模型能力覆盖画像（capacity-coverage）、ASSET_OWNER 运营形态（适合 MSP/托管服务商场景）。

---

## 6. 代码量明细（粗粒度）

**后端（管理面 apps，行数）**：tenant_app 339 / user_management_app 521 / user_app 233 / group_app 783 / api_key_app 131 / quota_app 759 / monitoring_app 169 / permission_utils 32 / cas_app 177 / oauth_app 393 / notification_app 82 / invitation_app 564 / tenant_config_app 42（合计 ~4,225）+ model_managment_app 1,334（资源管理侧）≈ **5,560 行**；服务层 quota_service 1,676 + audit_service 128；permissions 包 349。

**前端（管理面）**：页面壳 230；resource-manage 组件 ~10,535（其中 UserManageComp 1,441、PersonalKnowledgeBaseCapacity 1,173、McpList 1,079、AgentList 818 为最大件）；users 组件 736；permission/quota 公共组件 ~200。**合计约 11,700 行**。

**DB 迁移**：v1→v2.7 共 10 个合并迁移文件，管理面相关表集中在 v1。

---

## 7. 一句话结论

Nexent 管理面在「多租户 + 资源 + 配额 + 邀请 + 分组 + RBAC/DAC」这条主线上已是**可运营级完成度**（前端 1 万+ 行、三层配额体系完整）；短板集中在**审计（占位）、监控（外链半成品）、计费用量（缺失）**三大企业采购硬指标上，且角色矩阵 SQL 硬编码、双管理入口（resource-manage/owner-manage）带来维护成本。这三块 + 自定义角色应是与竞品拉差对比的核心验证点（TBD 待竞析确认）。
