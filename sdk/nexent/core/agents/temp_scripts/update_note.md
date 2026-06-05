## feat/opt-agent-context-refactor 更新说明
> 该分支基于 feat/benchmark-on-refactor (最新) 进行开发
### 面向问题
1. 当有工具调用的时候，对话消息中 role 为 tool-call 的内容是从 role 为 assistant 的 model output 中正则匹配出来的，所以这部分消息是重复的。当工具调用频繁，或工具参数内容过大时 (比如write tool，写的内容以字符串传入)，信息重复将导致Token浪费严重。
2. 原先的 agent_context.py 有 1400多行，可读性与维护性较差。
3. 上下文压缩虽然降低了Token消耗，但是也导致信息不可逆丢失。

### 该分支实现的目标
- **问题1**：借助静态解析（AST）提取被调用的工具名称及其调用签名（参数值-有截断上限），将其作为 tool-call 的 content，替换原先。
  - 相关代码：https://github.com/liudfgoo/nexent/blob/feat/opt-agent-context-refactor/sdk/nexent/core/utils/code_analysis.py
- **问题2**：对 agent_context.py 按照职责、功能模块进行拆分；拆分文件放置在 agent_context/ 目录下。
- **问题3**：目前这个问题没有全部解决，这里只是对于待压缩的、大段的内容(包括工具输出-observation，模型推理输出；在解决问题1后，工具调用的内容都很短了)，在压缩前进行卸载、保留全量信息；压缩的时候，发送给LLM的内容，也是截断后的。
  - 提供 reload 工具，当Agent在后续任务中，发现需要相关补充信息，可以使用 reload工具，加载全量信息。
  - 这也需要在对话历史中，加入当前 offload 的内容有哪些；目前这里是通过轻量的关键词匹配，提供相关卸载信息，且是临时性地(不驻留，只在当前轮发挥作用)、添加到对话历史的后面(不破坏前缀匹配)。
  - 相关代码：https://github.com/liudfgoo/nexent/blob/feat/opt-agent-context-refactor/sdk/nexent/core/agents/agent_context/offload_store.py, https://github.com/liudfgoo/nexent/blob/feat/opt-agent-context-refactor/sdk/nexent/core/tools/reload_original_context_tool.py

## 后续的变化与演进
1. 像DeepSeek V4模型，采用了极致的KV压缩，上下文窗口增大到1M，其容量限制性在减弱，且随着RL/后训练的进行，模型能力也在增强，启发式的上下文压缩价值可能会降低。（这价值也取决于所用模型，以及硬件资源）
2. Context Rot仍然存在，上下文管理的重心将倾斜在质量保证与增强上，这也要求新的管理方式或架构设计。