# 后端架构概览

Nexent 的后端采用 FastAPI 和 Python 构建，为 AI 智能体服务提供强大且可扩展的 API 平台。

## 技术栈

- **框架**: FastAPI
- **语言**: Python 3.10+
- **数据库**: PostgreSQL + Redis + Elasticsearch
- **文件存储**: MinIO
- **任务队列**: Celery + Ray
- **AI框架**: smolagents
- **向量数据库**: Elasticsearch

## 目录结构

```
backend/
├── apps/                         # API应用层
│   ├── base_app.py              # FastAPI主应用
│   ├── agent_app.py             # 代理相关API
│   ├── conversation_management_app.py # 对话管理API
│   ├── file_management_app.py   # 文件管理API
│   ├── knowledge_app.py         # 知识库API
│   ├── model_managment_app.py   # 模型管理API
│   ├── config_sync_app.py       # 配置同步API
│   └── voice_app.py             # 语音相关API
├── services/                     # 业务服务层
│   ├── agent_service.py         # 代理业务逻辑
│   ├── conversation_management_service.py # 对话管理
│   ├── vectordatabase_service.py # 搜索引擎服务
│   ├── model_health_service.py  # 模型健康检查
│   ├── prompt_service.py        # 提示词服务
│   └── tenant_config_service.py # 租户配置服务
├── database/                     # 数据访问层
│   ├── client.py                # 数据库连接
│   ├── db_models.py             # 数据库模型
│   ├── agent_db.py              # 代理数据操作
│   ├── conversation_db.py       # 对话数据操作
│   ├── knowledge_db.py          # 知识库数据操作
│   └── tenant_config_db.py      # 租户配置数据操作
├── agents/                       # 代理核心逻辑
│   ├── agent_run_manager.py     # 代理运行管理器
│   ├── create_agent_info.py     # 代理信息创建
│   └── default_agents/          # 默认代理配置
├── data_process/                 # 数据处理模块
│   ├── app.py                   # 数据处理应用
│   ├── config.py                # 数据处理配置
│   ├── tasks.py                 # 数据处理任务
│   ├── worker.py                # 数据处理工作器
│   └── utils.py                 # 数据处理工具
├── utils/                        # 工具类
│   ├── auth_utils.py            # 认证工具
│   ├── config_utils.py          # 配置工具
│   ├── file_management_utils.py # 文件管理工具
│   ├── logging_utils.py         # 日志工具
│   └── thread_utils.py          # 线程工具
├── consts/                       # 常量定义
│   ├── const.py                 # 系统常量
│   └── model.py                 # 数据模型
├── prompts/                      # 提示词模板
│   ├── knowledge_summary_agent.yaml # 知识库摘要代理
│   ├── manager_system_prompt_template.yaml # 管理器系统提示词
│   └── utils/                   # 提示词工具
├── sql/                         # SQL脚本
├── assets/                      # 后端资源文件
├── config_service.py            # 编辑态服务入口
├── runtime_service.py           # 运行态服务入口
├── data_process_service.py      # 数据处理服务入口
└── requirements.txt             # Python依赖
```

## 架构职责

### **应用层 (apps)**
- API路由定义
- 请求参数验证
- 响应格式化
- 身份验证和授权

### **服务层 (services)**
- 核心业务逻辑实现
- 数据处理和转换
- 外部服务集成
- 业务规则执行

### **数据层 (database)**
- 数据库操作和ORM模型
- 数据访问接口
- 事务管理
- 数据一致性和完整性

### **代理层 (agents)**
- AI代理核心逻辑和执行
- 工具调用和集成
- 推理和决策制定
- 代理生命周期管理

### **工具层 (utils)**
- 通用工具函数
- 配置管理
- 日志和监控
- 线程和进程管理

## 核心服务

### 代理管理
- 代理创建和配置
- 执行生命周期管理
- 工具集成和调用
- 性能监控

### 对话管理
- 消息处理和存储
- 上下文管理
- 历史记录跟踪
- 多租户支持

### 知识库
- 文档处理和索引
- 向量搜索和检索
- 内容摘要
- 知识图谱构建

### 文件管理
- 多格式文件处理
- MinIO存储集成
- 批处理能力
- 元数据提取

### 模型集成
- 多模型提供商支持
- 健康监控和故障转移
- 负载均衡和缓存
- 性能优化

## 数据流架构

### 1. 用户请求流程
```
用户输入 → 前端验证 → API调用 → 后端路由 → 业务服务 → 数据访问 → 数据库
```

### 2. AI Agent执行流程
```
用户消息 → Agent创建 → 工具调用 → 模型推理 → 流式响应 → 结果保存
```

### 3. 知识库文件处理流程
```
文件上传 → 临时存储 → 数据处理 → 向量化 → 知识库存储 → 索引更新
```

### 4. 实时文件处理流程
```
文件上传 → 临时存储 → 数据处理 → Agent → 回答
```

## 部署架构

### 容器服务
- **nexent**: 后端服务 (端口 5010)
- **nexent-data-process**: 数据处理服务 (端口 5012)
- **nexent-postgresql**: 数据库 (端口 5434)
- **nexent-elasticsearch**: 搜索引擎 (端口 9210)
- **nexent-minio**: 对象存储 (端口 9010)
- **redis**: 缓存服务 (端口 6379)

### 可选服务
- **nexent-openssh-server**: 终端工具的SSH服务器 (端口 2222)

## 开发设置

### 环境搭建
```bash
cd backend
uv sync && uv pip install -e ../sdk
```

### 服务启动
```bash
python backend/data_process_service.py   # 数据处理服务
python backend/config_service.py      # 编辑态服务
python backend/runtime_service.py        # 运行态服务
python backend/mcp_service.py     # MCP服务
```

## 性能和可扩展性

### 异步架构
- 基于asyncio的高性能异步处理
- 线程安全的并发处理机制
- 针对分布式任务队列优化

### 缓存策略
- 多层缓存提升响应速度
- Redis用于会话和临时数据
- Elasticsearch用于搜索结果缓存

### 负载均衡
- 智能并发限制
- 资源池管理
- 自动扩展能力

详细的后端开发指南，请参阅 [开发者指南](../developer-guide/overview)。