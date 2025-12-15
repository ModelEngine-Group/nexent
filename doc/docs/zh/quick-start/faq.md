# Nexent 常见问题

本常见问题解答主要针对安装和使用 Nexent 过程中可能遇到的问题。如需了解基本安装步骤，请参考[安装部署](./installation)。如需了解基本使用指导，请参考[用户指南](../user-guide/home-page)。

## 🚫 常见错误与运维方式

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

### 🔌 端口冲突
- **Q: 端口 3000 已被占用，如何修改？**
  - A: 可以在 Docker Compose 配置文件中修改端口。

### 📦 容器问题
- **Q: 如何查看容器日志？**
  - A: 使用 `docker logs <容器名称>` 命令查看特定容器的日志。

## 🔍 故障排除

### 🔢 模型连接问题

- **Q: 为什么我的模型无法连接？**
  - A: 请检查以下项目：
    1. **正确的 API 端点**: 确保您使用正确的 base URL
    2. **有效的 API 密钥**: 验证您的 API 密钥具有适当权限
    3. **模型名称**: 确认模型标识符正确
    4. **网络访问**: 确保您的部署可以访问提供商的服务器
    关于如何配置模型，请参阅用户指南中的 [模型管理](../user-guide/model-management)。

- **Q: 接入 DeepSeek 官方 API 时多轮对话会报错，如何解决？**
  - A: DeepSeek 官方当前仅支持文本对话接口，而 Nexent 的推理流程面向多模态设计。在多轮对话中，官方 API 无法正确接收多模态格式数据，因此会触发错误。建议改用硅基流动等已对 DeepSeek 系列模型完成多模态适配的供应商，既保持 DeepSeek 模型的体验，又能兼容 Nexent 的多模态调用链。具体来说，我们使用的消息体形如：
  ```python
  { "role":"user", "content":[ { "type":"text", "text":"prompt" } ] }
  ```
  而DeepSeek只接收：
  ```python
  { "role":"user", "content":"prompt" }

## 🐛 已知问题

本节列出了当前版本 Nexent 中的已知问题和限制。我们正在积极修复这些问题，并会随着解决方案的推出更新本节。

### 🔧 OpenSSH 容器软件安装限制

**问题描述**: 在 OpenSSH 容器中为终端工具使用安装其他软件包目前由于容器限制而比较困难。

**状态**: 开发中

**影响**: 需要在终端环境中使用自定义工具或软件包的用户可能面临限制。

**计划解决方案**: 我们正在努力提供改进的容器和文档，使自定义变得更容易。这将包括更好的包管理和更灵活的容器配置。

**预期时间线**: 改进的容器支持计划在即将发布的版本中提供。

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