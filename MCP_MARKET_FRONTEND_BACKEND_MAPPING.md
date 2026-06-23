# MCP 市场前后端对照表

## 1. 页面视图与接口对照

| 前端区域 | 前端功能 | 前端文件 / Hook | 当前接口 | 后端入口 | 当前状态 |
|---|---|---|---|---|---|
| 仓库标签页 | 查询仓库 MCP 列表 | `page.tsx` / `useMcpCommunityBrowser` | `GET /api/mcp-tools/community/list` | `backend/apps/mcp_management_app.py` | 已有 |
| 仓库标签页 | 搜索 MCP | `useMcpCommunityBrowser` | `GET /community/list?search=` | `list_community_mcp_services_api` | 已有 |
| 仓库标签页 | 按标签筛选 | `useMcpCommunityBrowser` | `GET /community/list?tag=` | `list_community_mcp_services_api` | 已有 |
| 仓库标签页 | 分页 | `useMcpCommunityBrowser` | `GET /community/list?cursor=&limit=` | `list_community_mcp_services_api` | 已有 |
| 仓库标签页 | 按 MCP 类型筛选 | `page.tsx` 前端本地筛选 | 无专门后端字段 | 依赖 `transport_type` / 前端推导 | 部分支持 |
| 仓库卡片 | 显示名称、描述、标签、版本 | `RepositoryMcpCard.tsx` | `community/list` | `McpCommunityRecord` | 已有 |
| 仓库卡片 | 显示评分 | `RepositoryMcpCard.tsx` | 期望 `rating` | 后端未返回 | 缺失 |
| 仓库卡片 | 显示下载量 | `RepositoryMcpCard.tsx` | 期望 `installCount` | 后端未返回 | 缺失 |
| 仓库卡片 | 显示类型图标 | `TransportIcon.tsx` | 依赖 `transportType` / `deploymentType` | 后端返回 `transport_type` | 部分支持 |
| 仓库卡片 | 安装 / 快速添加 | `useMcpCommunityQuickAdd` | `POST /api/mcp/add` 或 `/api/mcp/add-from-config` | `remote_mcp_app.py` | 已有 |
| 我的标签页 | 查询本地 MCP | `useMcpServicesList` | `GET /api/mcp/list` | `remote_mcp_app.py` | 已有 |
| 我的标签页 | 查询我已发布 MCP | `useMyCommunityMcp` | `GET /api/mcp-tools/community/mine` | `mcp_management_app.py` | 已有但语义有问题 |
| 我的标签页 | 显示当前版本 | `MineMcpServiceCard.tsx` | 期望本地 MCP 有 `version` | 本地 MCP 表无 `version` | 缺失 |
| 我的标签页 | 显示线上版本 | `page.tsx` 前端匹配 `myPublished.items` | `community/mine` | `McpCommunityRecord.version` | 已有 |
| 我的标签页 | 最近更新时间 | `MineMcpServiceCard.tsx` | `updatedAt` | 本地 `update_time` / 社区 `update_time` | 已有 |
| 我的标签页 | 右上角 `...` 菜单 | `MineMcpServiceCard.tsx` | 调用发布/更新/删除接口 | 多个接口组合 | 前端已接 |
| 我的标签页 | 提交版本更新：未上线则发布 | `page.tsx` | `POST /community/publish` | `publish_community_mcp_service_api` | 已有 |
| 我的标签页 | 提交版本更新：已上线则更新 | `page.tsx` | `PUT /community/update` | `update_community_mcp_service_api` | 部分支持 |
| 我的标签页 | 下架线上版本 | `page.tsx` | `DELETE /community/delete` | `delete_community_mcp_service_api` | 已有 |
| 审核中心 | 待审核列表 | `ReviewCenterView` | 无 | 无 | 缺失 |
| 审核中心 | 通过 / 拒绝 | `ReviewCenterView` | 无 | 无 | 缺失 |

## 2. 前端类型字段与后端字段对照

### 2.1 仓库 MCP：`CommunityMcpCard`

前端类型：`frontend/types/mcpTools.ts`

