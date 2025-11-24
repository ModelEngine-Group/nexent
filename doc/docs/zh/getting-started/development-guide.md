# Nexent 开发指南

本指南为开发者提供全面的信息，帮助理解并参与 Nexent 项目，涵盖架构、技术栈、开发环境搭建和最佳实践。

## 🏗️ 整体架构

```
nexent/
├── frontend/          # 前端应用 (Next.js + TypeScript)
├── backend/           # 后端服务 (FastAPI + Python)
├── sdk/              # Python SDK
├── docker/           # Docker 部署配置
├── make/             # 构建脚本
├── test/             # 测试代码
└── assets/           # 静态资源
```

## 🛠️ 技术栈

### 前端技术栈
- **框架**: Next.js 14 (App Router)
- **语言**: TypeScript
- **UI库**: React + Tailwind CSS
- **状态管理**: React Hooks
- **国际化**: react-i18next
- **HTTP客户端**: Fetch API

### 后端技术栈
- **框架**: FastAPI
- **语言**: Python 3.10+
- **数据库**: PostgreSQL + Redis + Elasticsearch
- **文件存储**: MinIO
- **任务队列**: Celery + Ray
- **AI框架**: smolagents
- **向量数据库**: Elasticsearch

### 部署技术栈
- **容器化**: Docker + Docker Compose
- **反向代理**: Nginx
- **监控**: 内置健康检查
- **日志**: 结构化日志

## 🚀 开发环境搭建

### 环境要求
- Python 3.10+
- Node.js 18+
- Docker & Docker Compose
- uv (Python 包管理器)
- pnpm (Node.js 包管理器)

### 基础设施部署
在开始后端开发之前，需要先部署基础设施服务。这些服务包括数据库、缓存、文件存储等核心组件。

```bash
# 在项目根目录的docker目录下执行
cd docker
./deploy.sh --mode infrastructure
```

::: info 重要说明
基础设施模式会启动 PostgreSQL、Redis、Elasticsearch 和 MinIO 服务。部署脚本会自动生成开发环境所需的密钥和环境变量，并保存到根目录的 `.env` 文件中。生成的密钥包括 MinIO 访问密钥和 Elasticsearch API 密钥。所有服务 URL 会配置为 localhost 地址，方便本地开发。
:::

### 后端设置
```bash
# 在项目根目录的backend目录下执行
cd backend
uv sync --all-extras
uv pip install ../sdk
```

::: tip 说明
`--all-extras` 会安装所有可选依赖，包括数据处理、测试等模块。然后安装本地 SDK 包。
:::

#### 使用国内镜像源（可选）
如果网络访问较慢，可以使用国内镜像源加速安装：

```bash
# 使用清华大学镜像源
uv sync --all-extras --default-index https://pypi.tuna.tsinghua.edu.cn/simple
uv pip install ../sdk --default-index https://pypi.tuna.tsinghua.edu.cn/simple

# 使用阿里云镜像源
uv sync --all-extras --default-index https://mirrors.aliyun.com/pypi/simple/
uv pip install ../sdk --default-index https://mirrors.aliyun.com/pypi/simple/

# 使用多个镜像源（推荐）
uv sync --all-extras --index https://pypi.tuna.tsinghua.edu.cn/simple --index https://mirrors.aliyun.com/pypi/simple/
uv pip install ../sdk --index https://pypi.tuna.tsinghua.edu.cn/simple --index https://mirrors.aliyun.com/pypi/simple/
```

::: info 镜像源说明
- **清华大学镜像源**: `https://pypi.tuna.tsinghua.edu.cn/simple`
- **阿里云镜像源**: `https://mirrors.aliyun.com/pypi/simple/`
- **中科大镜像源**: `https://pypi.mirrors.ustc.edu.cn/simple/`
- **豆瓣镜像源**: `https://pypi.douban.com/simple/`

推荐使用多个镜像源配置，以提高下载成功率。
:::

### 前端设置
```bash
# 在项目根目录的frontend目录下执行
cd frontend
pnpm install
pnpm run dev
```

### 服务启动
在启动服务之前，需要先激活虚拟环境：

```bash
# 在项目根目录的backend目录下执行
cd backend
source .venv/bin/activate  # 激活虚拟环境
```

