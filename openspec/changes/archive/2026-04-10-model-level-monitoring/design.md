## Context

Nexent 是一个零代码 AI Agent 生成平台，已具备基础的 LLM 监控基础设施：SDK 层通过 OpenTelemetry 采集 5 个指标（请求耗时、Token 生成速率、TTFT、总 Token 数、错误计数），Docker Compose 配置了 Prometheus + Grafana + Jaeger 服务栈。

**当前限制：**
- 错误计数不区分可恢复错误与不可恢复故障，运维无法快速定位严重问题
- 缺少请求总数计数器，无法计算错误率和故障率
- 无成本追踪能力，无法分析各模型的 Token 消费和费用
- Grafana 仪表板定义存在但 provisioning 未正确启用，仅 5 个基础面板
- 前端 `/monitoring` 页面显示 "Coming Soon"，无实际监控 UI
- 无告警机制，异常无法被自动检测和记录

**技术栈约束：**
- 后端：Python + FastAPI，SDK 使用 OpenTelemetry（可选依赖，缺失时优雅降级）
- 前端：Next.js 14 + React 18 + TypeScript + Tailwind CSS + Ant Design
- 数据库：PostgreSQL（Supabase 托管）
- 监控：OpenTelemetry → Prometheus → Grafana，Jaeger 追踪
- 数据库表命名遵循 `_t` 后缀约定，审计字段包含 `create_time`、`delete_flag`

## Goals / Non-Goals

**Goals:**
- 实现完整的模型级监控指标体系（16 个指标，含故障率）
- 区分可恢复错误与不可恢复故障，提供故障率独立指标
- 支持按模型/租户/Agent/时间的多维度深度分析
- 提供 Grafana 仪表板（12 个面板）和前端页面双展示
- 实现基于阈值的基础告警系统（5 种告警类型）
- 监控采集对 LLM 调用性能影响 < 2%

**Non-Goals:**
- LLM 自动质量评估（LLM-as-judge），仅使用用户反馈
- 邮件/Slack/Webhook 告警通知，仅记录到数据库
- 实时流式监控推送，使用轮询机制
- 自定义仪表板构建器，使用预定义面板
- 分布式追踪深度分析（Jaeger 已有基础能力）

## Decisions

### Decision 1: 故障分类策略

**选择**: 双层分类——`is_error`（可恢复）+ `is_failure`（不可恢复），使用 HTTP 状态码和错误消息模式匹配。

**理由**: 运维关注点不同——可恢复错误影响用户体验但可自愈（限流、超时），不可恢复故障意味着配置错误或服务中断（认证失败、模型不存在），后者需要立即人工介入。

**替代方案**:
- (A) 统一错误分类，通过标签区分——简单但无法设置不同告警阈值和严重级别
- (B) 仅统计故障率，不区分可恢复——丢失限流/超时等重要运维信息

### Decision 2: 监控数据双写——Prometheus + PostgreSQL

**选择**: OpenTelemetry 指标写入 Prometheus（时序聚合），同时单条记录写入 PostgreSQL（明细查询）。

**理由**: Prometheus 适合时序聚合和 Grafana 查询，但不适合明细检索和复杂过滤。PostgreSQL 支持按模型/租户/Agent 的多维度聚合，以及故障详情、告警记录的关系查询。两者互补。

**替代方案**:
- (A) 仅 Prometheus + PromQL——无法高效查询故障明细和告警记录
- (B) 仅 PostgreSQL——时序聚合性能差，Grafana 集成需额外开发

### Decision 3: 批量写入策略

**选择**: 后端维护内存缓冲区，按批量大小（100 条）或时间间隔（30 秒）触发批量 INSERT。

**理由**: 每次 LLM 调用同步写入数据库会增加 5-10ms 延迟，批量写入将影响降至 < 1ms。缓冲区大小和刷新间隔通过环境变量配置。

**风险**: 服务崩溃时丢失缓冲区中的未写入数据。可接受——Prometheus 侧已有指标，明细丢失不影响聚合统计。

### Decision 4: 前端图表库选择

**选择**: Recharts——轻量 React 原生图表库，支持 SSR，与 Next.js 兼容。

**理由**: 项目未使用图表库，Recharts 包体积小（~40KB gzip）、API 简洁、TypeScript 支持好。Ant Design Charts 过重，Chart.js 需要额外 React 封装。

### Decision 5: 成本计算方式

**选择**: 内置模型单价映射表 + 数据库 `model_record_t` 自定义单价覆盖。

**理由**: 主流模型价格公开且变化不频繁，内置映射覆盖常见模型。用户自定义模型通过数据库字段配置单价，查询时优先使用数据库值。每次监控记录同时保存当时的单价快照，避免历史数据因单价变动失真。

### Decision 6: 告警去重策略

**选择**: 同一模型同一告警类型在 5 分钟窗口内不重复触发。

**理由**: 避免告警风暴。告警去重基于 `alert_type + model_id + tenant_id + create_time > now() - 5min` 查询。

## Risks / Trade-offs

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 批量写入缓冲区在服务崩溃时丢失数据 | 低——丢失的明细不影响 Prometheus 聚合指标 | 刷新间隔控制在 30 秒内，最大丢失窗口有限 |
| `model_monitoring_record_t` 表在高流量下增长过快 | 中——磁盘占用和查询性能 | 90 天自动清理策略；`create_time` 分区索引 |
| 故障分类依赖错误消息模式匹配，新增错误类型可能漏分类 | 低——未分类错误归入 `unknown_failure` | 定期审查 `unknown_failure` 分布，补充匹配规则 |
| Grafana 仪表板 provisioning 路径配置不一致 | 低——可能导致仪表板不自动加载 | 实施时验证卷挂载路径与 YAML 配置一致 |
| 前端新增 recharts 依赖增加包体积 | 低——~40KB gzip | 按需加载，监控页面独立 chunk |
