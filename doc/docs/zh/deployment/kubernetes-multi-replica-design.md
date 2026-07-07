# Kubernetes 多副本改造设计

## 1. 背景与目标

当前 Kubernetes Helm 部署可以把大部分服务的 `replicaCount` 调大，但项目并不等同于无状态服务。应用层存在进程内运行状态、流式连接状态、后台调度状态和动态 MCP 注册状态；基础设施层也使用单实例 PVC。直接扩容会出现流式恢复失败、停止任务失效、MCP 工具列表不一致、后台任务重复执行、PVC 无法跨节点挂载等问题。

本设计文档的目标是定义“业务应用层多副本”的分阶段改造方案。第一阶段落地四个应用服务的手工多副本：

- `nexent-web`
- `nexent-config`
- `nexent-runtime`
- `nexent-northbound`

第一阶段明确不改 `nexent-mcp`、`nexent-data-process` 的多副本能力；这些组件继续按单副本运行，后续阶段再单独设计。

第一阶段不要求内置 Postgres、Redis、Elasticsearch、MinIO、Supabase DB 做集群高可用。这些组件仍保持单实例，或由生产环境替换为外部托管服务。

第一阶段的“扩缩容”仅指通过 Helm `replicaCount` 手工调整副本数，不启用 autoscaling/HPA。

## 2. 当前状态问题清单

### 2.1 Helm 与存储

当前默认值：

- `deploy/k8s/helm/nexent/values.yaml`
  - `global.sharedStorage.mode: local`
  - `global.sharedStorage.accessModes: ReadWriteOnce`
  - `workspace.localPath: /var/lib/nexent`
  - `skills.localPath: /var/lib/nexent-data/skills`
- `deploy/k8s/helm/nexent/charts/nexent-common/templates/shared-storage.yaml`
  - local 模式会创建 `hostPath` PV。

业务服务挂载共享卷：

- `nexent-config`: `/mnt/nexent`, `/mnt/nexent-data/skills`
- `nexent-runtime`: `/mnt/nexent`, `/mnt/nexent-data/skills`
- `nexent-northbound`: `/mnt/nexent`, `/mnt/nexent-data/skills`
- `nexent-mcp`: `/mnt/nexent`
- `nexent-data-process`: `/mnt/nexent`

问题：

- `ReadWriteOnce` 通常不能跨节点被多个 Pod 同时读写。
- `hostPath` 强绑定节点，Pod 调度到其他节点后看不到相同数据。
- 技能目录和工作区被多个业务服务读写，不能按普通临时目录处理。

### 2.2 Runtime 流式对话状态

相关代码：

- `backend/services/streaming_channel.py`
- `backend/agents/agent_run_manager.py`
- `backend/agents/preprocess_manager.py`
- `backend/services/agent_service.py`

当前状态：

- `StreamingChannelManager` 是进程内 singleton，`_channels` 保存 SSE 历史、订阅者和完成状态。
- `AgentRunManager` 是进程内 singleton，保存 `agent_runs`、`stop_event`、conversation 级 `ContextManager`。
- `PreprocessManager` 是进程内 singleton，保存预处理任务和取消句柄。

问题：

- 用户发起 `/api/agent/run` 后，如果重连请求落到另一个 `nexent-runtime` Pod，另一个 Pod 找不到原来的 channel。
- `/api/agent/stop/{conversation_id}` 落到非 owner Pod 时，找不到原来的 `stop_event`。
- 正在运行的 agent 状态只存在本地内存，Pod 重启后无法恢复运行控制。
- conversation 级 `ContextManager` 如果参与正确性，跨 Pod 会产生上下文不一致；如果只是优化，可以允许 miss 后重建。

### 2.3 MCP 动态工具状态

相关代码：

- `backend/mcp_service.py`
- `backend/services/tool_configuration_service.py`
- `backend/apps/tool_config_app.py`

当前状态：

- `mcp_service.py` 中 `_openapi_mcp_services` 是进程内 dict。
- `refresh_openapi_services_by_tenant` 会清理并重新 mount 当前进程中的 FastMCP 服务。
- config 服务通过 `MCP_MANAGEMENT_API` 调用 `nexent-mcp:5015` 刷新 MCP 服务。

问题：

- 多个 `nexent-mcp` Pod 后，Service 只会把刷新请求转发到其中一个 Pod。
- 被刷新 Pod 的工具列表正确，其他 Pod 仍是旧状态。
- FastMCP mount 状态无法仅靠 DB 查询自动保持一致。

### 2.4 Data Process 与后台调度

相关代码：

- `backend/data_process_service.py`
- `backend/data_process/app.py`
- `backend/data_process/worker.py`
- `backend/services/auto_summary_scheduler.py`

当前状态：

- `data_process_service.py` 在一个 Pod 中启动 Redis 连接检查、Ray、Celery workers、Flower 和 FastAPI。
- `service_processes` 保存本地启动的 worker、Flower、Ray 状态。
- `auto_summary_scheduler` 在进程内启动线程，`_in_flight` 只做单进程去重。

问题：

- 多个 data-process Pod 会各自启动 Ray 和 worker，需要重新设计队列消费和 Ray 拓扑。
- auto-summary 在多 Pod 下会重复扫描并处理相同知识库。
- Flower 和 Ray dashboard 不适合作为每个副本都暴露的应用端口。

### 2.5 Northbound 幂等与限流

相关代码：

- `backend/services/northbound_service.py`

当前状态：

