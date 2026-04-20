## Why

模型监控模块（v1 规格已归档）需要从多页面路由架构调整为单页面 Tab 集成架构，以匹配 Nexent 现有的模块导航模式。同时缺少趋势曲线可视化能力——运维人员无法直观看到模型调用量、错误率、故障率、响应时间、成本等指标随时间的变化走势，也无法在汇总视图和单一模型视图之间快速切换。

## What Changes

- **架构重构**: 将 `/monitoring/models`、`/monitoring/alerts`、`/monitoring/models/[modelId]` 三个子路由页面合并为单个 `/monitoring` 页面，使用 Ant Design Tabs 进行内部导航，使用 Drawer 展示模型详情
- **新增趋势曲线组件**: 使用 recharts AreaChart 展示 5 种指标（请求数、错误率、故障率、平均耗时、成本）的时间序列曲线
- **汇总/单模型切换**: 趋势图支持"所有模型汇总"与"单一模型"两种显示模式，通过 Select 下拉切换
- **新增聚合趋势 API**: `GET /monitoring/trend` 端点，支持 `model_id` 可选参数，返回汇总或单模型趋势数据
- **删除 MonitoringToolbar 组件**: 其功能合并到主页面
- **移除 framer-motion 缺失问题**: 添加 `useSetupFlow` 页面过渡动画，匹配其他模块风格

## Capabilities

### New Capabilities

- `model-trend-visualization`: 模型调用趋势曲线可视化——支持汇总/单模型切换的 recharts AreaChart 组件，5 种指标维度，时间范围联动

### Modified Capabilities

- `model-monitoring-frontend`: 从多页面子路由改为单页面 Tab+Drawer 集成架构，新增趋势图组件嵌入
- `model-monitoring-api`: 新增 `GET /monitoring/trend` 聚合趋势端点，支持 `model_id` 过滤参数

## Impact

- **前端组件**: 新增 `MonitoringTrendChart.tsx`；重写 `monitoring/page.tsx`；删除 `MonitoringToolbar.tsx`；修改 `ModelComparisonTable.tsx`（router.push → callback）
- **前端路由**: 删除 `/monitoring/models/`、`/monitoring/alerts/`、`/monitoring/models/[modelId]/` 子路由
- **前端依赖**: recharts 已添加到 package.json
- **后端 API**: `monitoring_app.py` 新增 `/trend` 端点和 `_generate_multi_model_trend` 函数
- **前端 hooks**: `useMonitoringData` 扩展为同时获取趋势数据，新增 `trendModelId` 状态
- **前端 service**: `monitoringService.ts` 新增 `fetchAggregatedTrend` 方法；`api.ts` 新增 `trend` 端点
