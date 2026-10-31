# 🚀 Nexent：开源智能体平台 / Nexent: Open Source Intelligent Agent Platform

我们很高兴地宣布Nexent v2.8.2 正式发布！🎉

Nexent 是一个开源智能体平台，能够将流程的自然语言转化为完整的多模态智能体 —— 无需编排，无需复杂拖拉拽。基于 MCP 工具生态，Nexent 提供强大的模型集成、数据处理、知识库管理、零代码智能体开发能力。我们的目标很简单：将数据、模型和工具整合到一个智能中心中，使日常工作流程更智能、更互联。

We are excited to announce that Nexent v2.8.2 is released! 🎉

Nexent is an open-source agent platform that turns process-level natural language into complete multimodal agents — no diagrams, no wiring. Built on the MCP tool ecosystem, Nexent provides model integration, data processing, knowledge-base management, and zero-code agent development. Our goal is simple: to bring data, models, and tools together in one smart hub, making daily workflows smarter and more connected.

---

## Bug 修复 / Bug Fixes

- 修复对话来源信息在长列表中卡顿的问题：来源元数据改为两行展示并由样式裁剪，悬停与详情按需加载，来源与图片分页统一为每页 20 条，前台刷新做了合并处理，引用在手动翻页后仍能正确定位。 / Fixed chat source metadata stalling on long lists: metadata now renders as two clipped rows, hover and details load lazily, sources and images paginate at 20 items per page, foreground refresh is coalesced, and citations still relocate correctly after manual paging.
- 修复 AIDP 知识库目录分页过少导致四列布局残缺的问题：默认每页 12 条并提供 12/24/48 可选，切换卡片与表格视图时保留记录、页码与筛选条件且不重新请求。 / Fixed the AIDP knowledge catalog showing too few items to fill four-column rows: pages now default to 12 with 12/24/48 options, and switching between card and table views preserves records, page size, and filters without refetching.
- 修复个人信息栏复制 API 秘钥时结果带掩码星号的问题：秘钥列表默认仍返回掩码值，权限层在确认用户有权复制后才取回原文，避免其他调用方意外泄露秘钥。 / Fixed copied API keys in the profile panel carrying mask asterisks: the token list still returns masked values by default, and only the permission layer fetches the raw key after confirming the user may copy it, keeping other callers leak-safe.

