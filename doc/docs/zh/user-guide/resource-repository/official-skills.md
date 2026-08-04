---
title: 官方技能
---

# 官方技能

Nexent 在 `official-skills-zip` 目录中提供了一组可直接安装的官方技能。安装后，您可以在智能体的技能配置中启用对应能力，并按需填写技能参数。

## 技能列表

### 文件操作

| 技能名称 | 能力说明 |
| --- | --- |
| `read-file` | 读取工作空间内文件的内容与元信息 |
| `create-file-directory` | 创建文件或目录 |
| `delete-file-directory` | 删除文件或目录 |
| `move-file-directory` | 移动或重命名文件或目录 |
| `list-directory` | 以树形结构列出目录内容 |
| [`create-docx`](./create-docx.md) | 根据内容生成 Word 文档并返回可下载的文件产物 |

### 知识库搜索

| 技能名称 | 能力说明 |
| --- | --- |
| `search-knowledge-base` | 搜索 Nexent 本地知识库，支持 hybrid、accurate 和 semantic 模式 |
| `search-dify` | 搜索 Dify 知识库 |
| `search-idata` | 搜索 iData 知识库 |
| `search-datamate` | 搜索 DataMate 知识库，支持相似度阈值控制 |

### 公网搜索

| 技能名称 | 能力说明 |
| --- | --- |
| `search-web-tavily` | 使用 Tavily 进行公网实时搜索 |
| `search-web-linkup` | 使用 Linkup 进行图文混合搜索 |
| `search-web-exa` | 使用 Exa 进行深度网页搜索 |

### 多模态分析

| 技能名称 | 能力说明 |
| --- | --- |
| `analyze-image` | 基于视觉语言模型分析图片内容并进行问答 |
| `analyze-text-file` | 提取并分析 PDF、Word、Excel 等文件内容 |

### 通信与远程操作

| 技能名称 | 能力说明 |
| --- | --- |
| `email-utils` | 通过 IMAP 收取邮件、通过 SMTP 发送邮件，支持 HTML、CC 和 BCC |
| `run-shell-ssh` | 建立持久化 SSH 会话并在远程主机执行命令 |

## 安装与使用

1. 打开 **资源仓库** 中的 **Skill 仓库**。
2. 进入官方技能安装入口，查看当前 `official-skills-zip` 中可用的技能。
3. 选择需要的技能并完成安装。
4. 在智能体配置的技能列表中启用已安装技能。
5. 根据技能要求填写参数并保存配置。

官方技能的具体参数和调用约束以对应技能包中的 `SKILL.md` 为准。文件生成类技能的使用方式请参阅 [文件生成技能指南](../../backend/skills/file-generation-guide.md)。

## 相关文档

- [Skill 仓库](./skill-repository.md)
- [技能系统概览](../../backend/skills/overview.md)
- [智能体配置](../agent-development/agent-configuration.md)
