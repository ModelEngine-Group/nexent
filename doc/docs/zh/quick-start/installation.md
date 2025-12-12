# 安装部署

## 🎯 系统要求

| 资源 | 最低要求 |
|----------|---------|
| **CPU**  | 2 核 |
| **内存**  | 6 GiB   |
| **架构** | x86_64 / ARM64 |
| **软件** | 已安装 Docker 和 Docker Compose |

## 🚀 快速开始

### 1. 下载和设置

```bash
git clone https://github.com/ModelEngine-Group/nexent.git
cd nexent/docker
cp .env.example .env # 复制环境变量配置文件
```

> **💡 提示**: 若无特殊需求，您可直接使用 `.env.example` 进行部署，无需进行任何修改。若您需要配置语音模型（STT/TTS），则需要在 `.env` 中配置相关参数。我们会尽快将此部分配置前端化，敬请期待。

### 2. 部署选项

运行以下命令开始部署：

```bash
bash deploy.sh
```

执行此命令后，系统会提供两个不同的版本供您选择：

**版本选择:**
- **Speed version（轻量快速部署，默认）**: 快速启动核心功能，适合个人用户和小团队使用
- **Full version（完整功能版）**: 提供企业级租户管理和资源隔离等高级功能，但安装时间略长，适合企业用户

**部署模式:**
- **开发模式 (默认)**: 暴露所有服务端口以便调试
- **基础设施模式**: 仅启动基础设施服务
- **生产模式**: 为安全起见仅暴露端口 3000

**可选组件:**
- **终端工具**: 启用 openssh-server 供 AI 智能体执行 shell 命令
- **区域优化**: 中国大陆用户可使用优化的镜像源

### 3. 访问您的安装

部署成功完成后：
1. 在浏览器中打开 **http://localhost:3000**
2. 参考 [用户指南](../user-guide/home-page) 进行智能体的开发


## 📦 服务架构

Nexent 采用微服务架构，包含以下核心服务：

**核心服务:**
- `nexent`: 后端服务 (端口 5010)
- `nexent-web`: 前端界面 (端口 3000)
- `nexent-data-process`: 数据处理服务 (端口 5012)

**基础设施服务:**
- `nexent-postgresql`: 数据库 (端口 5434)
- `nexent-elasticsearch`: 搜索引擎 (端口 9210)
- `nexent-minio`: 对象存储 (端口 9010，控制台 9011)
- `redis`: 缓存服务 (端口 6379)

**可选服务:**
- `nexent-openssh-server`: 终端工具的 SSH 服务器 (端口 2222)

## 🔌 端口映射

| 服务 | 内部端口 | 外部端口 | 描述 |
|---------|---------------|---------------|-------------|
| Web 界面 | 3000 | 3000 | 主应用程序访问 |
| 后端 API | 5010 | 5010 | 后端服务 |
| 数据处理 | 5012 | 5012 | 数据处理 API |
| PostgreSQL | 5432 | 5434 | 数据库连接 |
| Elasticsearch | 9200 | 9210 | 搜索引擎 API |
| MinIO API | 9000 | 9010 | 对象存储 API |
| MinIO 控制台 | 9001 | 9011 | 存储管理 UI |
| Redis | 6379 | 6379 | 缓存服务 |
| SSH 服务器 | 22 | 2222 | 终端工具访问 |

有关完整的端口映射详细信息，请参阅我们的 [开发容器指南](../deployment/devcontainer.md#port-mapping)。

## 💡 需要帮助

- 浏览 [常见问题](./faq) 了解常见安装问题
- 在我们的 [Discord 社区](https://discord.gg/tb5H3S3wyv) 提问
- 在 [GitHub Issues](https://github.com/ModelEngine-Group/nexent/issues) 中提交错误报告或功能建议

## 🔧 从源码构建

想要从源码构建或添加新功能？查看 [Docker 构建指南](../deployment/docker-build) 获取详细说明。

有关详细的安装说明和自定义选项，请查看我们的 [开发者指南](../developer-guide/overview)。