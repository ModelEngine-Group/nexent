# Nexent Dev Container 使用指南

## 1. 环境说明

此开发容器配置了一个完整的 Nexent 开发环境，包含以下组件：

- 主要开发容器 (`nexent-dev`)：基于 nexent/nexent 镜像，添加了开发工具
- 服务容器：
  - Elasticsearch (`nexent-elasticsearch`)
  - PostgreSQL (`nexent-postgresql`)
  - MinIO (`nexent-minio`)
  - Nexent 后端 (`nexent`)
  - Nexent 前端 (`nexent-web`)
  - 数据处理服务 (`nexent-data-process`)

## 2. 使用步骤

### 2.1 准备工作

1. 安装 Cursor
02. 安装 Dev Containers 插件 (`anysphere.remote-containers` 与 `anysphere.remote-sshRemote`)
3. 确保 Docker 和 Docker Compose 已安装并运行

### 2.2 使用 Dev Container 启动项目

1. 克隆项目到本地
2. 在 Cursor 中打开项目文件夹
3. 运行 `docker/deploy.sh` 脚本，在`infrastructure` 模式下启动容器
4. 进入 `nexent-minio` 与 `nexent-elasticsearch` 容器, 将 `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `ELASTICSEARCH_API_KEY` 环境变量复制到 `docker/docker-compose.dev.yml` 中的相应环境变量位置
5. 按下 `F1` 或 `Ctrl+Shift+P`，输入 `Dev Containers: Reopen in Container ...`
6. Cursor 将根据 `.devcontainer` 目录中的配置启动开发容器

### 2.3 开发工作流

1. 容器启动后，Cursor 会自动连接到开发容器
2. 所有文件编辑都在容器内完成
3. 进行开发、测试，修改完成后可以直接在容器内构建和运行
4. 可以直接在容器内进行 git 的变更管理，如使用 `git commit` 或 `git push`；但不建议在容器内拉取远程代码，容易导致路径问题

## 3. 端口映射

以下端口已在 devcontainer.json 中配置了映射：

- 3000: Nexent Web 界面
- 5010: Nexent 后端服务
- 5012: 数据处理服务
- 9010: MinIO API
- 9011: MinIO 控制台
- 9210: Elasticsearch API
- 5434: PostgreSQL

## 4. 自定义开发环境

您可以通过修改以下文件来自定义开发环境：

- `.devcontainer/devcontainer.json` - 插件配置项
- `docker/docker-compose.dev.yml` - 开发容器的具体构筑项，需要修改环境变量值才能正常启动

## 6. 常见问题解决

### 🔐 权限问题
如果遇到权限问题，可能需要在容器内运行：

```bash
sudo chown -R $(id -u):$(id -g) /opt
```

如果容器启动失败，可以尝试：

1. 重建容器：按下 `F1` 或 `Ctrl+Shift+P`，输入 `Dev Containers: Rebuild Container`
2. 检查 Docker 日志：`docker logs nexent-dev`
3. 检查 `.env` 文件中的配置是否正确

### 🌐 网络连接问题
- **Q: Docker 容器如何访问宿主机上部署的模型（如 Ollama）？**
  - A: 由于容器内的 `localhost` 指向容器自身，需要通过以下方式连接宿主机服务：
  
    **方案一：使用Docker特殊DNS名称 host.docker.internal**  
    适用场景：Mac/Windows和较新版本的Docker Desktop(Linux版本也支持)  
      ```bash
      http://host.docker.internal:11434/v1
      ```
    **方案二：使用宿主机真实 IP（需确保防火墙放行）**
    ```bash
    http://[宿主机IP]:11434/v1
    ```
    **方案三：修改Docker Compose配置**  
    在docker-compose.yaml中添加：
    ```yaml
    extra_hosts:
      - "host.docker.internal:host-gateway"
    ```
