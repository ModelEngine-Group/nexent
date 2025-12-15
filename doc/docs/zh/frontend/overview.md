# 前端架构概览

Nexent 的前端采用现代 React 技术构建，为 AI 智能体交互提供响应式和直观的用户界面。

## 技术栈

- **框架**: Next.js 14 (App Router)
- **语言**: TypeScript
- **UI库**: React + Tailwind CSS
- **状态管理**: React Hooks
- **国际化**: react-i18next
- **HTTP客户端**: Fetch API

## 目录结构

```
frontend/
├── app/                          # Next.js App Router
│   └── [locale]/                 # 国际化路由 (zh/en)
│       ├── chat/                 # 聊天界面
│       │   ├── internal/         # 聊天核心逻辑
│       │   ├── layout/           # 聊天界面布局组件
│       │   └── streaming/        # 流式响应处理
│       ├── setup/                # 系统设置页面
│       │   ├── agentSetup/       # 代理配置
│       │   ├── knowledgeBaseSetup/ # 知识库配置
│       │   └── modelSetup/       # 模型配置
│       └── layout.tsx            # 全局布局
├── components/                    # 可复用UI组件
│   ├── providers/                # 上下文提供者
│   └── ui/                       # 基础UI组件库
├── services/                     # API服务层
│   ├── api.ts                    # API基础配置
│   ├── conversationService.ts    # 对话服务
│   ├── agentConfigService.ts     # 代理配置服务
│   ├── knowledgeBaseService.ts   # 知识库服务
│   └── modelService.ts           # 模型服务
├── hooks/                        # 自定义React Hooks
├── lib/                          # 工具库
├── types/                        # TypeScript类型定义
├── public/                       # 静态资源
│   └── locales/                  # 国际化文件
└── middleware.ts                 # Next.js中间件
```

## 架构职责

### **展示层**
- 用户界面和交互逻辑
- 基于组件的可复用架构
- 多设备响应式设计

### **服务层**
- 封装API调用和数据转换
- 处理与后端服务的通信
- 管理错误处理和重试逻辑

### **状态管理**
- 使用React Hooks管理组件状态
- Context提供者管理全局状态
- 流式响应的实时更新

### **国际化**
- 支持中英文语言切换
- 动态语言切换
- 本地化内容和UI元素

### **路由管理**
- 基于Next.js App Router
- 语言感知路由
- 动态路由生成

## 核心特性

### 实时聊天界面
- 流式响应处理
- 消息历史管理
- 多模态输入支持（文本、语音、图像）

### 配置管理
- 模型提供商配置
- 智能体行为自定义
- 知识库管理

### 响应式设计
- 移动优先方法
- 自适应布局
- 触摸友好交互

### 性能优化
- 服务器端渲染 (SSR)
- 静态站点生成 (SSG)
- 代码分割和懒加载
- 图像优化

## 开发工作流

### 设置
```bash
cd frontend
npm install
npm run dev
```

### 生产构建
```bash
npm run build
npm start
```

### 代码质量
- ESLint 代码检查
- Prettier 代码格式化
- TypeScript 类型安全
- Husky 预提交钩子

## 集成点

### 后端通信
- RESTful API 调用
- WebSocket 实时功能
- 身份验证和授权
- 错误处理和用户反馈

### 外部服务
- 模型提供商 API
- 文件上传和管理
- 语音处理集成
- 分析和监控

详细的开发指南和组件文档，请参阅 [开发者指南](../developer-guide/overview)。