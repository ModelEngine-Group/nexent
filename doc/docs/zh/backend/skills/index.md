# 后端技能（Skill）文档

本节介绍 Nexent 后端基础设施中 Skills 技能系统的完整生态，包括技能定义、技能包结构与系统架构。

## 可用文档

### 概览与架构
- [技能系统概览](./overview)：技能类型、生命周期与版本管理

## 技能与工具的关系

在 Nexent 中，**工具（Tool）** 与 **技能（Skill）** 是两个不同层次的概念：

- **工具**：智能体可调用的单个原子操作。启用后，LLM 的每次思考都会在工具列表中搜索——即使本次对话完全不需要某个工具，LLM 仍然会消耗上下文额度。
- **技能**：通过 `SKILL.md` 将多个工具的能力组合为一个完整的工作流，并附带参数配置与使用文档。LLM 根据用户实际需求自行判断是否激活技能，激活后才加载对应工具集——有效节省 Token 消耗。

## 快速开始

1. **了解能力**：阅读 [技能系统概览](./overview) 了解已支持的技能类型
2. **体验创建**：在 [技能管理](../../user-guide/skills) 页面体验 NL-to-Skill 创建
3. **手动创建**：上传 `SKILL.md` 或 ZIP 包创建自定义技能
4. **为智能体配置**：在智能体工具配置中勾选技能

## 相关参考

- [技能管理（用户指南）](../../user-guide/skills)
- [智能体开发指南](../../user-guide/agent-development)
- [本地工具概览](../../user-guide/local-tools/index)
- [SDK 工具开发规范](../../sdk/core/tools)
- [MCP 工具开发](../tools/mcp)
- [常见问题](../../quick-start/faq)

## 获取帮助

- 查看 [常见问题](../../quick-start/faq) 了解常见技能使用问题
- 在 [GitHub Discussions](https://github.com/ModelEngine-Group/nexent/discussions) 中提问
- 查看 [GitHub Issues](https://github.com/ModelEngine-Group/nexent/issues) 了解已知问题