| 前端字段 | 含义 | 后端来源 | 当前是否支持 | 备注 |
|---|---|---|---|---|
| `communityId` | 仓库记录 ID | `community_id` | 支持 | 来自 `McpCommunityRecord` |
| `name` | MCP 名称 | `mcp_name` | 支持 |  |
| `version` | 线上版本 | `version` | 支持 |  |
| `description` | 描述 | `description` | 支持 |  |
| `createdAt` | 创建时间 | `create_time` | 支持 |  |
| `updatedAt` | 更新时间 | `update_time` | 支持 |  |
| `serverUrl` | MCP 服务地址 | `mcp_server` | 支持 |  |
| `transportType` | 传输类型 | `transport_type` | 支持 | 但粒度较粗 |
| `configJson` | 容器配置 | `config_json` | 支持 | 发布时可写入 |
| `registryJson` | registry 元数据 | `registry_json` | 支持 |  |
| `tags` | 标签 | `tags` | 支持 |  |
| `rating` | 评分 | 无 | 不支持 | 前端显示为 0.0/5 |
| `installCount` | 下载 / 安装量 | 无 | 不支持 | 前端显示为 0 |
| `deploymentType` | 部署类型 | 无直接字段 | 前端推导 | 由 `transportType/configJson` 推导 |
| `reviewStatus` | 审核状态 | 无 | 不支持 | 前端类型预留 |

### 2.2 我的本地 MCP：`McpServiceItem`

前端类型：`frontend/types/mcpTools.ts`

| 前端字段 | 含义 | 后端来源 | 当前是否支持 | 备注 |
|---|---|---|---|---|
| `mcpId` | 本地 MCP ID | `mcp_id` | 支持 |  |
| `name` | MCP 名称 | `mcp_name` / `remote_mcp_server_name` | 支持 |  |
| `description` | 描述 | `description` | 支持 |  |
| `serverUrl` | 服务地址 | `mcp_server` | 支持 |  |
| `enabled` | 启用状态 | `enabled` | 支持 |  |
| `updatedAt` | 更新时间 | `update_time` | 支持 |  |
| `tags` | 标签 | `tags` | 支持 |  |
| `transportType` | 传输类型 | 前端根据 `config_json` 推导 | 部分支持 | 本地表未明确保存 HTTP/SSE 类型 |
| `version` | 当前版本 | 后端无字段 | 不支持 | 这是当前主要缺口 |
| `registryJson` | registry 元数据 | `registry_json` | 支持 |  |
| `configJson` | 容器配置 | `config_json` | 支持 |  |
| `healthStatus` | 健康状态 | `status` | 部分支持 | `false` 当前前端映射成 `unchecked` |
| `containerId` | 容器 ID | `container_id` | 支持 |  |
| `containerPort` | 容器端口 | `container_port` | 支持 |  |
| `authorizationToken` | 鉴权 token | `authorization_token` | 支持 |  |
| `customHeaders` | 自定义 header | `custom_headers` | 支持 |  |
| `communityId` | 对应线上记录 ID | 后端可能返回 `community_id` | 不确定 | 前端已映射，但后端本地表未看到稳定字段 |
| `isListedInRepository` | 是否已上架仓库 | 后端可能返回 `is_listed_in_repository` | 不确定 | 前端已映射，但后端需补 |

## 3. 动作接口对照