::: warning 重要提示
Windows操作系统需执行`source .venv/Scripts/activate`命令激活虚拟环境。
:::

Nexent 包含三个核心后端服务，需要分别启动：

```bash
# 在项目根目录下执行，请按以下顺序执行：
source .env && python backend/mcp_service.py            # MCP 服务
source .env && python backend/data_process_service.py   # 数据处理服务
source .env && python backend/config_service.py         # 编辑态服务
source .env && python backend/runtime_service.py        # 运行态服务
```

::: warning 重要提示
所有服务必须在项目根目录下启动。每个 Python 命令前都需要先执行 `source .env` 来加载环境变量。确保基础设施服务（数据库、Redis、Elasticsearch、MinIO）已经启动并正常运行。
:::

## 🔧 开发模块指南

### 🎨 前端开发
- **技术栈**: Next.js 14 + TypeScript + React + Tailwind CSS
- **核心功能**: 用户界面、实时聊天、配置管理、国际化
- **详细信息**: 查看 [前端概览](../frontend/overview)

### 🔧 后端开发  
- **技术栈**: FastAPI + Python 3.10+ + PostgreSQL + Redis + Elasticsearch
- **核心功能**: API服务、智能体管理、数据处理、向量搜索
- **详细信息**: 查看 [后端概览](../backend/overview)

### 🤖 AI 智能体开发
- **框架**: 基于 smolagents 的企业级智能体框架
- **核心功能**: 智能体创建、工具集成、推理执行、多模态支持
- **自定义智能体**: 查看 [智能体模块](../sdk/core/agents)
- **系统提示词**: 位于 `backend/prompts/`
- **实现步骤**: 创建实例 → 配置工具 → 设置提示词 → 测试运行
- **详细信息**: 查看 [智能体模块](../sdk/core/agents)

### 🛠️ 工具开发
- **MCP 工具系统**: 基于 Model Context Protocol
- **开发流程**: 实现逻辑 → 注册工具 → 重启服务
- **协议遵循**: 工具开发需遵循 MCP 协议
- **详细规范**: 查看 [工具开发指南](../sdk/core/tools)

### 📦 SDK 开发工具包
- **功能**: 提供完整的AI代理、模型调用、工具集成接口
- **模块**: 核心代理、数据处理、向量数据库
- **详细信息**: 查看 [SDK 概览](../sdk/overview)

### 📊 数据处理
- **文件处理**: 支持 20+ 种格式
- **分块策略**: basic、by_title、none
- **流式处理**: 大文件内存优化
- **详细信息**: 查看 [数据处理指南](../sdk/data-process)

## 🏗️ 构建与部署

### Docker 构建
详细的构建指南请参考 [Docker 构建指南](../deployment/docker-build)

## 📋 开发最佳实践与注意事项

### 代码质量
1. **测试驱动**: 编写单元测试和集成测试
2. **代码审查**: 遵循团队代码规范
3. **文档更新**: 及时更新相关文档
4. **错误处理**: 完善的异常处理和日志记录

### 性能优化
1. **异步处理**: 使用异步架构提升性能
2. **缓存策略**: 合理使用缓存机制
3. **资源管理**: 注意内存和连接池管理
4. **监控调试**: 使用性能监控工具

### 安全考虑
1. **输入验证**: 严格验证所有输入参数
2. **权限控制**: 实现适当的访问控制
3. **敏感信息**: 妥善处理API密钥等敏感数据
4. **安全更新**: 定期更新依赖和安全补丁

### 重要开发注意事项
1. **服务依赖**: 确保所有服务都已启动后再测试
2. **代码修改**: 修改代码后需重启相关服务
3. **开发模式**: 开发环境建议用调试模式
4. **提示词测试**: 系统提示词需充分测试
5. **环境变量**: 确保 `.env` 文件中的配置正确
6. **基础设施**: 开发前确保基础设施服务正常运行

## 💡 获取帮助

### 文档资源
- [安装部署](./installation.md) - 环境搭建和部署
- [常见问题](./faq) - 常见问题解答
- [用户指南](../user-guide/home-page) - Nexent使用指南

### 社区支持
- [Discord 社区](https://discord.gg/tb5H3S3wyv) - 实时交流和支持
- [GitHub Issues](https://github.com/ModelEngine-Group/nexent/issues) - 问题报告和功能请求
