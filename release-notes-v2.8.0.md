# 🚀 Nexent：开源智能体平台 / Nexent: Open Source Intelligent Agent Platform

我们很高兴地宣布Nexent v2.8.0 正式发布！🎉

Nexent 是一个开源智能体平台，能够将流程的自然语言转化为完整的多模态智能体 —— 无需编排，无需复杂拖拉拽。基于 MCP 工具生态，Nexent 提供强大的模型集成、数据处理、知识库管理、零代码智能体开发能力。我们的目标很简单：将数据、模型和工具整合到一个智能中心中，使日常工作流程更智能、更互联。

We are excited to announce that Nexent v2.8.0 is released! 🎉

Nexent is an open-source agent platform that turns process-level natural language into complete multimodal agents — no diagrams, no wiring. Built on the MCP tool ecosystem, Nexent provides model integration, data processing, knowledge-base management, and zero-code agent development. Our goal is simple: to bring data, models, and tools together in one smart hub, making daily workflows smarter and more connected.

---

## 新功能 / New Features

- 新增 A2A 智能体协作协议支持，提供适配层、能力目录与校验模块，智能体可对外暴露可发现、可调用的服务端点。 / Added A2A agent collaboration protocol support with an adapter layer, capability catalog, and validation modules, so agents can expose discoverable and callable service endpoints.
- 新增智能体发布页签与访问详情，可查看发布状态、访问方式与 A2A 接入信息。 / Added an agent publication tab with access details, showing publication status, access methods, and A2A connection information.
- AIDP 知识库管理能力扩展：新增知识库详情页与完整的知识库创建、文件导入流程。 / Extended AIDP knowledge-base management with a knowledge-base detail page and complete creation and file-import flows.
- AIDP 检索支持图谱检索（graph search）与术语覆盖重排（jargon coverage），可在智能体与会话的检索配置中选择。 / AIDP retrieval now supports graph search and jargon coverage reranking, selectable in agent and conversation retrieval settings.
- 新增 DeepSeek 内置联网搜索工具，可在智能体中直接调用。 / Added a built-in DeepSeek web search tool that can be invoked directly from agents.
- 模型调用支持温度与 Top P 参数覆盖，并在参数弹窗中补齐两项参数的中英文说明与可聚焦提示。 / Model calls now support temperature and Top P overrides, with bilingual parameter guidance and keyboard-focusable help tooltips in the parameter dialog.
- 资源管理新增安全审计日志，覆盖后端管理类 API 的关键操作。 / Added security audit logging to backend management APIs.
- 新增官方智能体合集，内置 26 个开箱即用智能体，覆盖教育、金融、政务、人力资源、法律、营销、医疗七个行业，并配套技能包。 / Added an official agent collection with 26 ready-to-use agents across education, finance, government, human resources, legal, marketing, and medical domains, bundled with companion skills.
- 智能体仓库支持排序，并可自定义列表列宽与预置智能体头像。 / Agent repository now supports sorting, resizable list columns, and preset agent avatars.
- 本地工具支持不经过沙箱直接调用，官方工具动作可延迟启动 Docker，降低本地执行开销。 / Local tools can now be invoked without the sandbox, and official tool actions defer Docker startup to reduce local execution overhead.
- 自动化会话支持保留运行记录并统一活跃时间统计，标题改写采用独立版本号避免竞态。 / Automation conversations now preserve run records with unified activity tracking, and title renames use an independent version counter to avoid races.
- 新增可选的 Nginx HTTPS 终止配置，便于在部署时启用 TLS。 / Added optional Nginx HTTPS termination for enabling TLS at deployment time.
- 路由切换时展示骨架屏过渡，替代整页加载指示，导航期间保留源页面状态。 / Added shimmer skeletons during route navigation instead of a full-page loader, preserving source-page state while loading.

## 重构优化 / Refactoring & Improvements

- 重构后台服务目录结构，按业务模块重整 Management services 与公共工具，提升可维护性。 / Reorganized backend services by business domain, restructuring management services and shared utilities for better maintainability.
- 数据处理链路重构，以 Celery prefork 替代原有 Ray 实现，任务调度与恢复更稳定。 / Refactored the data-processing pipeline to use Celery prefork in place of Ray, making task scheduling and recovery more robust.
- 重构模型服务与模型/智能体契约和工具函数，统一调用入口与参数传递方式。 / Refactored the model service along with model/agent contracts and utilities, unifying entry points and parameter passing.
- 重构智能体提示词体系，统一提示词的生成、存储与注入路径。 / Refactored the agent prompt system, unifying how prompts are generated, stored, and injected.
- 全新改版智能体与对话工作流，统一工作台资源选择组件与推荐交互。 / Redesigned the agent and chat workflows, unifying workbench resource selection and recommendation interactions.
- 标签管理入口集中到资源管理页，同步优化知识库与资源配置交互。 / Consolidated tag management into the resource management page and refined knowledge-base and resource configuration interactions.
- 优化默认入口，部署后直接进入 Agent 工作台，首页入口默认隐藏，可通过环境变量按需开启。 / Optimized the default entry so deployments land on the Agent Workbench with the standalone Home page hidden by default, configurable through environment variables.

