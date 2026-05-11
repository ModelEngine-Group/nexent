# 🎨 前端改进说明

本文档详细介绍病理学AI助手中的前端优化和新增组件。

## 新增组件

### 1. PathologyImageGallery.tsx

**位置**: `frontend/components/medical-visualization/PathologyImageGallery.tsx`

**功能**: 病理图片画廊组件，用于展示和预览病理图片

**特性**:
- 网格布局展示图片
- 点击图片放大预览
- 支持图片分类标签
- 响应式设计

### 2. DiagnosisConfidenceCard.tsx

**位置**: `frontend/components/medical-visualization/DiagnosisConfidenceCard.tsx`

**功能**: 置信度评估卡片组件

**特性**:
- 显示总体置信度分数
- 风险等级指示器 (LOW/MEDIUM/HIGH/CRITICAL)
- 评估维度雷达图
- 建议和警告显示

### 3. SourceTag.tsx

**位置**: `frontend/components/medical-visualization/SourceTag.tsx`

**功能**: 来源标签组件，用于标注信息来源

**特性**:
- [内部] 标签 - 蓝色，表示来自本地知识库
- [外部] 标签 - 绿色，表示来自互联网搜索
- 悬停显示详细来源信息

---

## 修改的组件

### 1. MedicalVisualizationPanel.tsx

**位置**: `frontend/components/medical-visualization/MedicalVisualizationPanel.tsx`

**修改内容**:
- 移除HIV/AIDS硬编码文字
- 改为通用病理学描述
- 支持动态标题和描述

**修改行**: 54-56, 97

### 2. markdownRenderer.tsx

**位置**: `frontend/components/ui/markdownRenderer.tsx`

**修改内容**:
- 新增 `ClickableOption` 组件
- 解析 `[btn:xxx]` 格式为可点击按钮
- 支持诊断游戏交互

**新增代码位置**: 378-410行 (ClickableOption组件), 975-1045行 (processText函数)

### 3. chatLeftSidebar.tsx

**位置**: `frontend/app/[locale]/chat/components/chatLeftSidebar.tsx`

**修改内容**:
- 新增"清空所有对话"按钮
- 新增删除确认对话框
- 新增 `handleDeleteAllClick` 和 `confirmDeleteAll` 函数

**修改行**: 10, 136-138, 209-227, 463-475, 507-541

### 4. conversationService.ts

**位置**: `frontend/services/conversationService.ts`

**修改内容**:
- 新增 `deleteAll` 方法用于批量删除对话

**修改行**: 122-130

### 5. index.ts (医学可视化组件导出)

**位置**: `frontend/components/medical-visualization/index.ts`

**修改内容**:
- 添加新组件的导出语句

---

## 组件使用示例

### PathologyImageGallery

```tsx
import { PathologyImageGallery } from '@/components/medical-visualization';

<PathologyImageGallery 
  images={[
    { url: "http://...", title: "HIV淋巴结", category: "Immunopathology" }
  ]}
/>
```

### DiagnosisConfidenceCard

```tsx
import { DiagnosisConfidenceCard } from '@/components/medical-visualization';

<DiagnosisConfidenceCard 
  confidence={0.85}
  riskLevel="MEDIUM"
  dimensions={[
    { name: "证据充分度", score: 0.9 },
    { name: "一致性", score: 0.8 }
  ]}
/>
```

### SourceTag

```tsx
import { SourceTag } from '@/components/medical-visualization';

<SourceTag type="internal" /> // 显示 [内部]
<SourceTag type="external" /> // 显示 [外部]
```

### 可点击按钮 (Markdown中)

在AI回复中使用 `[btn:选项文字]` 格式，会自动渲染为可点击按钮：

```markdown
请选择下一步操作：

[btn:询问发热情况] [btn:询问其他症状] [btn:进入体格检查]
```

---

## 样式说明

所有新增组件使用：
- **TailwindCSS** 进行样式定义
- **Lucide React** 图标库
- **shadcn/ui** 基础组件

遵循 Nexent 现有设计规范，保持视觉一致性。
