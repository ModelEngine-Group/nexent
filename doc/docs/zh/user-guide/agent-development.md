# 智能体开发

在智能体开发页面中，您可以通过自然语言生成或手动配置智能体，并在同一页面完成调试、发布和版本管理。智能体可以组合模型、工具、Skill、知识库和协作 Agent 来完成任务。

## 快速导航

本模块包含以下四个配置页面，帮助您全方位配置智能体：

| 页面 | 说明 |
|------|------|
| [模型配置](./agent-development/model-configuration) | 接入和管理 AI 模型，包括大语言模型、向量化模型、视觉语言模型、重排模型以及语音模型（语音合成与语音识别） |
| [知识库配置](./agent-development/knowledge-configuration) | 创建知识库、查看个人容量、处理文档和管理 Chunk，让智能体检索私有数据 |
| [记忆配置](./agent-development/memory-configuration) | 管理 Tenant、User、Agent 三层记忆，并通过 Dreaming 将稳定的短期记忆整理为长期记忆 |
| [智能体配置](./agent-development/agent-configuration) | 使用智能生成完成整套配置或局部优化，也可以手动调整参数，并完成资源绑定、调试、发布和版本管理 |
| [添加外部 A2A Agent](./agent-development/a2a-external) | 通过 URL 或 Nacos 发现第三方 Agent，并将其用于智能体协作 |
| [发布为 A2A Agent](./agent-development/a2a-publish) | 将已发布的智能体开放给外部系统发现和调用 |

## 主要步骤

1. **配置模型** - 在模型管理中接入所需的 AI 模型
2. **准备知识库** - 创建知识库，上传文档并确认文档状态为“已就绪”
3. **配置记忆** - 开启记忆能力，并按需设置 Dreaming 计划
4. **开发智能体** - 描述业务需求，让系统推荐资源并生成配置，或手动填写各项参数
5. **调试与发布** - 验证提示词、工具和协作流程，确认无误后发布版本