- `_IDEMPOTENCY_RUNNING` 是进程内 dict。
- `_RATE_STATE` 是进程内 dict。

问题：

- 同一 `Idempotency-Key` 的并发请求打到不同 Pod 时会同时执行。
- 租户级每分钟限流在每个 Pod 单独计数，实际总额度会随副本数线性放大。

### 2.6 基础设施组件

当前 Helm chart 中以下组件是带 PVC 的单实例 Deployment：

- `nexent-postgresql`
- `nexent-redis`
- `nexent-elasticsearch`
- `nexent-minio`
- `nexent-supabase-db`

问题：

- Elasticsearch 使用 `discovery.type=single-node`，不能通过 `replicaCount` 变成集群。
- Postgres、Redis、MinIO、Supabase DB 没有 StatefulSet、主从、Sentinel、Operator 或分布式部署配置。
- 这些组件第一阶段必须明确为单实例状态依赖，不参与横向扩容。

## 3. 目标架构

### 3.1 状态分层

改造后状态分为四类：

| 状态类型 | 例子 | 第一阶段承载位置 |
| --- | --- | --- |
| 持久业务状态 | 用户、租户、智能体、消息、MCP 配置 | Postgres |
| 对象与文件状态 | 上传文件、预览缓存、技能 zip 或产物 | MinIO 或 RWX PVC |
| 短生命周期运行状态 | SSE 事件、运行任务 owner、取消信号、幂等键、限流计数 | Redis |
| 本地优化缓存 | HTTP client、模型实例、可重建 ContextManager | Pod 内存 |

原则：

- 影响正确性的运行状态必须外部化。
- 本地内存只能保存可丢弃、可重建、不会影响跨 Pod 语义的缓存。
- 第一阶段 `web`、`config`、`runtime`、`northbound` 不能依赖 sticky session 才正确；未来其它应用服务扩容时也遵循同一原则。
- Sticky session 可以保留为临时兼容策略，但不是设计前提。

### 3.2 应用层多副本边界

第一阶段允许多副本：

- `nexent-web`
- `nexent-config`
- `nexent-runtime`
- `nexent-northbound`

第一阶段保持单副本：

- `nexent-mcp`
- `nexent-data-process`
- `nexent-postgresql`
- `nexent-redis`
- `nexent-elasticsearch`
- `nexent-minio`
- `nexent-supabase-db`
- `nexent-openssh`

`nexent-web` 和 `nexent-config` 纳入第一阶段，但只做无状态化确认、启动/迁移并发保护、代理超时和 Helm 手工多副本配置。`nexent-mcp` 的动态工具一致性、`nexent-data-process` 的 scheduler/worker/Ray 拆分均放到后续阶段。

## 4. 详细修改点

### 4.1 Helm values 与模板

#### 4.1.1 新增应用服务手工多副本字段

第一阶段不启用 autoscaling/HPA，也不引入 PDB、topology spread、affinity、nodeSelector、tolerations 等调度增强项。`web`、`config`、`runtime` 和 `northbound` chart 只保留最小手工多副本配置：

- `replicaCount`
- `strategy`

涉及 chart：

- `deploy/k8s/helm/nexent/charts/nexent-web`
- `deploy/k8s/helm/nexent/charts/nexent-config`
- `deploy/k8s/helm/nexent/charts/nexent-runtime`
- `deploy/k8s/helm/nexent/charts/nexent-northbound`

修改模板：

- `templates/deployment.yaml`

最小配置示例：

```yaml
replicaCount: 2

strategy:
  type: RollingUpdate
  rollingUpdate:
    maxSurge: 1
    maxUnavailable: 0
```

验收要求：

- 默认仍然 `replicaCount: 1`，避免破坏现有安装。
- 生产示例 values 中仅 `nexent-web`、`nexent-config`、`nexent-runtime` 和 `nexent-northbound` 配置 `replicaCount: 2`。
- `web`、`config`、`runtime` 和 `northbound` Deployment 渲染出上述 RollingUpdate 策略。
- 第一阶段不渲染 `HorizontalPodAutoscaler`，也不新增 `autoscaling.*` values；自动扩缩容作为二期能力单独设计。
- 第一阶段不新增 PDB、topology spread、affinity、nodeSelector、tolerations；这些调度增强项如有需要放到后续生产增强阶段。

#### 4.1.2 共享存储生产模式

确认并补充 `global.sharedStorage.mode` 的生产使用说明：

- `local`: 当前默认，单节点/开发使用，保留 `hostPath`。
- `dynamic`: 使用 StorageClass 动态创建 PVC。
- `existing`: 使用用户提供的 PVC。

第一阶段要求：

- `config`、`runtime` 和 `northbound` 多副本生产示例必须使用 `existing` 或 `dynamic`。
- 如果 `config`、`runtime` 或 `northbound` 副本数大于 1 且共享 PVC access mode 不是 `ReadWriteMany`，安装文档必须给出明显 warning；Helm 模板阻断可作为后续增强。
- `local + ReadWriteOnce` 文档标注为不支持跨节点多副本；如果只在单节点开发环境验证，可以保留当前默认值。

需要修改：

- `deploy/k8s/helm/nexent/values.yaml`
- `deploy/k8s/helm/nexent/README.md`
- `doc/docs/zh/quick-start/kubernetes-installation.md`

#### 4.1.3 内置状态组件防误扩

第一阶段不改造以下状态组件的多副本能力：

- `nexent-postgresql`
- `nexent-redis`
- `nexent-elasticsearch`
- `nexent-minio`
- `nexent-supabase-db`

