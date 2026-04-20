## 1. 后端：聚合趋势 API

- [x] 1.1 在 `monitoring_app.py` 中添加 `_generate_multi_model_trend()` 函数 — 无 model_id 时生成带分模型明细的趋势数据点，指定 model_id 时生成平坦指标
- [x] 1.2 添加 `GET /monitoring/trend` 端点，支持 `interval`、`time_range`、`model_id` 查询参数
- [x] 1.3 在 `frontend/services/api.ts` 的 monitoring 区段添加 `trend` 端点 URL

## 2. 前端：趋势可视化组件

- [x] 2.1 创建 `frontend/components/monitoring/MonitoringTrendChart.tsx` — recharts AreaChart 渐变填充，5 种指标维度（请求数/错误率/故障率/耗时/成本），Segmented 指标选择器，Select 模型过滤下拉
- [x] 2.2 在 `monitoringService.ts` 中添加 `fetchAggregatedTrend()` 方法，调用 `GET /monitoring/trend`
- [x] 2.3 更新 `useMonitoringData` hook 以同时获取趋势数据，暴露 `trend`、`trendModelId`、`setTrendModelId`

## 3. 前端：单页面架构迁移

- [x] 3.1 将 `monitoring/page.tsx` 重写为单页面 + Tabs（Models / Alerts），使用 useSetupFlow 动画，Segmented 时间范围，刷新按钮
- [x] 3.2 在 `monitoring/page.tsx` 中创建 `ModelDetailDrawer` 组件 — Ant Design Drawer 720px 宽度，内含 Tabs（概览含趋势图 + PerformanceCharts，FailureDetailPanel，CostAnalysisCharts）
- [x] 3.3 更新 `ModelComparisonTable.tsx` — 将 `router.push` 替换为 `onModelClick` 回调 prop
- [x] 3.4 删除 `monitoring/models/page.tsx`、`monitoring/alerts/page.tsx`、`monitoring/models/[modelId]/page.tsx`
- [x] 3.5 删除 `MonitoringToolbar.tsx`（功能已合并到主页面）

## 4. 前端：集成与趋势图布局

- [x] 4.1 在 Models Tab 中将 MonitoringTrendChart 放置在 OverviewCards 和 ModelComparisonTable 之间
- [x] 4.2 连接 `trendModelId` 状态：Select 下拉变更触发 `setTrendModelId`，通过 useEffect 触发 `fetchAggregatedTrend`
- [x] 4.3 在 ModelDetailDrawer 的 Overview Tab 中添加 MonitoringTrendChart（预过滤为所选模型）
- [x] 4.4 在 `frontend/package.json` 中添加 recharts 依赖

## 5. 验证

- [x] 5.1 后端 API：`GET /monitoring/trend` 在 24h 范围返回 24 个数据点，无 model_id 时包含 `models` 分模型明细
- [x] 5.2 后端 API：`GET /monitoring/trend?model_id=model-1` 返回平坦数据点，不含 `models` 键
- [x] 5.3 前端：`http://localhost:3000/zh/monitoring` 返回 HTTP 200
- [x] 5.4 前端：dev server 日志无编译错误
- [x] 5.5 API 代理：`/api/monitoring/trend` 通过前端代理返回有效 JSON
