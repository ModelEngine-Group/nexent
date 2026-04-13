## 1. 数据库迁移

- [ ] 1.1 创建数据库迁移文件 `docker/sql/v2.1.0_0410_add_model_monitoring_t.sql`，包含 `model_monitoring_record_t` 表 DDL（含 `is_failure`、`failure_type` 字段和 6 个索引）
- [ ] 1.2 在迁移文件中添加 `model_alert_record_t` 表 DDL（含 5 个索引）
- [ ] 1.3 在迁移文件中添加 `model_record_t` 表的 `input_price_per_1m` 和 `output_price_per_1m` 字段 ALTER 语句
- [ ] 1.4 执行迁移文件验证表创建成功（本地 PostgreSQL 或测试环境）

## 2. SDK 监控指标扩展

- [ ] 2.1 在 `sdk/nexent/monitor/monitoring.py` 的 `MonitoringManager._init_telemetry` 中新增 `llm_request_total` Counter（标签：model, tenant_id, agent_id, operation, status）
- [ ] 2.2 新增 `llm_failure_count` Counter（标签：model, failure_type, tenant_id, agent_id）
- [ ] 2.3 新增 `llm_retry_count` Counter（标签：model, retry_reason, tenant_id, agent_id）
- [ ] 2.4 新增 `llm_concurrent_requests` Gauge（标签：model, tenant_id），并实现 `increment_concurrent` / `decrement_concurrent` 方法
- [ ] 2.5 新增 `llm_cost_total` Counter（标签：model, tenant_id, agent_id）
- [ ] 2.6 新增 `calculate_cost(model_name, input_tokens, output_tokens)` 函数，包含默认单价映射 `MODEL_PRICING` 和数据库单价覆盖逻辑
- [ ] 2.7 在 `MonitoringManager` 中添加 `record_request` 方法，统一处理所有指标的一次性记录

## 3. 错误分类与数据采集注入

- [ ] 3.1 创建 `backend/consts/alert_const.py`，定义所有告警阈值环境变量（`HIGH_FAILURE_RATE_THRESHOLD` 默认 0.01 等）和错误模式匹配常量
- [ ] 3.2 实现错误分类函数 `classify_error(msg) -> (error_type, is_recoverable)` 和 `classify_failure(msg) -> (failure_type, is_failure)`
- [ ] 3.3 在 `backend/utils/llm_utils.py` 的 `call_llm_for_system_prompt` 函数中注入监控采集：请求开始记录并发+1和开始时间，第一个 chunk 记录 TTFT，流式结束记录 duration 和 tokens，异常记录错误/故障分类，出口记录并发-1 和成本
- [ ] 3.4 在 `backend/consts/const.py` 中添加 `ENABLE_MODEL_MONITORING` 和批量写入相关配置项
- [ ] 3.5 创建 `backend/database/model_monitoring_db.py`，实现 `insert_monitoring_record`、`batch_insert_monitoring_records`、`query_model_summary`、`query_model_list`、`query_model_trend`、`query_failure_details` 函数
- [ ] 3.6 实现批量写入缓冲区：内存缓冲区按 `MODEL_MONITORING_BATCH_SIZE`（100）或 `MODEL_MONITORING_FLUSH_INTERVAL_SECONDS`（30s）触发批量 INSERT

## 4. 告警系统

- [ ] 4.1 创建 `backend/database/alert_db.py`，实现 `insert_alert`、`query_alerts`、`update_alert_status`、`check_duplicate_alert` 函数
- [ ] 4.2 创建 `backend/services/alert_service.py`，实现 `check_failure_rate_alert`（检查最近 5 分钟故障率，≥10 请求时判断是否超阈值，5 分钟去重）
- [ ] 4.3 实现 `check_error_rate_alert`（同上逻辑，但检查可恢复错误率，severity 为 warning）
- [ ] 4.4 实现 `check_slow_request_alert`（单次请求耗时检查）和 `check_quality_alert`（最近 10 次评分平均值检查）
- [ ] 4.5 在 LLM 调用监控采集逻辑中集成告警检查调用

## 5. 监控 API 端点

- [ ] 5.1 创建 `frontend/types/monitoring.ts`，定义 `ModelMonitoringSummary`、`ModelPerformanceDetail`、`ErrorBreakdown`、`TrendPoint`、`FailureDetail`、`AlertRecord` TypeScript 类型
- [ ] 5.2 在 `frontend/services/api.ts` 中添加 `monitoring` 端点定义（modelList, modelSummary, modelTrend, failures, alertList, alertAcknowledge, alertResolve）
- [ ] 5.3 创建 `backend/apps/monitoring.py`，实现 `GET /api/monitoring/models`（分页、租户隔离、时间过滤）
- [ ] 5.4 实现 `GET /api/monitoring/models/{model_id}/summary`（performance + errors + tokens + cost + quality 聚合）
- [ ] 5.5 实现 `GET /api/monitoring/models/{model_id}/trend`（按 interval 聚合时间序列）
- [ ] 5.6 实现 `GET /api/monitoring/models/{model_id}/failures`（故障详情分页查询，含 API Key 脱敏）
- [ ] 5.7 实现 `GET /api/monitoring/alerts`（告警列表，支持 status/type/severity 过滤）
- [ ] 5.8 实现 `PUT /api/monitoring/alerts/{id}/acknowledge` 和 `PUT /api/monitoring/alerts/{id}/resolve`
- [ ] 5.9 在 `backend/apps/__init__.py` 中注册 `/api/monitoring` 路由前缀