要求：

- values 和安装文档中标注这些组件不应通过 `replicaCount > 1` 扩容。
- 第一阶段不新增 StatefulSet、Sentinel、Operator 或集群模板。
- 生产 HA 推荐外接托管服务或后续阶段专门改造。

### 4.2 Runtime 分布式运行状态

#### 4.2.1 新增 Redis 运行状态服务

新增模块：

- `backend/services/runtime_state_service.py`

职责：

- 管理 agent run owner。
- 管理取消信号。
- 管理 SSE event buffer。
- 管理 channel completion 状态。
- 提供统一 TTL 清理。

建议 Redis key：

| Key | 类型 | 用途 | TTL |
| --- | --- | --- | --- |
| `runtime:run:{user_id}:{conversation_id}` | hash | run owner、status、message_id、started_at、updated_at | 运行中 24h；结束后 5min |
| `runtime:cancel:{user_id}:{conversation_id}` | string | stop 请求设置的取消信号 | 运行中 24h；结束后 5min |
| `runtime:stream:{user_id}:{conversation_id}` | stream 或 list | SSE 事件历史 | 运行中 24h；结束后 5min |
| `runtime:stream:done:{user_id}:{conversation_id}` | hash | 完成状态、错误信息、最后 event id | 结束后 5min |

Redis Stream 方案：

- `XADD runtime:stream:{key} * event <payload>`
- `XRANGE` 用于恢复历史。
- `XTRIM` 或 TTL 控制内存。
- 每个 SSE chunk 保存原始 `data: ...\n\n` 或结构化 JSON。

List 方案也可行：

- `RPUSH` 保存事件。
- `LRANGE` 恢复事件。
- 使用递增 index 作为 event id。

推荐 Redis Stream，因为天然有 event id，适合 `Last-Event-ID`。

#### 4.2.2 改造 StreamingChannelManager

现状：

- `backend/services/streaming_channel.py` 中 `_channels` 是进程内 dict。

改造：

- 保留 `StreamingChannel` API 形状，内部 publish 同时写 Redis。
- 本地 subscriber 仍可通过 asyncio event 低延迟接收当前 Pod 的事件。
- 跨 Pod resume 不依赖本地 channel，而是从 Redis 读取历史事件。
- 本地 channel 只作为实时 fan-out 优化，不作为事实来源。

新增接口：

- `append_stream_event(user_id, conversation_id, chunk) -> event_id`
- `read_stream_events(user_id, conversation_id, after_event_id=None) -> list`
- `mark_stream_completed(user_id, conversation_id, status, error=None)`
- `get_stream_status(user_id, conversation_id)`

兼容策略：

- 现有 `resume=true` 继续支持。
- 可新增可选 header `Last-Event-ID`，没有 header 时按当前 `resume_from_unit_index` 逻辑兜底。
- 如果 Redis 缓冲过期，则退化为 DB 已持久化消息恢复，并返回已完成/过期状态。

#### 4.2.3 改造 AgentRunManager

现状：

- `agent_runs` 和 `stop_event` 在本地内存。

改造：

- 注册 run 时写入 Redis：
  - `owner_pod`: Pod 名，可从环境变量 `HOSTNAME` 获取。
  - `status`: `running`
  - `message_id`
  - `started_at`
  - `updated_at`
- agent 主循环周期性检查 Redis cancel key。
- stop 请求只需要设置 Redis cancel key，不要求打到 owner Pod。
- owner Pod 检测到 cancel 后触发本地 `stop_event`。

代码修改：

- `backend/agents/agent_run_manager.py`
- `backend/services/agent_service.py`

关键点：

- 本地 `agent_runs` 仍保留，用于 owner Pod 快速停止。
- `stop_agent_run` 先尝试本地停止，再写 Redis cancel key。
- agent run finally 中删除或标记 Redis run 状态。
- Pod 异常退出时，run key 依赖 TTL 自动过期；消息状态由现有 DB 持久化兜底。

#### 4.2.4 改造 PreprocessManager

现状：

- 预处理任务只在本地保存 task id 和 asyncio task。

改造：

- 对需要跨 Pod 停止的预处理任务写 Redis cancel key。
- 预处理任务执行过程中定期检查 cancel key。
- `stop_preprocess_tasks` 写 Redis cancel key，并尝试本地取消。

涉及代码：

- `backend/agents/preprocess_manager.py`
- 使用 preprocess manager 的调用点。

验收：

- 在 Pod A 发起包含预处理的 agent run。
- `/agent/stop` 打到 Pod B。
- Pod A 中预处理和 agent run 均停止。

#### 4.2.5 Conversation ContextManager 策略

现状：

- `AgentRunManager._conversation_context_managers` 保存 conversation 级 `ContextManager`。

第一阶段策略：

- 将它定义为本地优化缓存。
- 如果当前 Pod 没有缓存，则从 DB conversation history 重建。
- 不要求跨 Pod 共享 ContextManager 内部压缩缓存。

风险：

- 多 Pod 下同一 conversation 的连续多轮可能落到不同 Pod，压缩缓存命中率下降。
- 如果有代码依赖 ContextManager 保存未持久化信息，需要在改造前确认并移除该依赖。

### 4.3 后续阶段：MCP 多副本一致性

本节不属于第一阶段交付。第一阶段 `nexent-mcp` 保持单副本；下面内容仅作为后续阶段设计预留。

#### 4.3.1 新增 MCP 启动初始化

现状：