| 动作 | 前端调用 | 接口 | 后端 service | 当前问题 |
|---|---|---|---|---|
| 查询仓库列表 | `listCommunityMcpTools` | `GET /api/mcp-tools/community/list` | `list_community_mcp_services` | 缺少评分、下载量、审核状态 |
| 查询我的发布 | `listMyCommunityMcpTools` | `GET /api/mcp-tools/community/mine` | `list_my_community_mcp_services` | 实际按 tenant 查，不一定按当前 user 查 |
| 发布本地 MCP | `publishCommunityMcpTool` | `POST /api/mcp-tools/community/publish` | `publish_community_mcp_service` | 可用 |
| 更新线上 MCP | `updateCommunityMcpTool` | `PUT /api/mcp-tools/community/update` | `update_community_mcp_service` | 后端忽略 `config_json`，不能完整同步容器配置 |
| 下架线上 MCP | `deleteCommunityMcpTool` | `DELETE /api/mcp-tools/community/delete` | `delete_community_mcp_service` | 当前是软删除，不是 offline 状态 |
| 安装仓库 MCP | `addMcpToolService` / `addContainerMcpToolService` | `POST /api/mcp/add` / `POST /api/mcp/add-from-config` | `add_mcp_service` / `add_container_mcp_service` | 不会增加下载量 |
| 启用本地 MCP | `enableMcpToolService` | `POST /api/mcp/enable` | `update_mcp_service_enabled` | 可用 |
| 禁用本地 MCP | `disableMcpToolService` | `POST /api/mcp/disable` | `update_mcp_service_enabled` | 可用 |
| 删除本地 MCP | `deleteMcpToolService` | `DELETE /api/mcp/{mcp_id}` | `delete_mcp_service` | 可用 |

## 4. 当前主要缺口

| 优先级 | 缺口 | 影响 | 建议 |
|---|---|---|---|
| 高 | 本地 MCP 没有 `version` 字段 | “我的”页当前版本显示不可靠 | 给 `McpRecord` 增加 `version` 字段，并在 add/update/list 中支持 |
| 高 | 本地 MCP 与线上 MCP 缺少稳定关联 | 前端只能按 `communityId` 或名称匹配，名称匹配不可靠 | 在本地 MCP 记录中保存 `community_id` 或维护关联表 |
| 高 | `/community/mine` 实际可能按 tenant 查 | “我的”可能显示同租户其他人的发布 | 改为按 `tenant_id + user_id` 查询 |
| 高 | 更新线上版本时不能更新 `mcp_server/config_json` | “提交版本更新”不能完整同步配置 | 扩展 `CommunityUpdateRequest` 和 service，支持 `mcp_server`、`config_json`、`transport_type` |
| 中 | 仓库评分 `rating` 缺失 | 前端评分始终为默认值 | 表中增加评分字段或统计表 |
| 中 | 下载量 / 安装量 `installCount` 缺失 | 前端下载量始终为 0 | 快速添加成功后回写安装次数 |
| 中 | 审核状态 `reviewStatus` 缺失 | 审核中心无法接入 | 增加 `review_status` 字段和审核接口 |
| 中 | 部署类型 `deploymentType` 后端未返回 | 类型筛选依赖前端推导 | 后端返回明确 `deployment_type` |
| 低 | 健康状态映射不准确 | 不健康服务可能显示为未检查 | 前端或后端明确区分 `healthy/unhealthy/unchecked` |
| 低 | `listMcpTools(params)` 参数未下推 | 标签筛选只能前端完成 | 如数据量变大，再补后端筛选 |

## 5. 建议后端补齐顺序

### 第一阶段：支撑当前前端功能跑通

| 内容 | 后端改动 |
|---|---|
| 本地 MCP 版本 | `McpRecord` 增加 `version`，`AddMcpServiceRequest` / `UpdateMcpServiceRequest` / list 返回支持 |
| 本地-线上关联 | `McpRecord` 增加 `community_id` 或关联表 |
| 我的发布只查当前用户 | `/community/mine` 改为 `tenant_id + user_id` |
| 更新线上版本同步配置 | `/community/update` 支持 `mcp_server`、`config_json`、`transport_type` |

### 第二阶段：补市场属性

| 内容 | 后端改动 |
|---|---|
| 下载量 | `McpCommunityRecord.install_count`，QuickAdd 成功后 +1 |
| 评分 | `rating` / `rating_count` 或独立评分表 |
| 审核状态 | `review_status` 字段 |
| 部署类型 | `deployment_type` 字段或后端统一推导返回 |

### 第三阶段：审核中心

| 内容 | 后端接口 |
|---|---|
| 待审核列表 | `GET /api/mcp-tools/community/review/list` |
| 通过审核 | `POST /api/mcp-tools/community/review/approve` |
| 拒绝审核 | `POST /api/mcp-tools/community/review/reject` |
| 管理员下架 | `POST /api/mcp-tools/community/offline` |