## 6. Grafana 仪表板

- [ ] 6.1 修复 `docker/monitoring/grafana/provisioning/dashboards/dashboards.yml` provisioning 配置，确保 path 与卷挂载一致
- [ ] 6.2 在 `nexent-llm-performance.json` 中新增概览统计行：总请求数 Stat、错误率 Stat、故障率 Stat（PromQL: `sum(rate(llm_failure_count_total[5m])) / sum(rate(llm_request_total[5m])) * 100`）、今日成本 Stat
- [ ] 6.3 新增"错误率 vs 故障率对比"时序面板（两条曲线：可恢复错误率 + 不可恢复故障率）
- [ ] 6.4 新增"各模型故障率" Bar Gauge 面板（阈值颜色：<0.5% 绿、0.5-1% 黄、>1% 红）
- [ ] 6.5 新增成本趋势面板（按模型堆叠面积图）和成本占比饼图
- [ ] 6.6 新增告警统计面板（活跃告警 Stat + 最近告警 Table）
- [ ] 6.7 添加模板变量 `model_filter`、`tenant_filter`、`agent_filter`，所有面板查询使用变量过滤

## 7. 前端监控页面

- [ ] 7.1 创建 `frontend/services/monitoringService.ts`，封装所有监控 API 调用
- [ ] 7.2 修改 `frontend/app/[locale]/monitoring/page.tsx`，从 Coming Soon 改为重定向到 `/monitoring/models`
- [ ] 7.3 创建 `frontend/components/monitoring/MonitoringLayout.tsx` 和 `MonitoringToolbar.tsx`（时间范围选择、模型过滤、租户过滤、刷新按钮）
- [ ] 7.4 创建 `frontend/components/monitoring/OverviewCards.tsx`（5 个卡片：总请求数、错误率、故障率、平均耗时、今日成本，含 vs 昨日对比和阈值颜色）
- [ ] 7.5 创建 `frontend/components/monitoring/ModelComparisonTable.tsx`（含故障率列，绿/黄/红颜色标识，支持排序、筛选、分页）
- [ ] 7.6 创建 `frontend/app/[locale]/monitoring/models/page.tsx` 主页面，组装 Toolbar + Cards + Table + Charts
- [ ] 7.7 创建 `frontend/app/[locale]/monitoring/models/[modelId]/page.tsx` 模型详情页，含 Tab 切换（概览/趋势分析/故障分析/告警记录/成本明细）
- [ ] 7.8 创建 `frontend/components/monitoring/FailureDetailPanel.tsx`（故障率趋势图、故障类型分布饼图、故障详情列表）
- [ ] 7.9 创建 `frontend/components/monitoring/PerformanceCharts.tsx` 和 `CostAnalysisCharts.tsx`
- [ ] 7.10 创建 `frontend/app/[locale]/monitoring/alerts/page.tsx` 和 `frontend/components/monitoring/AlertList.tsx`、`AlertDetailModal.tsx`
- [ ] 7.11 创建 `frontend/hooks/useMonitoringData.ts` 和 `useAlerts.ts`（自动刷新：卡片 30s、图表 60s、告警 15s）
- [ ] 7.12 在 `frontend/public/locales/zh/common.json` 和 `en/common.json` 中添加所有 `monitoring.*` 翻译 key
- [ ] 7.13 添加 `recharts` 依赖到 `frontend/package.json`

## 8. 集成验证

- [ ] 8.1 验证数据库迁移在干净环境执行无报错
- [ ] 8.2 验证 `ENABLE_MODEL_MONITORING=false` 时所有监控代码跳过，原有功能不受影响
- [ ] 8.3 验证故障分类逻辑：构造 401/404/429/503/timeout 等错误，确认 `is_failure` 和 `is_error` 分类正确
- [ ] 8.4 验证 Grafana 仪表板自动加载和所有面板数据正确
- [ ] 8.5 验证前端监控页面：概览卡片、模型表格、故障分析、告警管理功能完整
- [ ] 8.6 验证租户数据隔离：不同租户用户只能看到自己租户的监控数据
- [ ] 8.7 验证 API Key 脱敏：故障详情 API 返回的错误消息中不含明文 API Key