- 动态 OpenAPI MCP 服务只在 refresh 请求到达当前 Pod 时加载。

改造：

- `nexent-mcp` 启动时读取 DB 中 enabled OpenAPI MCP 服务并注册。
- 启动初始化失败时应记录错误并继续启动 local MCP，避免整个服务不可用。

涉及代码：

- `backend/mcp_service.py`
- `database/outer_api_tool_db.py`

新增函数：

- `load_all_openapi_services_on_startup()`
- 或复用 `refresh_openapi_services_by_tenant`，但需要支持所有 tenant。

如果数据库当前只提供按 tenant 查询，需要新增 DB 查询函数：

- `query_all_available_openapi_services()`

#### 4.3.2 Redis Pub/Sub 广播刷新

新增模块：

- `backend/services/mcp_refresh_bus.py`

Redis channel：

- `mcp:refresh`

消息结构：

```json
{
  "event": "refresh_all",
  "tenant_id": "xxx",
  "service_name": null,
  "source_pod": "nexent-config-xxx",
  "timestamp": 1234567890
}
```

事件类型：

- `refresh_all`: 刷新某 tenant 的全部 OpenAPI MCP 服务。
- `refresh_one`: 刷新某 tenant 的某个 service。
- `delete_one`: 删除某 tenant 的某个 service。

改造流程：

1. config 服务写 DB 成功。
2. config 服务发布 Redis Pub/Sub 消息。
3. 所有 mcp Pod 后台订阅。
4. 每个 mcp Pod 调用本地 refresh 函数更新自己的 FastMCP mount。

涉及代码：

- `backend/services/tool_configuration_service.py`
- `backend/apps/tool_config_app.py`
- `backend/mcp_service.py`

降级：

- 如果 Redis Pub/Sub 发布失败，保留当前直接调用 `MCP_MANAGEMENT_API` 的逻辑作为 best effort。
- 提供管理接口用于手动触发所有 Pod 刷新，或让 mcp Pod 周期性自检 DB 版本。

#### 4.3.3 MCP 配置版本号

为避免 Pub/Sub 消息丢失导致长期不一致，建议增加版本检查。

方案：

- 在 DB 或 Redis 保存 `mcp:version:{tenant_id}`。
- 每次 OpenAPI MCP 配置变更后 `INCR`。
- 每个 MCP Pod 维护本地 `loaded_version`。
- 后台每 30-60 秒检查一次版本，发现版本变化就刷新。

后续阶段可选：

- 如果要压缩工作量，可以先只做 Pub/Sub。
- 生产可靠性建议同时做版本检查。

### 4.4 Northbound 幂等与限流

#### 4.4.1 幂等键外部化

现状：

- `_IDEMPOTENCY_RUNNING` 是本地 dict。

改造：

- 使用 Redis `SET key value NX EX ttl`。
- key 格式：`northbound:idempotency:{tenant_id}:{idempotency_key}`。
- value 保存 request id、pod name、created_at。
- 请求结束后延迟释放，保持当前 3 秒窗口语义。

涉及代码：

- `backend/services/northbound_service.py`

异常策略：

- Redis 不可用时，为了避免重复执行，建议返回 503 或 429，而不是回退到本地 dict。
- 如果业务更偏可用性，可以通过配置 `NORTHBOUND_IDEMPOTENCY_FAIL_OPEN=true` 允许降级。

#### 4.4.2 限流外部化

现状：

- `_RATE_STATE` 是本地 dict。

改造：

- 使用 Redis 计数器：
  - `INCR northbound:rate:{tenant_id}:{minute_bucket}`
  - 第一次设置 `EXPIRE 120`
- 超过 `_RATE_LIMIT_PER_MINUTE` 返回 `LimitExceededError`。

新增配置：

- `NORTHBOUND_RATE_LIMIT_PER_MINUTE`
- `NORTHBOUND_RATE_LIMIT_ENABLED`

注意：

- 后续如果需要更平滑限流，可改为 token bucket 或 sliding window。
- 第一阶段保持当前 minute bucket 语义。

### 4.5 后续阶段：Auto Summary Scheduler 分布式锁

本节不属于第一阶段交付。第一阶段 `nexent-data-process` 保持单副本，不启用多个 scheduler 实例。

现状：

- `_in_flight` 只在单进程内避免重复。

改造：

- 每个知识库执行前抢 Redis 锁：
  - `SET auto_summary:lock:{index_name} pod_name NX EX lock_ttl`
- 抢锁成功才执行。
- 执行完成后校验 value 是当前 pod 再释放。

涉及代码：

- `backend/services/auto_summary_scheduler.py`

锁 TTL：

- 默认 2 小时，或根据最大摘要任务时间配置。
- 新增配置 `AUTO_SUMMARY_LOCK_TTL_SECONDS`。

调度模式：

- 后续阶段可以允许多个 Pod 都启动 scheduler，但通过分布式锁保证单个 KB 不重复处理。
- 更推荐在 Helm 中让 scheduler 拆成独立 deployment，再结合单副本、leader election 或分布式锁运行。

### 4.6 后续阶段：Data Process 拆分预留

第一阶段不做完整 data-process 横扩，但文档和代码应避免阻塞后续拆分。

二期目标形态：

- `nexent-data-process-api`: 只提供 HTTP API。
- `nexent-data-process-worker`: Celery worker，可按队列和资源扩容。
- `nexent-ray-head`: Ray head，StatefulSet 或独立 Deployment。
- `nexent-ray-worker`: Ray worker，支持手工副本数或 KubeRay；HPA 不进入第一阶段。
- `nexent-flower`: 可选单副本监控。
- `nexent-auto-summary-scheduler`: 单副本或 leader election。

