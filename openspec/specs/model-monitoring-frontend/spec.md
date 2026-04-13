
### Requirement: 系统 SHALL 提供模型监控主页面
系统 SHALL 将 `/monitoring` 页面从 "Coming Soon" 改为重定向到 `/monitoring/models`。`/monitoring/models` 页面 SHALL 包含：顶部工具栏（时间范围选择、模型过滤下拉、租户过滤下拉、刷新按钮）、概览卡片区（总请求数、错误率、故障率、平均耗时、今日成本）、模型对比表格（包含故障率列，支持排序、筛选、分页）、性能图表区（耗时趋势、Token 使用量趋势）、最近告警列表。

#### Scenario: 监控主页面展示完整数据
- **WHEN** 认证用户访问 `/monitoring/models`
- **THEN** 页面 SHALL 显示概览卡片（含故障率卡片）、模型对比表格（含故障率列，使用绿/黄/红颜色标识）、性能趋势图表、最近告警列表

#### Scenario: 故障率卡片显示与昨日对比
- **WHEN** 今日故障率为 0.2%，昨日为 0.3%
- **THEN** 故障率卡片 SHALL 显示 "0.2%"，下方显示 "↓0.1% vs 昨日"，颜色为绿色（< 0.5%）

### Requirement: 系统 SHALL 提供单模型详情页面
系统 SHALL 提供 `/monitoring/models/{modelId}` 详情页面，包含 Tab 切换：概览、趋势分析、故障分析、告警记录、成本明细。故障分析 Tab SHALL 包含：故障率趋势图（红色实线 + 阈值虚线）、故障类型分布饼图、故障类型堆叠面积图、故障详情列表表格。

#### Scenario: 查看模型故障分析
- **WHEN** 用户点击模型详情 → 切换到 "故障分析" Tab
- **THEN** 页面 SHALL 显示故障率趋势图、按 failure_type 分布的饼图、故障详情列表

#### Scenario: 从故障详情查看原始错误
- **WHEN** 用户在故障详情列表中点击某条 `auth_failure` 记录
- **THEN** 系统 SHALL 展开显示完整错误消息（API Key 已脱敏）、关联的智能体名称和对话 ID

### Requirement: 系统 SHALL 提供告警管理页面
系统 SHALL 提供 `/monitoring/alerts` 页面，包含：告警过滤工具栏（按类型/状态/严重级别/时间过滤）、告警列表（每条显示类型图标、模型名称、指标值与阈值、时间、状态）、每条告警提供"确认"和"解决"操作按钮、告警详情弹窗。

#### Scenario: 告警列表按严重级别排序
- **WHEN** 用户访问告警管理页面
- **THEN** 告警 SHALL 按 severity 排序（critical > warning > info），同级别按时间倒序

#### Scenario: 确认告警
- **WHEN** 用户点击某条 active 告警的"确认"按钮
- **THEN** 系统 SHALL 调用 `PUT /api/monitoring/alerts/{id}/acknowledge`，成功后该告警状态更新为 `acknowledged`

### Requirement: 系统 SHALL 支持监控页面国际化
系统 SHALL 在 `zh/common.json` 和 `en/common.json` 中添加所有监控相关的翻译 key（以 `monitoring.` 为前缀），包括指标名称、故障类型、告警类型、按钮文案、提示信息。页面 SHALL 根据当前语言设置正确显示中文或英文。

#### Scenario: 中文环境显示
- **WHEN** 用户语言设置为中文
- **THEN** 故障率标签 SHALL 显示 "故障率（不可恢复）"，`auth_failure` 类型 SHALL 显示 "认证失败"

#### Scenario: 英文环境显示
- **WHEN** 用户语言设置为英文
- **THEN** 故障率标签 SHALL 显示 "Failure Rate (Unrecoverable)"，`auth_failure` 类型 SHALL 显示 "Auth Failure"

### Requirement: 系统 SHALL 支持监控数据自动刷新
系统 SHALL 对概览卡片每 30 秒自动刷新、图表数据每 60 秒自动刷新、告警列表每 15 秒自动刷新。同时提供手动刷新按钮覆盖所有数据。使用前端缓存策略避免重复请求。

#### Scenario: 自动刷新生效
- **WHEN** 用户在监控页面停留 30 秒
- **THEN** 概览卡片数据 SHALL 自动更新为最新值，无需用户手动操作

### 需求：监控页面采用单页面 Tab+Drawer 架构
监控模块 SHALL 实现为单个 Next.js 页面 `/monitoring`，使用 Ant Design Tabs 在"模型"和"告警"视图之间进行内部导航，通过 `useSetupFlow` 实现 framer-motion 页面过渡动画。模型详情 SHALL 通过点击模型对比表格中的模型行，在 Ant Design Drawer（720px 宽度）中展示。

#### 场景：用户导航到监控模块
- **WHEN** 用户在侧边栏点击"监控与运维"
- **THEN** 系统加载单个 `/monitoring` 页面，Models Tab 处于激活状态，展示 OverviewCards、MonitoringTrendChart 和 ModelComparisonTable

#### 场景：用户在对比表格中点击模型
- **WHEN** 用户在 ModelComparisonTable 中点击某个模型名称
- **THEN** 系统在右侧打开 Drawer，展示模型详情，内含 Tabs（概览含趋势图 + 性能指标、故障分析、成本分析）

### 需求：MonitoringTrendChart 组件嵌入 Models Tab
Models Tab SHALL 包含 MonitoringTrendChart 组件，放置在 OverviewCards 和 ModelComparisonTable 之间。模型详情 Drawer 的"概览"Tab SHALL 同时嵌入 MonitoringTrendChart，展示所选模型的趋势数据。

#### 场景：页面加载时渲染趋势图
- **WHEN** 监控页面加载且 Models Tab 处于激活状态
- **THEN** 趋势图出现在概览卡片下方和对比表格上方，展示最近 24 小时的聚合请求数数据

#### 场景：Drawer 中的趋势图
- **WHEN** 用户打开模型详情 Drawer
- **THEN** 概览 Tab 展示一个预过滤为该模型数据的趋势图，随后是性能指标
