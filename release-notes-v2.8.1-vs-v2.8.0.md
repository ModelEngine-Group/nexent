# 🚀 Nexent：开源智能体平台 / Nexent: Open Source Intelligent Agent Platform

我们很高兴地宣布Nexent v2.8.1 正式发布！🎉

Nexent 是一个开源智能体平台，能够将流程的自然语言转化为完整的多模态智能体 —— 无需编排，无需复杂拖拉拽。基于 MCP 工具生态，Nexent 提供强大的模型集成、数据处理、知识库管理、零代码智能体开发能力。我们的目标很简单：将数据、模型和工具整合到一个智能中心中，使日常工作流程更智能、更互联。

We are excited to announce that Nexent v2.8.1 is released! 🎉

Nexent is an open-source agent platform that turns process-level natural language into complete multimodal agents — no diagrams, no wiring. Built on the MCP tool ecosystem, Nexent provides model integration, data processing, knowledge-base management, and zero-code agent development. Our goal is simple: to bring data, models, and tools together in one smart hub, making daily workflows smarter and more connected.

---

## Bug 修复 / Bug Fixes

- 修复智能体对话历史在长会话下加载缓慢、滚动卡顿的问题，改为按分组分页并在滚动时按需续取。 / Fixed slow loading and scroll lag in long agent conversation history by paginating by group and fetching on demand while scrolling.
- 修复 SSE 连接中断后对话无法继续的问题，断线后可正常恢复后续回复。 / Fixed conversations getting stuck after an SSE disconnect; replies now resume correctly once the stream recovers.
- 修复外部 A2A 智能体名称含特殊字符时，智能体调用名称校验不通过的问题。 / Fixed agent invocation name validation rejecting externally registered A2A agents whose names contain special characters.
- 修复智能体编辑页未沿用已配置默认模型、需要每次手动重选的问题。 / Fixed the agent editor not carrying over the configured default model, which forced a manual reselect every time.
- 修复智能体空间标签缺失、卡片信息层级与操作入口不一致的问题。 / Fixed missing tags in Agent Space and inconsistent information hierarchy and actions on agent cards.
- 修复智能体对话页默认展示数量不当、以及查看对话详情时接口被重复调用的问题。 / Fixed an inappropriate default number of agents shown on the conversation page and duplicate calls to the conversation-detail API.
- 修复浏览器标签页标题与图标未跟随产品品牌和当前语言更新的问题。 / Fixed browser tab titles and icons not following the product branding and the active language.
