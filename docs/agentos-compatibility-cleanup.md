# AgentOS 兼容实现复核

复核日期为 2026-11-12。范围包括 AgentOS、Management 运行准备、Runtime SDK 工厂以及两者的客户端。依据为产品导入关系、调用方搜索、当前回归测试及服务边界 SPEC。

## 已删除的实现

| 实现 | 复核结果 | 当前承接 |
| --- | --- | --- |
| Runtime `legacy_admission.py` | 无产品调用方，旧线程池接纳链已退出 | `prepared_run.py`、`ephemeral.py` 与当前运行管理器 |
| Runtime `legacy_tracking.py` | 无产品调用方，旧会话 channel 登记已退出 | 持久 run_id、execution 状态与 RunJournal |
| Runtime `legacy_producer.py` | 无产品调用方，旧 SSE 生产任务已退出 | Runtime 当前独立 producer，Management 事件投影 |
| Runtime `admission.py` | 只服务退役的兼容会话入口 | Management 会话提交与 Runtime 标准快照接纳 |
| Management `run.py`、`subscription.py`、`execution.py`、`lifecycle.py` | 原进程内执行器及其注入协议，无产品启动调用方 | `runtime_client.py`、`prepared_turn.py`、`prepared_projection.py` |
| `LegacyRunMaterializer`、`LegacyRunFactory`、`legacy_workspace.py` | 只供已退役的进程内运行使用 | Management 纯快照编译，Runtime 当前 prepared SDK 构造和 Skill 物化 |
| preparation 标记及 export_evaluation 开关 | 新运行均已使用标准快照，无需 legacy/management 跳转选择 | 单一路径编译与原幂等指纹 |
| 旧公开 Runtime、compat 启动及 Management 反向派发 | Gateway、Northbound、A2A、自动化均已迁移 | Management 对外适配和标准 AgentOS |

没有增加旧模块别名、弃用包装器或 import 回退。两个服务目录之间不允许直接源码导入。

## 仍有用途的历史处理

| 实现 | 保留依据 | 删除条件 |
| --- | --- | --- |
| `runtime/agentos/legacy_resume.py` | Management 在无法找到新式 prepared turn 时仍调用，只读重放旧会话输出 | 完成旧数据和存量运行迁移，移除唯一当前调用方并验证历史会话读取 |
| `infrastructure/legacy_stream_replay.py`、`rdb/conversation_state.py` 的历史续传读取 | 上一项仍使用，包含真实归属校验及旧单元位置 | 与历史续传同批退役，不能直接丢弃旧消息 |
| Management `background_compatibility.py` | 当前后台派发在缺少自动化来源记录时仍使用；执行已通过标准 AgentOS | 完成后台来源记录补齐或明确不再支持该业务来源，保留 run_id 与消息幂等 |
| Management `prepared_turn.py` 的历史 receipt、消息状态及游标适配 | 已存历史消息仍可能没有 Management streaming_owner 或新 admission 记录 | 完成数据迁移与对应历史回归 |
| 当前 prepared model 的旧根模型别名判断 | 处理现有资源与模型引用的形状，当前模型配置回归仍覆盖 | 统一资源数据形状并验证根模型、子模型共享与版本语义 |
| `CompatibilityConversationRun`、`CompatibilityStop` 类型名 | 当前 Management 公开请求装配和会话查询仍使用；没有重新开放旧跨服务执行入口 | 可在独立命名整理中整体改名；当前不保留无效 preparation 字段 |

上表不能据文件名推导为已完成迁移。移除时应先更新调用方或存量数据，避免将只读历史请求变成新执行。

## 验证与限制

当前编译、公开会话、归属、后台恢复与投影选择组以及正式 AOS-TRANSPORT-D3-001 用于验证当前路径。新增源码退役检查先得到两项失败，用于防止已删除执行器重新进入镜像。镜像独立启动的前序证据和部署步骤记录在独立 nexent-doc 文档目录。

传统测试中仍有直接导入退役私有实现的旧用例，混合文件同时包含管理 CRUD 和权限断言。本轮保留混合文件原内容，不批量删除有效管理测试，也不使用 skip、ignore 或重建产品兼容入口掩盖失败。两项仅验证 LegacyRunFactory 的编译用例随该实现退役，当前快照编译、模型根子配置和真实跨 HTTP SDK 断言继续执行。

`API-AUTO-7CBDF5C068165594` 仍需迁移。原用例要求旧 Runtime 运行与 Northbound 私有入口的同步过载 429；当前持久运行采用异步 202 接纳，需要明确接纳前拒绝与运行中终态错误的边界。当前公开错误透传 UT 证明已经收到的 429 和 Retry-After 可以保留，不等于证明真实持久运行压力下仍按旧阶段拒绝。该缺口必须在 PR 中披露，不能把跨 HTTP 选择组通过描述为全分支验收完成。
