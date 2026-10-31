# 🚀 Nexent：开源智能体平台 / Nexent: Open Source Intelligent Agent Platform

我们很高兴地宣布Nexent v2.8.3 正式发布！🎉

Nexent 是一个开源智能体平台，能够将流程的自然语言转化为完整的多模态智能体 —— 无需编排，无需复杂拖拉拽。基于 MCP 工具生态，Nexent 提供强大的模型集成、数据处理、知识库管理、零代码智能体开发能力。我们的目标很简单：将数据、模型和工具整合到一个智能中心中，使日常工作流程更智能、更互联。

We are excited to announce that Nexent v2.8.3 is released! 🎉

Nexent is an open-source agent platform that turns process-level natural language into complete multimodal agents — no diagrams, no wiring. Built on the MCP tool ecosystem, Nexent provides model integration, data processing, knowledge-base management, and zero-code agent development. Our goal is simple: to bring data, models, and tools together in one smart hub, making daily workflows smarter and more connected.

---

## 新功能 / New Features

- 统一 A2A 代理调用超时配置，将默认超时调整为 15 分钟，并通过环境变量同时作用于运行时子智能体调用与北向直调两条路径。 / Unified the A2A agent invocation timeout at 15 minutes through a single environment variable that now covers both the runtime sub-agent path and northbound direct calls.
- 将首页品牌与浏览器标签品牌分离，首页标题与 Logo、标签页标题与图标可各自独立配置，并修复刷新或页面跳转时标题和图标先显示默认 Nexent 再被覆盖的问题。 / Separated homepage branding from browser-tab branding so the home title and logo can be configured independently of the tab title and icon, and fixed the default Nexent title and icon briefly showing before the configured branding took over on refresh or navigation.
- MCP 工具按所属服务分组展示，并统一工具描述的悬浮预览体验，便于在大量工具中快速定位目标。 / Grouped MCP tools by their hosting service and unified the description hover preview, making it easier to locate the right tool in a long list.
- 增强执行历史的压缩与召回能力，新增按运行范围授权的执行结果读取工具，模型可在需要时回查已被压缩的输出细节。 / Enhanced execution-history compaction and recall with a new read tool scoped to the current run, letting the agent retrieve details of outputs that were compacted earlier.

## Bug 修复 / Bug Fixes

- 修复代理组内权限的历史数据问题：将旧表单遗留的 `EDITABLE` 值归一化为 `EDIT`，使非创建者、非管理员用户在界面上显示的编辑权限与实际行为一致。 / Fixed legacy agent in-group permissions by normalizing the `EDITABLE` value left by the previous deployment form to `EDIT`, so non-creator and non-admin users now actually get the edit access the UI already advertised.
- 提升北向 Chat API 的流式响应向前兼容性，新增 `final_answer_mode` 参数以在完整根答案与增量最终答案事件之间选择，默认行为保持兼容。 / Improved forward compatibility of the northbound Chat API streaming response with a new `final_answer_mode` parameter that selects between one complete root answer and incremental final-answer events, with the default keeping existing behaviour.

## 文档与部署变化 / Docs and Deployment Changes

- 新增 v2.8.3 SQL 迁移脚本用于修正代理组内权限，并在 `deploy/env/.env.example` 中补充 A2A 调用超时配置项；升级时请执行迁移以修正存量数据。 / Added the v2.8.3 SQL migration that corrects agent in-group permissions and documented the A2A invocation timeout in `deploy/env/.env.example`; run the migration during upgrade to repair existing rows.
