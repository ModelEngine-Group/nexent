## Why

Nexent 平台已有基础 LLM 指标采集（OpenTelemetry + Prometheus），但缺乏模型级别的深度监控能力。当前无法区分可恢复错误与不可恢复故障、无法追踪各模型的成本消耗、无法在前端直观查看模型健康状态。随着接入模型数量和用户规模增长，运维人员需要快速定位模型故障、分析性能瓶颈、控制 Token 成本。

## What Changes

- 新增**故障率指标**（`llm_failure_count`），区分不可恢复故障（认证失败、模型不存在、响应异常）与可恢复错误（限流、超时），独立于现有 `llm_error_count`
- 扩展 SDK 监控系统，新增 `llm_request_total`、`llm_retry_count`、`llm_concurrent_requests`、`llm_cost_total`、`llm_quality_score` 等 8 个指标
- 新增 `model_monitoring_record_t` 和 `model_alert_record_t` 数据库表，持久化每次 LLM 调用的监控明细
- 在 `backend/utils/llm_utils.py` 调用链路中注入故障分类和监控数据采集逻辑
- 新增 7 个后端 API 端点（`/api/monitoring/*`），提供模型监控数据查询、趋势分析、故障详情和告警管理
- 扩展 Grafana 仪表板至 12 个面板，新增故障率对比、成本分析、告警统计等面板
- 将前端 `/monitoring` 页面从 "Coming Soon" 改造为完整监控仪表板，包含模型概览、对比表格、故障分析、告警管理等子页面
- 实现基于阈值的基础告警系统，支持慢请求、错误率、故障率、质量低分等 5 种告警类型

## Capabilities

### New Capabilities
- `model-metrics-collection`: 模型监控指标采集与故障分类——扩展 OpenTelemetry SDK 指标体系，在 LLM 调用链路中注入故障分类（可恢复错误 vs 不可恢复故障）和全维度指标采集
- `model-monitoring-storage`: 监控数据持久化——新建数据库表存储每次 LLM 调用的性能、成本、质量、故障明细，支持批量写入和按模型/租户/时间聚合查询
- `model-monitoring-api`: 监控数据 API——提供模型列表概览、单模型统计、趋势数据、故障详情、告警 CRUD 等 REST 端点
- `model-grafana-dashboard`: Grafana 仪表板——扩展现有仪表板配置，新增故障率对比、成本分析、告警统计等面板，修复 provisioning 自动加载
- `model-monitoring-frontend`: 前端监控页面——将 /monitoring 从 Coming Soon 改为完整监控仪表板，含概览卡片、模型对比表格、故障分析面板、告警管理
- `model-alert-system`: 基础告警系统——基于阈值的告警检测（慢请求/错误率/故障率/质量/重试率），记录告警到数据库，支持确认和解决

### Modified Capabilities
（无现有 spec 需要修改——这是全新功能模块）

## Impact

- **后端**: 修改 `sdk/nexent/monitor/monitoring.py`（新增 8 个指标）、`backend/utils/llm_utils.py`（注入监控采集）、`backend/consts/const.py`（新增配置项）；新增 `backend/database/model_monitoring_db.py`、`backend/database/alert_db.py`、`backend/services/alert_service.py`、`backend/consts/alert_const.py`、`backend/apps/monitoring.py`
- **数据库**: 新增 2 张表（`model_monitoring_record_t`、`model_alert_record_t`），`model_record_t` 新增 2 个单价字段；迁移文件 `docker/sql/v2.1.0_0410_add_model_monitoring_t.sql`
- **前端**: 修改 `frontend/services/api.ts`（新增端点）、`frontend/app/[locale]/monitoring/page.tsx`（从 Coming Soon 改为重定向）；新增约 15 个组件/服务/hook 文件和 1 个 TypeScript 类型定义文件
- **监控基础设施**: 修改 `docker/monitoring/grafana/dashboards/nexent-llm-performance.json`（新增 7 个面板）、`docker/monitoring/grafana/provisioning/dashboards/dashboards.yml`（修复自动加载）
- **依赖**: 前端新增 `recharts` 图表库；后端无新增依赖（OpenTelemetry 已为可选依赖）
- **API**: 新增 `/api/monitoring/*` 路由前缀下的 7 个端点，需通过现有认证中间件鉴权
