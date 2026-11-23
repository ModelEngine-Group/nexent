# Nexent Dev Container 使用指南

## 1. 环境说明

此开发容器配置了一个完整的 Nexent 开发环境，包含以下组件：

- 主要开发容器 (`nexent-data-process`)：基于 nexent/nexent-data-process 镜像，仓库代码挂载到容器内 `/opt` 目录，并预置 Python 开发环境
- 服务容器（通过 `bash deploy.sh docker` 部署的基础设施与应用服务）：
  - Elasticsearch (`nexent-elasticsearch`)
  - PostgreSQL (`nexent-postgresql`)
  - MinIO (`nexent-minio`)
  - 后端 Config 服务 (`nexent-config`)
  - Web 前端 (`nexent-web`)
  - 数据处理服务 (`nexent-data-process`)

## 2. 使用步骤

### 2.1 准备工作

1. 安装 Cursor
2. 安装 Dev Containers 插件 (`anysphere.remote-containers`)
3. 确保 Docker 和 Docker Compose 已安装并运行

### 2.2 使用 Dev Container 启动项目

1. 克隆项目到本地
2. 在 Cursor 中打开项目文件夹
3. 在项目根目录运行 `bash deploy.sh docker --components infrastructure,application,data-process,supabase --port-policy development` 启动基础容器
4. 部署脚本会把生成的 `MINIO_ACCESS_KEY`、`MINIO_SECRET_KEY`、`ELASTICSEARCH_API_KEY` 等变量写回 `deploy/env/.env`，`deploy/docker/compose/docker-compose.dev.yml` 中的服务通过 `env_file` 自动加载这些配置，无需手动复制
5. 按下 `F1` 或 `Ctrl+Shift+P`，输入 `Dev Containers: Reopen in Container ...`
6. Cursor 将根据 `.devcontainer` 目录中的配置启动开发容器

### 2.3 开发工作流

1. 容器启动后，Cursor 会自动连接到开发容器
2. 所有文件编辑都在容器内完成
3. 进行开发、测试，修改完成后可以直接在容器内构建和运行
4. 可以直接在容器内进行 git 的变更管理，如使用 `git commit` 或 `git push`；但不建议在容器内拉取远程代码，容易导致路径问题

## 3. 端口映射

`.devcontainer/devcontainer.json` 中通过 `forwardPorts` 转发了以下端口：

- 3000: Nexent Web 界面
- 5012: 数据处理服务

其余服务端口（后端 Config 服务 5010、PostgreSQL 5434、MinIO API 9010、MinIO 控制台 9011、Elasticsearch API 9210 等）由 development 端口策略下的 Docker Compose 直接发布在宿主机上，可从宿主机直接访问。

## 4. 自定义开发环境

您可以通过修改以下文件来自定义开发环境：

- `.devcontainer/devcontainer.json` - 插件配置项
- `deploy/docker/compose/docker-compose.dev.yml` - 开发容器的具体构筑项，需要修改环境变量值才能正常启动

## 5. 常见问题解决

如果遇到权限问题，可能需要在容器内运行：

```bash
sudo chown -R $(id -u):$(id -g) /opt
```

如果容器启动失败，可以尝试：

1. 重建容器：按下 `F1` 或 `Ctrl+Shift+P`，输入 `Dev Containers: Rebuild Container`
2. 检查 Docker 日志：`docker logs nexent-data-process`
3. 检查 `.env` 文件中的配置是否正确
