## Context

Nexent 的"监控与运维"模块已有 v1 规格（归档于 `openspec/changes/archive/2026-04-10-model-level-monitoring/`），定义了 6 个 capability spec。本次变更基于 v1 规格进行了前端架构重构和趋势可视化增强。

当前状态：
- 后端 `monitoring_app.py` 提供 7 个 API 端点（含 mock 数据）
- 前端原本为 3 个子路由页面（`/monitoring/models`、`/monitoring/alerts`、`/monitoring/models/[modelId]`）
- Nexent 其他模块（agents、chat、knowledges 等）均为单页面 + 内部 Tab 架构
- 缺少时间序列曲线可视化

约束：
- 项目规则：所有代码注释使用英文
- 前端技术栈：Next.js 15 + React 18 + TypeScript + Ant Design + Tailwind CSS
- 图表库：recharts（已添加到 package.json）
- 后端使用 FastAPI + `ConversationResponse(code=0, message="success", data=...)` 统一响应格式

## Goals / Non-Goals

**Goals:**
- 将监控模块从多页面子路由改为单页面 Tab+Drawer 架构，匹配 Nexent 现有模块模式
- 添加 recharts AreaChart 趋势曲线，支持 5 种指标维度切换
- 支持汇总（所有模型）和单一模型两种趋势视图切换
- 新增后端聚合趋势 API
- 模型详情通过 Drawer 展示，避免子路由跳转

**Non-Goals:**
- 不涉及数据库实际写入（仍使用 mock 数据）
- 不涉及 Grafana 仪表板修改
- 不涉及 SDK 指标采集层修改
- 不修改现有的告警系统逻辑

## Decisions

### D1: 单页面 Tab 架构替代多页面子路由

**选择**: 合并为 `/monitoring` 单页面，使用 Ant Design Tabs 导航
**替代方案**: 保持多页面子路由 + layout.tsx
**理由**: Nexent 所有模块（agents、chat、knowledges、models 等）均为单页面，无 layout.tsx 嵌套模式。保持一致性降低维护成本。

### D2: Drawer 替代子路由展示模型详情

**选择**: 使用 Ant Design Drawer（720px 宽度）展示模型详情
**替代方案**: 右侧滑入面板或全屏详情页
**理由**: Drawer 允许用户在查看详情时保持对主列表的上下文感知。子路由跳转会丢失滚动位置和筛选状态。

### D3: recharts AreaChart 作为趋势可视化

**选择**: recharts `AreaChart` + 线性渐变填充
**替代方案**: Ant Design 内置图表、ECharts、@ant-design/charts
**理由**: recharts 是 React 原生图表库（轻量、声明式），与项目技术栈最契合。AreaChart 带渐变填充比纯折线图更具可读性。

### D4: 趋势图模型过滤使用 Select 下拉

**选择**: Ant Design `Select` 组件放在趋势图卡片内
**替代方案**: Segmented（只支持平铺选项）、Radio.Group
**理由**: 模型列表可能超过 5 个，Select 下拉支持滚动和搜索，不占用水平空间。

### D5: 聚合趋势 API 复用 /monitoring/trend 端点

**选择**: 新增 `GET /monitoring/trend` 端点，通过 `model_id` 可选参数区分汇总/单模型
**替代方案**: 两个独立端点
**理由**: 单端点减少维护成本，参数可选性强，响应结构统一。

### D6: ModelComparisonTable 使用回调而非路由跳转

**选择**: `onModelClick` 回调 prop，由父组件控制行为
**替代方案**: 维持 `router.push`
**理由**: 配合 Drawer 架构，表格点击触发回调打开 Drawer，而非路由跳转。

## Risks / Trade-offs

- **[recharts 包体积]** → recharts ~200KB gzipped。仅在 `/monitoring` 路由懒加载，不影响其他页面性能。
- **[Mock 数据一致性]** → 聚合趋势和单模型趋势使用不同的随机种子，数值可能不完全对应。生产环境使用真实数据库后将自然解决。
- **[Drawer 空间限制]** → 720px 宽度在移动端可能过窄。响应式处理：移动端改为全屏 Modal。