第一阶段需要避免：

- 在应用层多副本设计中承诺 `nexent-data-process.replicaCount > 1` 可用。
- 把 Flower/Ray dashboard 多副本暴露成生产入口。

### 4.7 Web 与 Config 多副本

#### 4.7.1 Web 代理层

现状：

- `frontend/server.js` 将 `/api/agent/run`、`/api/agent/stop`、`/api/conversation/`、`/api/share/`、`/api/memory/`、`/api/file/storage` 等代理到 runtime。
- `/api/voice/` WebSocket upgrade 代理到 runtime。
- 其他 `/api` 代理到 config。
- `nexent-web` 不挂载共享 PVC，主要状态来自浏览器 cookie、后端服务和对象存储。

第一阶段改造：

- 为 `nexent-web` Deployment 增加最小 RollingUpdate 策略。
- 确认 Node proxy 对 SSE 不 buffer。
- 增加代理超时配置，避免长时间 agent run 被 web 层中断。
- Web Pod 重启或滚动更新导致 SSE 断开时，前端应能重新连接；恢复语义由 runtime Redis stream/DB 兜底。
- Web 不保存关键服务端状态，不要求 sticky session。

建议配置：

- `PROXY_TIMEOUT_MS`
- `PROXY_WS_TIMEOUT_MS`
- `SSE_PROXY_TIMEOUT_MS`

Ingress：

- 不要求 sticky session。
- 需要为 SSE/WebSocket 配置合适 timeout：
  - nginx: `proxy-read-timeout`, `proxy-send-timeout`
  - 其他 ingress controller 按实际配置。

#### 4.7.2 Config 服务

现状：

- `nexent-config` 挂载 `/mnt/nexent` 和 `/mnt/nexent-data/skills`。
- Deployment 中 `NEXENT_SQL_STARTUP_MODE` 当前为 `migrate`，多副本启动时可能多个 Pod 同时执行数据库迁移。
- config 服务写入 Postgres、MinIO 或共享 PVC，并通过 `MCP_MANAGEMENT_API` 通知 `nexent-mcp` 刷新工具。
- 第一阶段 `nexent-mcp` 仍是单副本，因此 config 多副本不会引入 MCP 多 Pod 工具列表不一致问题。

第一阶段改造：

- 为 `nexent-config` Deployment 增加最小 RollingUpdate 策略。
- config Pod 不保存影响正确性的进程内状态；如发现本地缓存，只能作为可重建缓存。
- 数据库迁移必须避免多 Pod 并发执行。推荐方案是把迁移拆到 Helm hook Job 或独立 migration Job，config Deployment 启动时不再执行迁移。
- 如果短期不拆 migration Job，则需要在迁移入口加数据库级互斥锁，例如 Postgres advisory lock，保证同一时间只有一个 Pod 执行迁移，其它 Pod 等待或跳过。
- config 多副本写共享文件时要求 `nexent-workspace` 和 `nexent-skills` 使用 RWX 或对象存储化路径；`local + ReadWriteOnce` 不支持跨节点生产多副本。
- 保持现有 `MCP_MANAGEMENT_API` 调用方式，因为第一阶段 mcp 是单副本。MCP 多副本广播刷新放到后续阶段。

验收：

- 两个 config Pod 同时启动时，数据库迁移不会并发冲突。
- config API 的创建、更新、删除、查询操作在多 Pod 下读取一致。
- OpenAPI MCP 配置变更仍能刷新单副本 `nexent-mcp`。
- 滚动更新期间 config 普通 API 可用，不能因为某个 Pod 正在迁移导致整体不可用。

### 4.8 配置与环境变量

后端新增环境变量必须集中到 `backend/consts/const.py`。Web 代理层环境变量归属前端 Helm chart，不放入后端 `const.py`。

建议新增：

- `RUNTIME_STATE_REDIS_URL`
  - 默认复用 `REDIS_URL`
- `RUNTIME_STREAM_TTL_SECONDS`
- `RUNTIME_RUN_TTL_SECONDS`
- `RUNTIME_CANCEL_TTL_SECONDS`
- `RUNTIME_COMPLETED_TTL_SECONDS`
- `NORTHBOUND_IDEMPOTENCY_TTL_SECONDS`
- `NORTHBOUND_RATE_LIMIT_ENABLED`
- `NORTHBOUND_RATE_LIMIT_PER_MINUTE`
- `MULTI_REPLICA_MODE`

Web chart 建议新增或确认：

- `PROXY_TIMEOUT_MS`
- `PROXY_WS_TIMEOUT_MS`
- `SSE_PROXY_TIMEOUT_MS`

Config 需要确认：

- `NEXENT_SQL_STARTUP_MODE`
  - 如果迁移拆成独立 Job，config Deployment 中应关闭启动迁移。
  - 如果继续在 Pod 启动时迁移，迁移逻辑必须加数据库级互斥锁。

Helm ConfigMap 需要同步：

- `deploy/k8s/helm/nexent/charts/nexent-common/templates/configmap.yaml`
- `deploy/k8s/helm/nexent/charts/nexent-common/values.yaml`
- `deploy/k8s/helm/nexent/generated-*.yaml` 生成逻辑如有涉及也需更新。

### 4.9 性能影响与优化边界

