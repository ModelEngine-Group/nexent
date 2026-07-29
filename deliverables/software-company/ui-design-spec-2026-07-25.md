# Nexent 生态市场 UI 设计规范

> UI Designer  
> 日期：2026-07-25  
> 基于：nexent-market-architecture-2026-07-25.md 系统架构设计  

---

## 目录

- [1. 设计系统基础](#1-设计系统基础)
- [2. 组件设计](#2-组件设计)
- [3. 页面设计](#3-页面设计)
- [4. 交互状态](#4-交互状态)
- [5. 响应式设计](#5-响应式设计)
- [6. 可访问性标准](#6-可访问性标准)
- [7. 开发交接规格](#7-开发交接规格)

---

## 1. 设计系统基础

### 1.1 设计语言

沿用 Nexent 现有的 **Purple-Indigo 渐变设计语言**，在保持一致性的基础上扩展为多实体类型的市场系统。

| 设计原则 | 说明 |
|---------|------|
| 一致性优先 | 三种实体类型（Agent/Skill/MCP）使用统一的卡片骨架和间距系统 |
| 类型可区分 | 通过颜色编码区分实体类型，不依赖图标文字 |
| 零配置优先 | 官方预置内容突出"⚡"标记，降低用户决策成本 |
| 空间留白 | 卡片间距 16px（gap-4），保持视觉呼吸感 |

### 1.2 色彩系统

#### 主色板（Purple-Indigo）

| Token | Hex | 用途 |
|-------|-----|------|
| `--color-primary-50` | `#EEEDFE` | 背景填充、徽章背景 |
| `--color-primary-100` | `#CECBF6` | 次级边框、悬停状态 |
| `--color-primary-200` | `#AFA9EC` | 分隔线、次要元素 |
| `--color-primary-400` | `#7F77DD` | 主理人角色标识、中间状态 |
| `--color-primary-500` | `#534AB7` | 主按钮、激活态、链接 |
| `--color-primary-800` | `#3C3489` | 标题文字 |
| `--color-primary-900` | `#26215C` | 卡片标题 |

#### 实体类型编码色

| 实体类型 | 色板 | 用途 |
|---------|------|------|
| **Agent** | Purple (`#534AB7`) | 主色，卡片顶部色条 |
| **Skill** | Teal (`#1D9E75` / `#E1F5EE`) | Recipe 可视化中的 Skill 节点 |
| **MCP** | Amber (`#BA7517` / `#FAEEDA`) | Recipe 可视化中的 MCP 节点 |
| **Recipe** | Blue (`#378ADD` / `#E6F1FB`) | 组合配方卡片标识 |
| **Expert** | Purple + 特殊徽章 | 专家包，沿用主色但加 Official 徽章 |

#### 语义色

| Token | Hex | 用途 |
|-------|-----|------|
| `--color-success` | `#1D9E75` | 安装成功、依赖可用 |
| `--color-warning` | `#BA7517` | 依赖缺失、需配置 |
| `--color-error` | `#D85A30` | 安装失败、权限不足 |
| `--color-info` | `#378ADD` | 提示信息 |

### 1.3 排版系统

沿用现有 Tailwind + antd 排版：

| 层级 | Tailwind Class | 字号 | 字重 | 用途 |
|------|---------------|------|------|------|
| h1 | `text-3xl` | 30px | 700 (bold) | 页面标题 |
| h2 | `text-2xl` | 24px | 700 (bold) | 区域标题 |
| h3 | `text-lg` | 18px | 600 (semibold) | 卡片标题 |
| body | `text-sm` | 14px | 400 (normal) | 正文 |
| label | `text-xs` | 12px | 400 (normal) | 标签、辅助文字 |
| badge | `text-xs` | 12px | 500 (medium) | 徽章文字 |
| count | `text-xs` | 12px | 400 (normal) | 下载数、数量 |

### 1.4 间距系统

| Token | rem | px | 用途 |
|-------|-----|----|----|
| `--space-1` | 0.25rem | 4px | 微间距、图标内边距 |
| `--space-2` | 0.5rem | 8px | 小间距 |
| `--space-3` | 0.75rem | 12px | 徽章内边距 |
| `--space-4` | 1rem | 16px | **卡片间距（gap-4）** |
| `--space-6` | 1.5rem | 24px | 卡片内边距 |
| `--space-8` | 2rem | 32px | 区域间距 |
| `--space-12` | 3rem | 48px | 页面区块间距 |

### 1.5 圆角系统

| Token | 值 | 用途 |
|-------|---|------|
| `--radius-sm` | 4px | 小徽章、标签 |
| `--radius-md` | 6px | 按钮、输入框 |
| `--radius-lg` | 8px | 小卡片、chip |
| `--radius-xl` | 10px | 标准卡片 |
| `--radius-2xl` | 12px | 大卡片、容器 |
| `--radius-full` | 9999px | 头像、圆形徽章 |

### 1.6 阴影系统

沿用 framer-motion 动画驱动：

| Token | 值 | 用途 |
|-------|---|------|
| `--shadow-card` | `0 1px 2px 0 rgb(0 0 0 / 0.05)` | 默认卡片 |
| `--shadow-hover` | `0 10px 15px -3px rgba(0,0,0,0.1), 0 4px 6px -2px rgba(0,0,0,0.05)` | 悬停卡片 |
| `--shadow-featured` | 全卡 `linear-gradient(180deg, rgba(139,92,246,0.06), rgba(99,102,241,0.04))` | 精选卡片叠加层 |

---

## 2. 组件设计

### 2.1 OfficialBadge 官方徽章

**路径**: `frontend/components/market/OfficialBadge.tsx`

| 属性 | 值 |
|------|---|
| 背景 | `#534AB7` (primary-500) |
| 圆角 | 8px (radius-full) |
| 内边距 | 2px 8px |
| 文字 | "Official" / "官方"，10px，500，白色 |
| 图标 | 白色实心圆点（4px），左侧 |
| 尺寸 | 高度 18px |

```tsx
// 设计规格
<Badge 
  style={{
    background: '#534AB7',
    color: '#FFFFFF',
    fontSize: '10px',
    fontWeight: 500,
    borderRadius: '9999px',
    padding: '2px 8px',
    display: 'inline-flex',
    alignItems: 'center',
    gap: '4px',
  }}
>
  <Circle size={4} color="#FFFFFF" />
  Official
</Badge>
```

### 2.2 AgentMarketCard（已有，保持不变）

维持现有设计，仅扩展 `source` 字段支持：

- 官方预置：显示 OfficialBadge
- 社区发布：显示 "By {author}" 文字

### 2.3 SkillMarketCard

**路径**: `frontend/app/[locale]/market/components/SkillMarketCard.tsx`

与 AgentMarketCard 结构一致，差异点：

| 元素 | Agent 卡片 | Skill 卡片 |
|------|-----------|-----------|
| 类型标识色 | Purple (`#534AB7`) | Teal (`#1D9E75`) |
| 顶部色条 | `bg-purple-500 opacity-8%` | `bg-teal-500 opacity-8%` |
| 类别标签色 | `text-purple-600` | `text-teal-600` |
| 下载按钮 | `from-purple-500 to-indigo-500` | `from-teal-500 to-green-500` |
| 统计信息 | tool_count | usage_count（使用次数） |

### 2.4 McpMarketCard

**路径**: `frontend/app/[locale]/market/components/McpMarketCard.tsx`

差异点：

| 元素 | 值 |
|------|---|
| 类型标识色 | Amber (`#BA7517`) |
| 顶部色条 | `bg-amber-500 opacity-8%` |
| 统计信息 | server_type（stdio/sse）+ tool_count |
| 下载按钮 | `from-amber-500 to-orange-500` |

### 2.5 RecipeMarketCard

**路径**: `frontend/app/[locale]/market/components/RecipeMarketCard.tsx`

组合配方卡片，特殊设计：

| 元素 | 值 |
|------|---|
| 类型标识色 | Blue (`#378ADD`) |
| 特殊标记 | 显示组合数：3 Agents + 2 Skills + 1 MCP |
| 下载按钮 | "Use recipe" 替代 "Download" |
| 组合可视化 | 迷你节点图：A→S→M 三色节点 |

### 2.6 ExpertCard

**路径**: `frontend/app/[locale]/market/components/ExpertCard.tsx`

#### 大尺寸变体（Featured/详情区）

| 元素 | 规格 |
|------|------|
| 卡片宽度 | 320px |
| 卡片高度 | 最小 290px |
| 顶部色条 | 3px，`#534AB7`（Team型满色，Agent型 60% 透明度） |
| 头像 | 48px 圆形，`#EEEDFE` 背景 + `#534AB7` 边框 |
| Official 徽章 | 右上角，紧邻头像 |
| 类型徽章 | "Team" / "Agent"，区分背景色 |
| 成员 chips | 20px 高，圆角 10px，主理人用 `#EEEDFE` 突出 |
| IndustryRule 徽章 | Teal 背景，显示 "Guardrails active" |
| 安装按钮 | 124px 宽，`#534AB7` 背景 |

#### 紧凑变体（列表中）

| 元素 | 规格 |
|------|------|
| 卡片宽度 | 200px |
| 卡片高度 | 190px |
| 头像 | 32px 圆形 |
| 成员展示 | 头像重叠堆叠（-7px 偏移），最多展示 6 个 |
| 安装按钮 | 168px 宽，满宽 |

### 2.7 PresetAgentCard

**路径**: `frontend/app/[locale]/newchat/assistant-ui/components/PresetAgentCard.tsx`

零配置启动卡片：

| 元素 | 规格 |
|------|------|
| 卡片宽度 | 200px |
| 卡片高度 | 140px |
| 顶部色条 | 3px，`#534AB7` |
| 头像 | 36px 圆形，`#EEEDFE` 背景 |
| ⚡ 标记 | 右上角 20px 圆形，`#EEEDFE` 背景 |
| 快捷提示框 | 168px 宽，`#FAFAFB` 背景 + `#CECBF6` 边框 |
| 提示文字 | 10px，`#534AB7`（紫色提示预填文本） |

### 2.8 RecipeVisualizer

**路径**: `frontend/app/[locale]/agents/template/[template_id]/components/RecipeVisualizer.tsx`

组合关系可视化：

| 元素 | 规格 |
|------|------|
| 容器 | 632px 宽，130px 高，白底卡片 |
| Agent 节点 | 140×44px，`#EEEDFE` 背景 + `#534AB7` 边框 |
| Skill 节点 | 120×36px，`#E1F5EE` 背景 + `#1D9E75` 边框 |
| MCP 节点 | 140×36px，`#FAEEDA` 背景 + `#BA7517` 边框 |
| 连接线 | 虚线（dasharray 3,2），0.5px，`#B4B2A9` |
| 节点图标 | 左侧 8px 圆形，填充对应类型色 |
| 图例 | 底部行，8×8px 色块 + 文字 |

### 2.9 RecipeForm

**路径**: `frontend/app/[locale]/agents/template/[template_id]/components/RecipeForm.tsx`

动态表单，根据 `recipe.variables` 渲染：

| 变量类型 | 渲染组件 | antd 组件 |
|---------|---------|----------|
| `string` | 文本输入 | `<Input>` |
| `number` | 数字输入 | `<InputNumber>` |
| `select` | 下拉选择 | `<Select>` |
| `radio` | 单选组 | `<Radio.Group>` |
| `boolean` | 开关 | `<Switch>` |

**必填标记**：`required` 变量显示 `#EEEDFE` 背景的 "required" 小标签（40×16px，圆角 4px）。

### 2.10 ReviewSection

**路径**: `frontend/app/[locale]/agents/template/[template_id]/components/ReviewSection.tsx`

| 元素 | 规格 |
|------|------|
| 评分展示 | 星级（5星），`#EF9F27` 填充 |
| 评论项 | 632×52px 卡片，头像 28px + 评论文字 |
| 写评论按钮 | 80×28px，白底紫边框 |
| 评分摘要 | "4.8 · 23 reviews" 格式 |

---

## 3. 页面设计

### 3.1 统一市场页 `/market`

**路径**: `frontend/app/[locale]/market/page.tsx`（重构）

#### 页面结构

```
┌─────────────────────────────────────────────┐
│ Header: 🛒 Agent Market + Search bar       │
├─────────────────────────────────────────────┤
│ Tabs: Agents | Skills | MCPs | Recipes |  │
│       Experts  (含数量徽章)                 │
├─────────────────────────────────────────────┤
│ Sub-tabs: All · Research · Writing · ...  │
├─────────────────────────────────────────────┤
│ ★ Featured banner (632×70px)                │
├─────────────────────────────────────────────┤
│ Card grid (4 columns, gap-4)               │
│  ┌────┐ ┌────┐ ┌────┐ ┌────┐              │
│  │Card│ │Card│ │Card│ │Card│              │
│  └────┘ └────┘ └────┘ └────┘              │
│  ┌────┐ ┌────┐ ┌────┐ ┌────┐              │
│  │Card│ │Card│ │Card│ │Card│              │
│  └────┘ └────┘ └────┘ └────┘              │
├─────────────────────────────────────────────┤
│ Pagination                                  │
└─────────────────────────────────────────────┘
```

#### Tab 数量徽章设计

| 状态 | 背景 | 文字色 |
|------|------|--------|
| 激活 Tab | `#EEEDFE` (primary-50) | `#534AB7` (primary-500) |
| 非激活 Tab | `#F1EFE8` (gray-50) | `#888780` (gray-400) |
| 尺寸 | 高 14px，圆角 7px，字号 10px |

#### Featured banner 设计

| 属性 | 值 |
|------|---|
| 背景 | `#EEEDFE` (primary-50) |
| 边框 | 0.5px `#CECBF6` (primary-100) |
| 圆角 | 12px |
| 尺寸 | 632×70px |
| 内含 | "★ Featured this week" 标题 + 描述 + Official 徽章 + "View →" 按钮 |
| View 按钮 | 76×34px，`#534AB7` 背景，白色文字 |

#### 响应式列数

| 断点 | 列数 |
|------|------|
| `< 768px` (mobile) | 1 列 |
| `768px - 1023px` (tablet) | 2 列 |
| `1024px - 1279px` (desktop) | 3 列 |
| `≥ 1280px` (large) | 4 列 |

### 3.2 模板详情页 `/agents/template/[template_id]`

**路径**: `frontend/app/[locale]/agents/template/[template_id]/page.tsx`

#### 页面结构（从上到下）

1. **TemplateHeader**（632×84px 卡片）
   - 左侧 4px 紫色色条
   - 头像 44px 圆形
   - Official 徽章 + Template 徽章
   - 标题 + 版本 + 下载数 + 更新时间
   - 右侧 "One-click create" 按钮（120×36px）

2. **TemplateIntro**（文字区）
   - h2 标题 "Introduction"
   - 两行描述文字

3. **RecipeVisualizer**（632×130px 卡片）
   - h2 标题 "Recipe composition"
   - 节点图：Agent 顶部居中 → 连接线 → Skills/MCPs 底部
   - 图例行

4. **RecipeForm**（632×124px 卡片）
   - h2 标题 "Configure recipe variables"
   - 2 列网格布局表单
   - 每个 variable 含 label + description + input

5. **ReviewSection**
   - h2 标题 "Reviews" + 评分摘要
   - 单条评论卡片（632×52px）
   - "Write review" 按钮

### 3.3 Newchat Landing 页

**路径**: `frontend/app/[locale]/newchat/assistant-ui/agent-landing.tsx`（修改）

#### 新增区域

在现有聊天输入框下方添加：

```
┌─────────────────────────────────────────────┐
│ Chat input (632×40px)                       │
├─────────────────────────────────────────────┤
│ Quick start with presets                    │
│ ──── (60px 紫色短线) ──── No config needed │
├─────────────────────────────────────────────┤
│ Preset cards grid (3×2 = 6 cards)           │
│  ┌──────┐ ┌──────┐ ┌──────┐                │
│  │ ⚡🔬 │ │ ⚡💻 │ │ ⚡✍️ │                │
│  │Research│ │Review│ │Writer│               │
│  │prompt │ │prompt│ │prompt│               │
│  └──────┘ └──────┘ └──────┘                │
│  ┌──────┐ ┌──────┐ ┌──────┐                │
│  │ ⚡📊 │ │ ⚡🎨 │ │ ⚡📝 │                │
│  │Data  │ │UI Des│ │Email │                │
│  └──────┘ └──────┘ └──────┘                │
├─────────────────────────────────────────────┤
│ ⚡ = Zero config · Platform API key         │
│                              [Browse all →] │
└─────────────────────────────────────────────┘
```

---

## 4. 交互状态

### 4.1 卡片悬停状态

```css
.card-hover {
  transition: all 300ms ease;
}
.card-hover:hover {
  transform: translateY(-4px);
  box-shadow: 0 10px 15px -3px rgba(0,0,0,0.1), 0 4px 6px -2px rgba(0,0,0,0.05);
  border-color: #AFA9EC; /* primary-200 */
}
```

### 4.2 按钮状态

| 状态 | 主按钮 | 次按钮 |
|------|--------|--------|
| Default | `#534AB7` 背景 | 白色背景 + `#534AB7` 边框 |
| Hover | `#7F77DD`（亮色） | `#EEEDFE` 背景 |
| Active | `#3C3489`（暗色） | `#CECBF6` 背景 |
| Disabled | opacity 0.6, cursor not-allowed | 同左 |
| Focus | 2px outline `#534AB7` + 2px offset | 同左 |

### 4.3 加载状态

| 场景 | 组件 |
|------|------|
| 列表加载 | antd `<Spin size="large">` 居中 |
| 详情加载 | 8px 圆圈旋转 + `#534AB7` 边框 |
| 安装中 | 按钮 text 变为 "Installing..." + spinner |
| 表单提交 | 按钮 loading 状态 + 禁用 |

### 4.4 空状态

| 场景 | 显示内容 |
|------|---------|
| 无搜索结果 | antd `<Empty>` + "No agents found in this category" |
| 无评论 | "No reviews yet. Be the first to review!" |
| 无 Recipe 变量 | 隐藏 RecipeForm，直接显示 "One-click create" 按钮 |

### 4.5 错误状态

| 场景 | 显示内容 |
|------|---------|
| 网络错误 | MarketErrorState 组件（已有） |
| 依赖预检失败 | 422 + 缺失项列表 + 补配引导提示 |
| 安装失败 | antd `message.error` + 错误描述 |
| 权限不足 | 403 + "You do not have permission" 提示 |

---

## 5. 响应式设计

### 5.1 断点策略（沿用现有）

| 断点 | 像素 | Tailwind | 布局调整 |
|------|------|----------|---------|
| Mobile | 320-639px | `sm:` | 单列，搜索栏满宽 |
| Tablet | 640-1023px | `md:` | 2 列卡片，精选区 2 列 |
| Desktop | 1024-1279px | `lg:` | 3 列卡片 |
| Large | 1280px+ | `xl:` | 4 列卡片，搜索栏 max-w-md |

### 5.2 组件适配

| 组件 | Mobile | Desktop |
|------|--------|---------|
| FeaturedCarousel | 1 列滚动 | 4 列宽度 |
| ExpertCard | 紧凑变体满宽 | 大变体 + 紧凑变体混排 |
| RecipeForm | 单列堆叠 | 2 列网格 |
| RecipeVisualizer | 节点垂直排列 | 节点水平+垂直混排 |
| PresetAgentCard | 2 列 | 3 列 |

---

## 6. 可访问性标准

### 6.1 WCAG AA 合规

| 要求 | 标准 | 实现 |
|------|------|------|
| 文字对比度 | 4.5:1（正常文字） | `#26215C` on `#FFFFFF` = 12.3:1 ✓ |
| | 3:1（大文字） | `#534AB7` on `#EEEDFE` = 4.6:1 ✓ |
| 焦点可见 | 2px outline + 2px offset | 所有交互元素 |
| 键盘导航 | Tab 顺序逻辑 | Tab 索引按视觉顺序 |

### 6.2 触摸目标

| 元素 | 最小尺寸 | 实际尺寸 |
|------|---------|---------|
| 下载按钮 | 44×44px | 120×22px（需增大 padding） |
| Tab 标签 | 44×44px | 文字 + padding ≈ 44px ✓ |
| 卡片点击区 | 44×44px | 整卡可点击 ✓ |
| 分页按钮 | 44×44px | antd Pagination 默认 32px（需 size="default"） |

### 6.3 屏幕阅读器

| 元素 | ARIA 属性 |
|------|----------|
| Tab 列表 | `role="tablist"`, 每个 Tab `role="tab"` + `aria-selected` |
| 卡片 | `role="article"` + `aria-label="{name} - {category}"` |
| 按钮 | `aria-label` 描述动作 |
| 加载状态 | `aria-live="polite"` + `aria-busy="true"` |
| 精选轮播 | `aria-label="Featured agents"` + 滚动按钮 `aria-label` |

### 6.4 动画敏感度

```css
@media (prefers-reduced-motion: reduce) {
  * {
    animation-duration: 0.01ms !important;
    transition-duration: 0.01ms !important;
  }
}
```

---

## 7. 开发交接规格

### 7.1 文件清单

| # | 文件路径 | 类型 | 说明 |
|---|---------|------|------|
| 1 | `frontend/components/market/OfficialBadge.tsx` | N | 官方徽章组件 |
| 2 | `frontend/app/[locale]/market/components/MarketHeader.tsx` | N | 市场页头部 |
| 3 | `frontend/app/[locale]/market/components/SearchBar.tsx` | N | 统一搜索栏 |
| 4 | `frontend/app/[locale]/market/components/FeaturedCarousel.tsx` | N | 精选轮播 |
| 5 | `frontend/app/[locale]/market/components/SkillMarketCard.tsx` | N | Skill 卡片 |
| 6 | `frontend/app/[locale]/market/components/McpMarketCard.tsx` | N | MCP 卡片 |
| 7 | `frontend/app/[locale]/market/components/RecipeMarketCard.tsx` | N | Recipe 卡片 |
| 8 | `frontend/app/[locale]/market/components/ExpertCard.tsx` | N | 专家包卡片 |
| 9 | `frontend/app/[locale]/agents/template/[template_id]/page.tsx` | N | 模板详情页 |
| 10 | `frontend/app/[locale]/agents/template/[template_id]/components/TemplateHeader.tsx` | N | 模板头部 |
| 11 | `frontend/app/[locale]/agents/template/[template_id]/components/TemplateIntro.tsx` | N | 模板介绍 |
| 12 | `frontend/app/[locale]/agents/template/[template_id]/components/RecipeVisualizer.tsx` | N | Recipe 可视化 |
| 13 | `frontend/app/[locale]/agents/template/[template_id]/components/RecipeForm.tsx` | N | Recipe 动态表单 |
| 14 | `frontend/app/[locale]/agents/template/[template_id]/components/ReviewSection.tsx` | N | 评分评论 |
| 15 | `frontend/app/[locale]/newchat/assistant-ui/components/PresetAgentCard.tsx` | N | 预置 Agent 卡片 |

### 7.2 设计 Token CSS 变量

```css
:root {
  /* Entity type colors */
  --entity-agent: #534AB7;
  --entity-agent-bg: #EEEDFE;
  --entity-skill: #1D9E75;
  --entity-skill-bg: #E1F5EE;
  --entity-mcp: #BA7517;
  --entity-mcp-bg: #FAEEDA;
  --entity-recipe: #378ADD;
  --entity-recipe-bg: #E6F1FB;
  
  /* Official badge */
  --official-badge-bg: #534AB7;
  --official-badge-text: #FFFFFF;
  
  /* Featured overlay */
  --featured-overlay: linear-gradient(180deg, rgba(139,92,246,0.06), rgba(99,102,241,0.04));
  
  /* Card structure */
  --card-border: 0.5px solid #B4B2A9;
  --card-radius: 10px;
  --card-top-bar-height: 3px;
}
```

### 7.3 framer-motion 动画规格

```typescript
// 卡片入场动画
const cardVariants = {
  initial: { opacity: 0, scale: 0.9 },
  animate: { opacity: 1, scale: 1 },
  exit: { opacity: 0, scale: 0.9 },
};

const cardTransition = {
  duration: 0.3,
  delay: 0.05 * index, // 错开入场
};

// 卡片悬停动画
const cardHover = {
  y: -4,
  boxShadow: "0 10px 15px -3px rgba(0,0,0,0.1), 0 4px 6px -2px rgba(0,0,0,0.05)",
};

const cardHoverTransition = {
  type: "spring",
  stiffness: 300,
  damping: 25,
};

// 页面入场
const pageVariants = {
  initial: { opacity: 0, y: -20 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: 20 },
};
```

### 7.4 antd 组件定制

```typescript
// Tabs 主题定制
const theme = {
  components: {
    Tabs: {
      itemActiveColor: '#534AB7',
      itemHoverColor: '#7F77DD',
      itemSelectedColor: '#534AB7',
      inkBarColor: '#534AB7',
    },
    Button: {
      primaryColor: '#FFFFFF',
      primaryBg: '#534AB7',
      primaryHoverBg: '#7F77DD',
      primaryActiveBg: '#3C3489',
    },
    Input: {
      activeBorderColor: '#534AB7',
      activeShadow: '0 0 0 3px rgba(83,74,183,0.1)',
    },
  },
};
```

---

## 附录：组件设计决策记录

| 决策 | 选择 | 理由 |
|------|------|------|
| 类型编码方式 | 颜色（非图标） | 色觉友好，快速扫描识别 |
| 精选卡片 | 全卡渐变叠加层 | 沿用现有设计，不破坏一致性 |
| 成员展示 | chips（大）+ 头像堆叠（小） | 大版详细，小版紧凑 |
| Recipe 可视化 | 节点图（非树） | 展示组合关系，非层级 |
| 表单布局 | 2 列网格 | 减少垂直空间，桌面端优化 |
| 预置卡片提示 | 预填文本框 | 降低空白页焦虑，引导用户 |

---

**UI Designer**: UI Designer  
**设计系统日期**: 2026-07-25  
**实现状态**: Ready for developer handoff  
**QA 流程**: Design review + accessibility validation pending
