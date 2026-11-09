# Agent Core 接入与部署配置

Nexent 保存智能体的业务配置，后端统一工厂选择 Core Adapter。Jiuwen Adapter 将配置、可信模型出口和授权资源转换为 Jiuwen 可以运行的对象，调用其 Runner，再把过程和结果转换为公共输出。SDK 目录采用 contracts、factory、orchestration、resources、output、context、sandbox 和 cores/{smolagents,jiuwen} 分层；models 目录位置不变，不恢复旧别名。

## 系统级 Core 选择

在部署共同使用的 `.env` 中配置：

```dotenv
NEXENT_AGENT_CORE=jiuwen
```

支持 `smolagents` 和 `jiuwen`，未配置时默认 `smolagents`；空值或未知值在后端启动时拒绝。配置仅由 `backend/contracts/constants/environment.py` 读取，再由应用层注入 SDK，SDK 不读环境变量。

变更后重启全部相关后端角色并刷新页面。Core 统一作用于普通会话、调试、工作台、本地主智能体和子智能体、NL2Agent 与 NL2Skills；远端 A2A 的内部 Core 仍由远端系统决定。模型出口、模型参数、工具和授权仍分别属于各智能体，不因统一选核而共用模型或扩大权限。

智能体配置页面不再显示 Core 字段或选择器。创建、更新、发布版本和导入导出不保存逐智能体 Core；旧客户端/导出包中的 `agent_core` 被忽略。上下文管理器开关、模型、资源绑定与业务提示继续保存。不兼容的非安全执行选项只在运行副本中归一，已启用的未支持护栏明确拒绝，不静默移除安全配置。

本特性未合并的 `v2.7.2_1010_agent_core_factory.sql` 已删除，ORM 不再要求 `ag_tenant_agent_t.agent_core`。新环境无需为选核新增列；旧测试库若已有多余列，新代码直接忽略，不自动 DROP 或重写业务数据。此结论只针对 Core 选核，上游其他功能的数据库迁移仍需按版本执行。

SDK 独立调用仍支持显式注入 `AgentConfig(agent_core="jiuwen", ...)`，用于工厂及其他集成；系统内运行参数统一由后端部署策略生成。公共事件中的 `agent_core` 是历史运行来源标签，继续保留，不是智能体配置项。

## Jiuwen 执行边界

- Jiuwen 负责 Agent loop；模型发送只走 Nexent 统一 ModelService 和可信 `ResolvedModelProfile`，不构造另一套提供商 HTTP 客户端。
- 普通工具、MCP、Skills、知识库、子智能体和 A2A 通过公共授权资源桥执行。子智能体使用自己的模型出口、版本和授权；本地 Core 遵循同一全局策略。
- Python 与文件生成使用 Nexent 受控执行器和配置的沙箱。Skills 是授权本地资源，不是待下载的 S3 文件；脚本只执行授权清单中真实存在的内容。
- ContextManager 和数据库历史沿用 Nexent 的预算、开关、摘要及检查点；已有历史作为事实载入，不重放旧任务。变更部署 Core 后原会话仍按公共历史合同加载。
- StepObservation、RunResult、工具/子调用、推理和容量经过公共输出协议，前端共用既有解析和渲染，不按 Core 增加另一套卡片。

## 人在回路

普通 Jiuwen 会话提供终止型 `ask_user` 能力。原生模式使用 JSON 工具调用，文本模式使用独立完整的字面量调用；两者共用 `ClarificationForm` 和缺少关键信息时的澄清策略。名称与业务工具冲突时使用避让名称。

完整响应校验通过后，后端发出一个既有 `human_interaction` 表单并以 `completed/awaiting_input` 结束本轮，不进入 Python 沙箱、不执行同批其他工具、不继续请求模型，也不把等待答案当作取消。用户提交走原有普通消息及历史恢复链路。普通文字回答不会被自动识别为表单；信息充分时模型应直接作答。NL2Agent/NL2Skills 继续使用各自的业务卡片/产物协议。

## 验证与部署状态

实现、传统 UT、受控 D3/D5、固定页面 D4、真实模型验收和已部署镜像分别记录，不用某一层通过替代其余层。最新进度及未完成范围见 [SPEC task](../../nexent-doc/docs/Developing/runtime-agent-core-factory/task.md)。2026-11-05 已重新构建并部署 `core-global-hitl-20261105` 后端/Web 镜像，当前全局 `jiuwen`。实际核对两种部署值均不显示逐智能体 Core 设置；算卦助手使用原 qwen3.8-max 出口的澄清卡片、提交续聊及已保存会话历史刷新验证通过。澄清提交在后端识别已保存的单层公共原生信封，仍使用既有表单身份和原子保存校验。工作台五模式与 NL2Agent/NL2Skills 完整真实业务旅程仍需单独验收。保存会话应从其历史入口（`thread_id`）打开；`agent_id` 是新会话入口，本轮没有修改该导航语义。