## Bug 修复 / Bug Fixes

- 修复对话中 PDF 预览无法正常显示的问题。 / Fixed PDF preview not rendering correctly in chat.
- 修复普通用户会话与工作台无法选择模型的问题。 / Fixed model selection being unavailable in regular user sessions and the workbench.
- 修复对话过程中输入框异常刷新，以及资源管理页无法进入知识库的问题。 / Fixed the composer refreshing unexpectedly during a session and the knowledge base being unreachable from the resource management page.
- 修复删除知识库后，智能体与会话仍残留绑定关系的问题。 / Fixed agent and conversation bindings remaining after a knowledge base was deleted.
- 修复复制智能体时未一并复制其技能的问题。 / Fixed skills not being copied when duplicating an agent.
- 修复 AIDP 相关同步调用阻塞其他接口的问题，改为托管线程执行。 / Fixed AIDP synchronous calls blocking other endpoints by moving them to a managed thread.
- 修复并发调用同一智能体导致沙箱内核不健康的问题。 / Fixed concurrent calls to the same agent making the sandbox kernel unhealthy.
- 修复 Agent 解析输出时思考前缀兼容性问题，以及子智能体场景下最终答案重复的问题。 / Fixed thinking-prefix compatibility in agent output parsing and duplicated final answers in subagent scenarios.
- 修复工作台 nl2skills 功能异常与 Skill 流式创建问题。 / Fixed issues with the nl2skills feature in the Agent Workbench and streaming Skill creation.
- 修复自定义网关地址下思考控制不生效的问题。 / Fixed reasoning controls not taking effect for custom gateway URLs.
- 修复英文界面中残留中文文案的问题。 / Fixed Chinese text remaining in the English UI.
- 修复智能体空间列表标签在未启用时导致的报错，并统一英文界面下的 Agent Space 命名。 / Fixed errors when Agent Space listing tags were disabled and unified the English Agent Space naming.
- 修复 SSE 流式响应被代理缓冲的问题，增加 `X-Accel-Buffering: no` 请求头。 / Fixed SSE streaming being buffered by proxies by adding the `X-Accel-Buffering: no` header.
- 修复 SQL 工具在限制结果行数时额外拼接 LIMIT 的问题。 / Fixed the SQL tool appending an extra LIMIT when capping result rows.
- 修复会话置顶刷新、批量管理入口丢失与内联编辑失效等会话相关问题。 / Fixed conversation pin refresh, missing batch-management entry, and broken inline editing.
- 修复知识库上传拖拽限制与批量标签读取，并完善 AIDP 知识库详情分页与评估器界面。 / Fixed knowledge-base upload drop restrictions and batched tag reads, and refined AIDP knowledge-detail pagination and the evaluator UI.

## 文档与部署变化 / Docs & Deployment Changes

- 合并 v2.7.0 之后的所有 SQL 迁移为单一 `v2.8.0_merged_migrations.sql`，迁移文件目录仅保留合并后的包。 / Consolidated all post-v2.7.0 SQL migrations into a single `v2.8.0_merged_migrations.sql`, keeping only merged bundles in the migrations directory.
- 新增外部 A2A 智能体的 TLS 证书校验开关，可按智能体决定是否验证对端证书。 / Added a TLS verification switch for external A2A agents so peer certificates can be validated per agent.
- Helm Chart 支持通过 Secret 注入环境变量，并补充配套的 `env.sh` 脚本与部署文档。 / Helm charts now support injecting environment variables through Secrets, with a companion `env.sh` script and updated deployment docs.
- 前后端容器默认时区调整为 `Asia/Shanghai`，并将完整环境变量文件注入后端容器。 / Default container timezone for frontend and backend is now `Asia/Shanghai`, and complete environment files are injected into backend containers.
- 新增变更源文件版权头检查与 MinIO 镜像同步到 Docker Hub 的流水线。 / Added a copyright-header check for changed source files and a pipeline that syncs the MinIO image to Docker Hub.
