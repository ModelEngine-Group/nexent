## 修改的需求

### 需求：监控页面结构
监控模块 SHALL 实现为单个 Next.js 页面 `/monitoring`，使用 Ant Design Tabs 在"模型"和"告警"视图之间进行内部导航，通过 `useSetupFlow` 实现 framer-motion 页面过渡动画。模型详情 SHALL 通过点击模型对比表格中的模型行，在 Ant Design Drawer（720px 宽度）中展示。

#### 场景：用户导航到监控模块
- **WHEN** 用户在侧边栏点击"监控与运维"
- **THEN** 系统加载单个 `/monitoring` 页面，Models Tab 处于激活状态，展示 OverviewCards、MonitoringTrendChart 和 ModelComparisonTable

#### 场景：用户在对比表格中点击模型
- **WHEN** 用户在 ModelComparisonTable 中点击某个模型名称
- **THEN** 系统在右侧打开 Drawer，展示模型详情，内含 Tabs（概览含趋势图 + 性能指标、故障分析、成本分析）

#### 场景：用户切换到告警 Tab
- **WHEN** 用户点击"告警"Tab
- **THEN** 系统展示 AlertList 组件及所有告警记录

### 需求：监控子路由已移除
系统 SHALL 不再使用 `/monitoring/` 下的子路由页面。所有监控内容 SHALL 在单个 `/monitoring/page.tsx` 组件中使用 Tabs 和 Drawer 模式渲染。

#### 场景：直接访问旧子路由 URL
- **WHEN** 用户直接导航到 `/monitoring/models` 或 `/monitoring/alerts`
- **THEN** 系统返回 404（子路由页面已被移除）

## 新增需求

### 需求：Models Tab 中嵌入 MonitoringTrendChart 组件
Models Tab SHALL 包含 MonitoringTrendChart 组件，放置在 OverviewCards 和 ModelComparisonTable 之间。

#### 场景：页面加载时渲染趋势图
- **WHEN** 监控页面加载且 Models Tab 处于激活状态
- **THEN** 趋势图出现在概览卡片下方和对比表格上方，展示最近 24 小时的聚合请求数数据

### 需求：模型详情 Drawer 包含趋势图
模型详情 Drawer 的"概览"Tab SHALL 嵌入 MonitoringTrendChart，展示所选模型的趋势数据。

#### 场景：Drawer 中的趋势图
- **WHEN** 用户打开模型详情 Drawer
- **THEN** 概览 Tab 展示一个预过滤为该模型数据的趋势图，随后是性能指标