2026-11-06 后端已更新为 `jiuwen-loop-20261106`，Web沿用11-05版本。旧Agent思考参数在公共兼容边界按可信出口转换，保留原自定义字段优先级；会话低强度或关闭思考均可保存和运行，无需清空原智能体或历史配置。新格式参数与受保护字段仍严格校验。

Jiuwen 的进程级 Runner 及回调框架由 `cores/jiuwen/execution_loop.py` 的稳定循环服务承载，归应用 `ThreadManager` 的 `background-service` 通道拥有，占一个专用服务名额。各主/子调用以独立协程并发运行、各自传递上下文与取消范围；服务自身在空 Context 中启动。单运行取消不会停止全局服务，应用退出排空任务后在原循环关闭 Runner；容量不足不另开非托管线程。阻塞 MCP 连接建立留在 Agent 工作线程。此修复避免跨事件循环竞争同一异步锁，不串行整个 Agent 执行，不修改前端渲染、模型或数据库合同。

最终镜像中原沙箱多子智能体与 deepseek-v4-flash 的两个并发会话各三轮通过：6次主调用、18次首次子调用全部成功，实时与历史一致，原配置及历史未改。SDK UT 466项通过，受控并发、取消隔离及 MCP/Skills 资源回归另行记录；完整工作区仍有3项既有无关资产门禁错误。具体 Case、准备清理及交付证据见 SPEC，不将这些结果等同于全部模型或浏览器业务验收。

2026-11-06 澄清历史读边界已修复，并按 `latest` 构建，经根 `deploy.sh --defaults docker --image-source local-latest --sandbox-mode full` 部署。正常 `completed/awaiting_input` 的空正文、空最终块、无错误结果表示等待用户输入，历史加载保留此终态；不将其当作缺少最终回答，也不改写数据库原记录。普通空回答、畸形协议、失败/停止和不符合上述形状的记录继续原校验。前端共用现有卡片和历史解析，无新增 Core 分支；具体回归和真实模型页面结果见 SPEC 最新记录。

2026-11-09 Skill创建历史的业务事件边界已修复并重新部署latest。NL2Skill流在保存文件/摘要等业务事件前去除原生运行信封的判别字段，保留文件正文和追踪信息；可信Skill创建历史对旧文件包装做同样的只读投影，避免公共前端误报NEXENT_TERMINAL_MISSING或显示空文件。无需SQL或前端Core分支。121项UT、受控D3及真实工作台生成、保存、历史重开/刷新D4通过，截图旧记录3个文件逐项一致且原数据未改写；各Core真实模型验收范围见SPEC。

2026-11-09 NL2Agent原生MCP交互边界已修复并部署latest。Jiuwen python_workflow识别MCPTool单层result文本并发出既有nl2a/nl2a_state；有效卡片阻止后续模型和工具派发，公共流排空拥有的工作线程与真实等待终态，普通取消保持原行为。卡片后已派发工具结果仍透传且边界保持；创建持久化和公共历史保留完整原生工具/结果身份。前端不增加Core分支。真实工作台完成卡片、提交续接及历史刷新，原配置/历史未改；详细验证和剩余门禁见SPEC。


## NL2Agent结果与草稿入口

工作台使用同一套公共实时/历史规则：只有可信且目标Agent ID一致的`agent_generation_completed`才生成结果跳转卡，消息内去重；后续普通回答不降级完成状态。澄清、空回答、字段保存和等待终态均不会产生结果卡，历史缺少完成事件时也不从正文推测成功，不改写原记录。

提前编辑从工作台工具栏的“编辑当前草稿”进入，绑定当前线程草稿目标；没有草稿或退出创建模式时隐藏，运行期间禁用且不提供可点击链接。打开草稿不会自动提交澄清或触发生成，用户返回原会话可以继续提交。

2026-11-09主/Web latest已重新构建部署。smolagents和Jiuwen分别用真实模型完成澄清、提前编辑返回、提交生成、结果卡及历史重开/刷新；当前部署恢复为jiuwen，私有配置逐字节还原、原数据未变。定向前端96项、Python复用96项、8变体D3通过；两次提供商TLS失败保留为失败，最终同版本重跑通过。全量前端与全工作区资产的既有阻塞另见SPEC task，不能由这些定向结果推出全量通过。
