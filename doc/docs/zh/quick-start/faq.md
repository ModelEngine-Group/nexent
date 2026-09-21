# Nexent 常见问题

本常见问题解答主要针对安装和使用 Nexent 过程中可能遇到的问题。如需了解基本安装步骤，请参考[安装部署](./installation)。如需了解基本使用指导，请参考[用户指南](../user-guide/home-page)。

## 🚫 常见错误与运维方式

### 🌐 网络连接问题
- **Q: Docker 容器如何访问宿主机上部署的模型（如 Ollama）？**
  - A: 由于容器内的 `localhost` 指向容器自身，需要通过以下方式连接宿主机服务：
  
    **方案一：使用 Docker 特殊 DNS 名称 `host.docker.internal`**

    适用场景：macOS、Windows，以及已配置该名称的 Linux Docker 环境。

      ```bash
      http://host.docker.internal:11434/v1
      ```
    **方案二：使用宿主机真实 IP（需确保防火墙放行）**
    ```bash
    http://[宿主机IP]:11434/v1
    ```
    **方案三：配置 Docker Compose**

    在对应服务中添加：
    ```yaml
    extra_hosts:
      - "host.docker.internal:host-gateway"
    ```

### 🔌 端口冲突
- **Q: 端口 3000 已被占用，如何修改？**
  - A: 可以在 Docker Compose 配置文件中修改端口。

### 📦 容器问题
- **Q: 如何查看容器日志？**
  - A: 使用 `docker logs <容器名称>` 命令查看特定容器的日志。

- **Q: 智能体运行时报错，提示无法创建沙箱，如何排查？**
  - A: 依次检查以下项目：
    1. Docker 服务是否正常运行。
    2. Runtime 是否能够只读访问 `/var/run/docker.sock`。
    3. `deploy/env/.env` 中 `NEXENT_SANDBOX_DOCKER_IMAGE` 指定的镜像是否已拉取。
    4. `NEXENT_SANDBOX_WORKSPACE_VOLUME` 指定的工作区卷是否存在。
    5. 沙箱资源限制是否超过当前主机可用资源。

    Docker 部署可使用以下命令检查默认资源：

    ```bash
    docker images nexent/nexent-sandbox
    docker volume inspect nexent-agent-workspace
    docker logs nexent-runtime --tail 100
    ```

## 🔍 故障排除

### 🔢 模型连接问题

- **Q: 为什么我的模型无法连接？**
  - A: 请检查以下项目：
    1. **正确的 API 端点**: 确保您使用正确的 base URL
    2. **有效的 API 密钥**: 验证您的 API 密钥具有适当权限
    3. **模型名称**: 确认模型标识符正确
    4. **网络访问**: 确保您的部署可以访问提供商的服务器
    关于如何配置模型，请参阅用户指南中的 [模型配置](../user-guide/agent-development/model-configuration)。

- **Q: 模型服务提示消息格式不兼容，如何解决？**
  - A: 不同提供商对 OpenAI 消息格式的兼容程度不同。有些纯文本接口只接受字符串 `content`，不接受由多个内容块组成的数组。请先确认模型类型和 API 地址配置正确，再查阅提供商的协议说明。例如，多模态消息可能使用：

  ```python
  { "role":"user", "content":[ { "type":"text", "text":"prompt" } ] }
  ```

  纯文本接口可能只接受：

  ```python
  { "role":"user", "content":"prompt" }
  ```

  如果提供商不支持当前消息格式，请改用兼容 OpenAI 多模态消息的接口，或将该模型配置为对应的纯文本模型类型。

## 🐛 已知问题

本节列出了当前版本 Nexent 中的已知问题和限制。我们正在积极修复这些问题，并会随着解决方案的推出更新本节。

### 🔧 OpenSSH 容器软件安装限制

**问题描述**：OpenSSH 终端容器和智能体沙箱都是受控执行环境，不建议在运行时安装系统软件包。沙箱镜像已经包含常用的数据处理和文档生成依赖，但不保证包含所有第三方软件。

**状态**：属于运行环境的安全限制。

**影响**：依赖额外系统包或需要管理员权限的脚本可能无法直接运行。

**解决方式**：将依赖预先加入自定义终端或沙箱镜像，并在部署配置中使用该镜像。不要在生产运行期间临时修改容器。

## 📝 问题报告

如果您遇到此处未列出的任何问题，请：

1. **搜索现有问题** 在 [GitHub Issues](https://github.com/ModelEngine-Group/nexent/issues)
2. **创建新问题** 并提供详细信息，包括：
   - 重现步骤
   - 预期行为
   - 实际行为
   - 系统信息
   - 日志文件（如适用）

## 💡 需要帮助

如果这里没有找到您的问题答案：
- 加入我们的 [Discord 社区](https://discord.gg/tb5H3S3wyv) 获取实时支持
- 查看我们的 [GitHub Issues](https://github.com/ModelEngine-Group/nexent/issues) 寻找类似问题
- 在 [GitHub Discussions](https://github.com/ModelEngine-Group/nexent/discussions) 开启讨论