第一阶段不是零成本扩容。`runtime` 和 `northbound` 会引入 Redis 读写，`web` 和 `config` 会增加代理层、数据库连接数和启动并发控制压力。

Web 主要影响：

- 多个 Web Pod 会增加到 runtime/config Service 的并发代理连接数。
- SSE/WebSocket 长连接会占用 Web Pod 连接和内存资源。
- Web Pod 滚动更新会断开该 Pod 上的长连接，依赖前端重连和 runtime resume 保证体验。

Config 主要影响：

- 多个 config Pod 会增加 Postgres、MinIO 和共享存储的并发访问。
- 如果启动迁移使用数据库锁，Pod 启动时间可能变长。
- 如果数据库连接池按 Pod 固定大小配置，总连接数会随副本数增长，需要校验 Postgres `max_connections`。

Runtime 主要影响：

- SSE 每个 chunk 需要追加到 Redis stream/list，Redis QPS 会随 agent 输出 token/chunk 数增加。
- resume 需要从 Redis 读取历史事件，历史越长读取越多。
- stop/cancel 需要 owner Pod 周期性检查 Redis cancel key，检查间隔越短停止越快，但 Redis 读压力越高。
- 本地 channel 仍保留为同 Pod 实时 fan-out 优化，正常不断线场景不应全部依赖 Redis 轮询。

Northbound 主要影响：

- 每个带 `Idempotency-Key` 的请求至少增加一次 Redis `SET NX EX`。
- 每个受限流控制的请求至少增加一次 Redis `INCR/EXPIRE`。
- Redis 不可用时应优先 fail closed，避免重复执行和限流失效；这会牺牲部分可用性。

优化要求：

- SSE buffer 必须设置 TTL 和最大长度，避免长对话撑爆 Redis 内存。
- agent run 完成、失败或停止后，主动把 runtime Redis key 的 TTL 缩短到 `RUNTIME_COMPLETED_TTL_SECONDS`。
- cancel 检查使用合理间隔，例如 0.5-2 秒，不做高频忙轮询。
- Northbound Redis key 必须设置 TTL，避免幂等键和限流桶长期残留。
- Config 数据库连接池要按副本数重新核算，避免副本数翻倍后压满 Postgres。
- Web SSE/WebSocket timeout 要大于典型 agent run 时间，避免代理层提前断开。
- 压测必须覆盖 Redis QPS、内存占用、P95/P99 延迟和滚动更新期间错误率。

## 5. 兼容性与迁移策略

### 5.1 默认行为

- 默认单副本行为保持不变。
- 不开启 `MULTI_REPLICA_MODE` 时，允许继续使用本地内存实现；但建议 runtime/northbound 改造后统一走 Redis，减少双路径。
- 第一阶段 Helm 不引入 HPA/autoscaling，所有副本数通过 `replicaCount` 手工控制。

### 5.2 上线步骤

推荐顺序：

1. 发布 web/config Helm 策略、config 迁移并发保护、runtime/northbound Redis 状态改造代码，但 `replicaCount` 仍保持 1。
2. 单副本下验证 Web 代理、config CRUD、config migration、agent run、SSE resume、stop、preprocess cancel、northbound 幂等、northbound 限流。
3. 确认生产环境 Redis 可用，且 config/runtime/northbound 使用的共享存储不是跨节点 `local + ReadWriteOnce`。
4. 开启 `nexent-web` 多副本，设置 `replicaCount: 2` 和 RollingUpdate 策略，验证登录、页面访问、SSE/WebSocket 代理。
5. 开启 `nexent-config` 多副本，设置 `replicaCount: 2` 和 RollingUpdate 策略，验证迁移互斥、配置写入、单副本 MCP refresh。
6. 开启 `nexent-northbound` 多副本，设置 `replicaCount: 2` 和 RollingUpdate 策略。
7. 开启 `nexent-runtime` 多副本，设置 `replicaCount: 2` 和 RollingUpdate 策略。
8. 进行滚动更新、Pod 删除、断连重连和跨 Pod stop 故障演练。

### 5.3 回滚策略

- Helm 保留 `replicaCount: 1` 快速回滚方式。
- Redis 中新增运行状态均设置 TTL，不需要数据库迁移清理。
- Web 如果代理层出现长连接异常，可以先回滚为单副本，不影响后端状态。
- Config 如果迁移锁或共享存储写入异常，可以先回滚为单副本，并暂停新的配置写入操作。
- Runtime 如果 Redis 状态异常，可以停止多副本，保留 DB 中已持久化消息。
- Northbound 如果 Redis 幂等或限流异常，可以先回滚为单副本，避免重复执行或限流放大。

## 6. 工作量评估

第一阶段包含 `nexent-web`、`nexent-config`、`nexent-runtime` 和 `nexent-northbound` 多副本，预估 20-31 人日。

| 模块 | 工作内容 | 预估 |
| --- | --- | --- |
| Helm 多副本模板 | web/config/runtime/northbound 手工 replicaCount、RollingUpdate、生产存储限制说明 | 2-3 人日 |
| Web 多副本 | 代理超时、SSE/WebSocket 不 buffer、滚动更新断连恢复验证 | 1-2 人日 |
| Config 多副本 | 启动迁移互斥、共享存储写入确认、MCP 单副本刷新兼容 | 3-5 人日 |
| Runtime 分布式状态 | Redis stream、run owner、cancel、resume、stop、TTL | 8-12 人日 |
| Northbound 分布式控制 | Redis 幂等、限流、异常降级策略 | 2-3 人日 |
| 测试与文档 | 单测、集成测试、k8s 验证、压测、升级文档 | 4-6 人日 |

