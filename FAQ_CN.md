# Nexent 常见问题 🤔

[![English](https://img.shields.io/badge/English-FAQ-blue)](FAQ.md)
[![中文](https://img.shields.io/badge/中文-FAQ-green)](FAQ_CN.md)

本常见问题解答主要针对安装和部署 Nexent 过程中可能遇到的问题。如需了解基本安装步骤，请参考 README 中的[快速开始指南](../README_CN.md#-先来试试看)。

## 🚀 安装与设置

### 🔑 Jina API 密钥
- **Q: 如何获取用于嵌入模型的 Jina API 密钥？**
  - A: 要使用基于 Jina 的嵌入模型，您需要：
    1. 访问 [Jina AI 官网](https://jina.ai/)，无需注册
    3. 进入 Embedding 部分页面获取您的 API 密钥
    4. 将 API 密钥添加到页面中

## 🚫 常见错误与运维方式

### 🌐 端口冲突
- **Q: 端口 3000 已被占用，如何修改？**
  - A: 可以在 Docker Compose 配置文件中修改端口。

### 📦 容器问题
- **Q: 如何查看容器日志？**
  - A: 使用 `docker logs <容器名称>` 命令查看特定容器的日志。

### 🔢 Embedding模型问题
- **Q: 为什么我的Embedding模型无法连通？**
  - A: 创建模型填写模型URL时，注意添加 `/v1/embeddings` 后缀。完整示例如 `https://model.provider.com/v1/embeddings`

### 📧 邮件工具配置
- **Q: 如何启用和配置邮件工具？**
  - A: 我们团队已经预制实现了基于 IMAP 和 SMTP 的邮件工具。要启用它们：
    1. 在 `.env` 文件中配置邮件参数
    2. 在 `agent_utils.py` 中取消邮件工具相关的注释
    3. 切换到支持邮件的系统提示词 `code_agent_with_email.yaml`
    4. 重启 MCP 服务使更改生效

## ❓ 需要更多帮助？

如果这里没有找到您的问题答案：
- 加入我们的 [Discord 社区](https://discord.gg/tb5H3S3wyv) 获取实时支持
- 查看我们的 [GitHub Issues](https://github.com/ModelEngine-Group/nexent/issues) 寻找类似问题
- 参考我们的[贡献指南](CONTRIBUTING_CN.md)获取更详细的信息 