第二阶段额外工作量：

| 模块 | 工作内容 | 预估 |
| --- | --- | --- |
| MCP 一致性 | 启动加载、Pub/Sub 广播、版本检查、管理接口兼容 | 4-6 人日 |
| Auto Summary Scheduler | scheduler 独立部署、分布式锁或 leader election | 2-4 人日 |
| Data Process 横向扩展 | API/worker/Ray/Flower/scheduler 拆分 | 15-30 人日 |
| 内置状态组件 HA | Postgres、Redis、ES、MinIO、Supabase DB 集群化 | 20-40 人日 |
| 生产观测与容量模型 | 指标、告警、压测模型、容量建议 | 5-10 人日 |

## 7. 测试计划

### 7.1 单元测试

新增或修改测试：

- `test/frontend` 或前端现有代理测试：覆盖 SSE/WebSocket proxy timeout 和不 buffer 行为。
- `test/backend/apps/test_config_app.py`
- `test/backend/services/test_tool_configuration_service.py`
- `test/backend/services/test_runtime_state_service.py`
- `test/backend/services/test_streaming_channel_distributed.py`
- `test/backend/agents/test_agent_run_manager.py`
- `test/backend/services/test_northbound_service.py`

重点场景：

- Redis 写入失败、读取失败、TTL 过期。
- Web 代理长连接不被提前关闭。
- config 启动迁移并发时只有一个执行者。
- config API 多 Pod 下读写 DB 后结果一致。
- SSE 事件追加和按 event id 恢复。
- cancel key 被设置后 agent loop 能退出。
- 幂等 key 并发抢占只有一个成功。
- 租户级限流在多 Pod 下仍按全局额度生效。

### 7.2 集成测试

本地或 CI 中用 fake Redis/miniredis 或真实 Redis：

- Web 代理到 runtime/config 的 API 正常转发。
- Web 代理 SSE 断开后可重连。
- config 多实例同时启动不会并发执行迁移。
- config 写入 OpenAPI MCP 配置后仍能刷新单副本 mcp。
- agent run 正常完成。
- agent run 中断后 resume。
- stop 请求不在 owner 进程内也能停止。
- northbound 同一 idempotency key 并发请求只执行一次。
- northbound 限流请求打到不同 Pod 时仍按同一租户额度计数。

### 7.3 Kubernetes 验证

部署矩阵：

| 服务 | 副本数 |
| --- | --- |
| nexent-web | 2 |
| nexent-config | 2 |
| nexent-runtime | 2-3 |
| nexent-northbound | 2 |
| nexent-mcp | 1 |
| nexent-data-process | 1 |
| 状态组件 | 1 或外部托管 |

验证场景：

1. 两个 web Pod 下登录、页面访问、普通 API、SSE 和 WebSocket 代理正常。
2. 删除一个 web Pod，确认浏览器重连后 agent 流式对话可恢复或得到明确完成状态。
3. 两个 config Pod 同时启动或滚动更新，确认数据库迁移不并发冲突。
4. config API 创建、更新、删除智能体配置、模型配置、工具配置后，另一个 Pod 立即读取一致结果。
5. config 写入 OpenAPI MCP 配置后，确认单副本 `nexent-mcp` 刷新成功。
6. 发起长 agent SSE，删除处理该请求的 runtime Pod，确认前端能通过 DB/Redis 得到明确恢复结果。
7. 发起长 agent SSE，断开浏览器连接，再重新连接到不同 runtime Pod，确认继续接收或正确提示已完成。
8. 发起 agent run 后，将 stop 请求强制打到另一个 runtime Pod，确认运行停止。
9. northbound 同一 idempotency key 并发请求打到不同 Pod，确认只有一个执行。
10. northbound 同一租户请求打到不同 Pod，确认限流总额度不随副本数放大。
11. 手工调大或调小 web/config/runtime/northbound `replicaCount` 后，Web 登录、智能体配置、知识库查询、文件预览仍可用。

### 7.4 压测与容量

基础压测指标：

- agent run 并发数。
- SSE event 写 Redis 的 QPS 和内存占用。
- Redis stream/list TTL 清理效果。
- web Pod 长连接数、代理延迟、断线重连成功率。
- config Pod DB 连接数、迁移锁等待时间、配置写入延迟。
- runtime Pod CPU/内存。
- northbound 限流准确性。
- northbound Redis 操作延迟和错误率。

建议验收门槛：

- stop 请求跨 Pod 生效小于 2 秒。
- SSE resume 在 Redis 状态未过期时成功率 100%。
- web 滚动更新期间长连接可重连，普通页面/API 可用。
- config 滚动更新期间普通 API 可用，迁移不会并发失败。
- northbound 幂等键并发抢占成功率符合预期，重复执行次数为 0。
- 滚动更新期间普通 API 错误率不超过预设阈值。

## 8. 风险与待确认项

### 8.1 Redis 成为关键依赖

runtime/northbound 多副本后，Redis 不再只是 Celery broker/cache，也承载运行控制状态。

需要确认：

- 生产环境是否使用托管 Redis 或 Redis HA。
- Redis 持久化和内存淘汰策略。
- Redis 不可用时 runtime/northbound 的失败策略。

建议：

- 第一阶段文档要求生产多副本环境必须提供可靠 Redis。
- Redis 单实例只适合开发或非关键部署。
- Redis 自身多副本不在第一阶段 Helm 内置改造范围内。生产推荐三种方式：
  - 托管 Redis/云 Redis，应用侧仍使用单个稳定连接地址。
  - Redis Sentinel，一主多从加自动故障转移，应用侧需要确认 Redis client 支持 Sentinel 地址。
  - Redis Cluster，用于更大容量和分片场景，应用侧需要确认 key 设计、client 和部署网络均支持 cluster mode。
- 如果继续使用 chart 内置单实例 Redis，则只能视为 runtime/northbound 多副本的功能验证环境，不能视为高可用生产形态。

### 8.2 技能目录共享语义

技能相关代码仍会读写 `SKILLS_PATH`。

需要确认：

- 生产是否提供 RWX PVC。
- 是否计划将技能文件完全迁移到 MinIO/DB。

第一阶段建议：

- config/runtime/northbound 多副本要求 `nexent-skills` 使用 RWX。
- 后续单独设计“技能文件对象存储化”。

### 8.3 Config 启动迁移并发

`nexent-config` 当前通过 `NEXENT_SQL_STARTUP_MODE=migrate` 在 Pod 启动时执行迁移。多副本后，如果两个 Pod 同时启动或滚动更新，可能同时执行 SQL migration。

第一阶段建议：

- 优先把迁移拆为独立 Job，在 config Deployment 启动前完成。
- 如果继续保留 Pod 启动迁移，必须使用 Postgres advisory lock 或等效数据库锁。
- 迁移失败时 config Pod 不应进入 Ready，避免服务接入到不完整 schema。
- 滚动更新时必须验证两个 config Pod 不会因为等待迁移锁而全部不可用。

### 8.4 Agent 运行恢复语义

Pod 被删除时，正在运行的 agent 无法真正从中间继续推理，只能：

- 从 DB 返回已持久化部分。
- 标记为 failed/stopped。
- 由用户重新发起。

第一阶段目标是“连接恢复和停止控制跨 Pod 可用”，不是“Pod 崩溃后 agent 计算继续执行”。

### 8.5 Data Process 完整横扩

当前 data-process 结构把 API、worker、Ray、Flower、scheduler 放在同一进程树中。

第一阶段不承诺：

- 多个 data-process Pod 同时启动 Ray 后能正确协作。
- Flower/Ray dashboard 多副本访问一致。
- Celery worker 和 Ray actor 池按资源自动弹性扩缩。

这些应进入第二阶段。

## 9. 分阶段实施计划

### Milestone 1: 基础设施与配置准备

内容：

- 为 `nexent-web`、`nexent-config`、`nexent-runtime` 和 `nexent-northbound` 新增 Helm 最小多副本字段。
- 为 web/config/runtime/northbound Deployment 增加 RollingUpdate 策略配置。
- 新增四个服务的多副本文档和 values 示例。
- 明确内置状态组件、mcp、data-process 第一阶段保持单副本。
- 新增 `backend/services/runtime_state_service.py` 基础封装。

验收：

- 单副本行为不变。
- web/config/runtime/northbound 可渲染多副本 manifests。
- 生产示例只包含这四个服务的 `replicaCount: 2` 和 RollingUpdate 策略。

预估：3-4 人日。

### Milestone 2: Web 与 Config 多副本

内容：

- Web proxy SSE/WebSocket timeout 和不 buffer 确认。
- Web 滚动更新断线重连验证。
- Config 启动迁移拆 Job 或加数据库锁。
- Config 多 Pod 下配置读写一致性验证。
- Config 到单副本 MCP 的 refresh 兼容验证。

验收：

- web 2 副本下页面、普通 API、SSE、WebSocket 正常。
- config 2 副本下迁移不并发冲突，配置读写一致。

预估：4-7 人日。

### Milestone 3: Runtime 多副本

内容：

- SSE event 写 Redis。
- resume 从 Redis/DB 恢复。
- agent run owner 和 cancel key 外部化。
- stop 跨 Pod 生效。
- preprocess cancel 外部化。

验收：

- runtime 2-3 副本下，run/resume/stop 通过集成测试。

预估：8-12 人日。

### Milestone 4: Northbound 多副本

内容：

- northbound Redis 幂等和限流。
- Redis 不可用时的失败策略。
- 多 Pod 并发幂等和全局限流测试。

验收：

- northbound 2 副本下幂等和限流准确。

预估：2-3 人日。

### Milestone 5: Kubernetes 验证、压测与文档

内容：

- web/config/runtime/northbound k8s 多副本验证。
- 压测和容量记录。
- 更新安装/升级文档。

验收：

- web/config/runtime/northbound 多副本部署完成全链路 smoke test。
- 滚动更新期间核心功能可用。

预估：5-8 人日。

## 10. 最终交付物

代码交付：

- Web proxy timeout 和长连接兼容配置。
- Config migration 并发保护或独立 migration Job。
- Redis 运行状态服务。
- Runtime SSE/resume/stop 分布式化。
- Northbound 分布式幂等与限流。
- Web/config/runtime/northbound Helm 手工多副本 values 示例和 RollingUpdate 策略配置。

文档交付：

- Kubernetes 多副本设计文档。
- Kubernetes 安装文档中的 web/config/runtime/northbound 多副本限制说明。
- Kubernetes 升级文档中的 web/config/runtime/northbound 多副本升级步骤。
- 运维 runbook：如何扩容、回滚、排查 Redis 状态。

测试交付：

- 后端单元测试。
- Redis 集成测试。
- k8s 多副本 smoke test 清单。
- 压测结果和容量建议。
