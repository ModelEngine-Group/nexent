# Context Budget 与模型能力治理开发 Handoff

> 日期：2026-09-09  
> 状态：核心实现和本地分层验证完成；真实环境验收尚未收口  
> 继续开发分支：`feat/context-budget-runtime-governance`  
> 基线：`origin/develop@163b7e292`

## 1. 接手方式

```bash
git fetch origin
git switch --track origin/feat/context-budget-runtime-governance
```

代码仓库工作树原路径：

```text
/home/jason/Workspace/Huawei-Agentic/worktrees/context_budget_split
```

SPEC 是独立的 Syncthing 文档目录，不属于 Nexent Git 仓库：

```text
/home/jason/Workspace/Huawei-Agentic/nexent-doc/docs/Developing/context-budget
/home/jason/Workspace/Huawei-Agentic/nexent-doc/docs/Developing/context-budget/p8-capability-discovery-and-usage-popover
```

P8 的 `00 Requirement Analysis.md`、`01 Functional Design.md`、`02 Technical Design.md`
已补充 P8-015～P8-019；最终浏览器、真实模型和 Langfuse 证据仍需写回验收矩阵。

## 2. 分支结构

当前分支把原四层 stacked PR 以四个 squash 提交整合，并在 2026-09-09 重放到最新 develop：

| 层 | 当前提交 | 主要内容 |
|---|---|---|
| Capacity foundation | `4ca63189d` | 容量 profile、tokenizer 治理、模型能力 catalog、Provider count/preflight 基础 |
| Model governance | `1cdfcc151` | 模型容量 API/前端、同表能力基线与租户覆盖、结构化能力编辑器 |
| Request recovery | `be3c58c4b` | 最终请求预算、上下文组合、Provider request count、overflow recovery |
| Usage observability | `dd2ebc67b` | Agent/模型使用量、上下文证据、前端用量详情、数据库持久化、能力运行时接线 |

历史远端 PR 仍为：

- #3848：`split/context-capacity-foundation`
- #3849：`split/context-model-governance`
- #3850：`split/context-request-recovery`
- #3851：`split/context-usage-observability`

这些 PR 的远端分支没有在本次 handoff 中强制更新；继续开发应优先以当前整合分支为事实来源。

## 3. 已实现的关键行为

### 3.1 Context Budget

- 输入只观测，不使用 Nexent 自行推断的供应商 input/max-output 联合硬限制。
- API 请求的最大输出使用模型记录/profile 的 `max_output_tokens`。
- ContextManager 根据可信容量、完整请求估算和预设阈值执行 compaction。
- dispatch 前重建并检查完整请求，Provider overflow 响应驱动恢复动作。
- API 实测用量与本地估算分开记录；模型响应数据不会被中途失败调用覆盖。
- 前端分开展示模型调用开销和“估算的上下文构成”。

### 3.2 模型能力记录与生效

- 不新增业务表；继续使用 `model_record_t`。
- `feature_capability_metadata` 保存 Provider/catalog 自动能力基线。
- 新增 nullable JSONB `feature_capability_override` 保存租户管理员覆盖。
- 有效配置在读取/运行时计算，不额外持久化第三份状态。
- 已确认能力默认开启；未知能力 fail closed。
- 租户模型管理员可以修改当前租户覆盖；跨租户修改要求超级管理员。
- 管理员可以为私有/未知模型补充 reasoning 和 prompt-cache 能力。
- catalog 更新刷新未覆盖字段；显式覆盖保持不变。
- factory/model/endpoint 改变时保留覆盖并产生 `override_identity_mismatch`。
- 前端只提供结构化字段和“恢复自动配置”，不提供原始 JSON 编辑器。
- Agent 将有效 capabilities、policy 和 warnings 传到 OpenAI adapter。
- trace 包含 `llm.feature.policy_source` 和 `llm.feature.configuration_warnings`。

主要实现位置：

- `sdk/nexent/core/models/feature_capability.py`
- `backend/consts/model_feature_capabilities.py`
- `backend/services/model_feature_configuration_service.py`
- `backend/services/model_management_service.py`
- `backend/agents/create_agent_info.py`
- `sdk/nexent/core/models/openai_llm.py`
- `frontend/app/[locale]/models/components/model/ModelFeatureCapabilityFields.tsx`
- `frontend/services/modelService.ts`
- `deploy/sql/migrations/v2.6.0_0904_model_feature_capability_override.sql`

## 4. 已完成验证

下列测试均在独立 pytest 进程中通过：

- `test/sdk/core/models/test_feature_capability.py`：13 passed
- `test/sdk/core/models/test_openai_llm.py`：94 passed
- `test/backend/services/test_model_feature_configuration_service.py`：6 passed
- `test/backend/services/test_model_management_service.py`：86 passed
- `test/backend/services/test_model_provider_service.py`：74 passed
- `test/backend/app/test_model_managment_app.py`：97 passed
- `test/backend/agents/test_create_agent_info.py`：240 passed（2026-09-09 rebase 后复跑）
- `test/sdk/core/agents/test_agent_model.py`：69 passed
- `test/sdk/core/agents/test_nexent_agent.py`：240 passed
- Context policy/budget/assembly：16 passed
- 模型能力与 context usage migrations：3 passed
- 前端：rebase 前 `npm run type-check -- --pretty false` passed

2026-09-09 rebase 后复跑结果：能力模型 13 项和 Agent 创建 240 项通过。前端全量 type-check 当前被
`origin/develop` 新增的 `e2e/external-memory-provider.spec.ts` 阻塞：当前设备复用的 `node_modules` 尚未安装
`package.json` 已声明的 `@playwright/test@1.62.1`，继而产生该文件的隐式 `any` 派生错误。换设备后先完整安装
前端依赖，再重跑 type-check；不要把当前依赖不完整状态记为业务代码回归失败或 PASS。

已从 `origin/develop` 执行四次本地 `git merge --squash` 演练，每层提交后分别验证；最终演练树曾与
`split/context-usage-observability` 逐文件一致。2026-09-09 再次 rebase 时仅
`backend/agents/create_agent_info.py` 导入区冲突，解决结果同时保留：

- `get_memory_external_provider_service`
- `effective_feature_factory`
- `resolve_record_feature_configuration`
- `ModelCapacityConfigError`
- `SYSTEM_MANAGED_TOOL_NAMES`

### pytest 注意事项

部分旧测试文件会改写全局 `sys.modules` 或 tokenizer registry。把大量文件交给同一个 pytest 进程会产生
重复注册/模块桩污染；应逐文件启动 pytest。`test_monitoring_app.py` 和
`test_agent_service.py` 整文件在本机曾超过 60 秒，但本功能新增 selector 独立通过：

```bash
pytest test/backend/app/test_monitoring_app.py::TestContextBudgetMetrics -q
pytest test/backend/services/test_agent_service.py::test_ac_tu_004_stream_persists_llm_and_turn_usage_units_atomically -q
```

## 5. 尚未完成的验收

以下事项不能标记为 PASS：

1. 在部署后的真实 PostgreSQL 上确认新 migration 和 JSONB round-trip。
2. 用真实 HTTP API 验证管理员权限、保存、刷新、恢复自动配置和身份变化告警。
3. 浏览器验证结构化编辑器及中英文显示，并保留截图/网络证据。
4. 使用 `MODEL_URL`、`MODEL_API_KEY`、`MODEL_NAME` 跑实际 Nexent Agent 路径。
5. 在 Langfuse 中确认 reasoning/cache 请求参数、policy source、warnings、token usage 和最终响应。
6. 将证据回填 P8-015～P8-019 traceability table，消除 `PENDING`。
7. 根据后续策略决定更新旧四个 stacked PR，还是从当前整合分支创建新的替代 PR。

不要把模型或 Langfuse 密钥写入命令日志、代码、测试、截图或 SPEC。只使用环境变量名检查可用性。

## 6. 本机 VM 状态

Multipass VM：`nexent-context-capability`，当前已停止。

部署在镜像拉取阶段被中断，基础设施容器曾启动，但不能视为完整部署。VM 是当前设备本地状态，换设备后
不会随 Git 分支迁移。若继续使用本机，可启动后检查；若换设备，建议按
`nexent-multipass-runtime` 技能重新创建专用 VM。

VM 部署脚本曾把挂载工作树的非执行文件改成 executable，并生成 `official-skills-zip/`；handoff 前已恢复
全部 Git 执行位并删除该可重建目录。当前提交前工作树应保持干净。

## 7. 建议的下一步顺序

1. checkout 当前 handoff 分支并确认 `git status` 干净。
2. 逐文件重跑上方核心 UT 和前端 type-check，验证 rebase 结果。
3. 创建新的隔离 VM，完成 Docker 部署和 migration 检查。
4. 使用一次性本地管理员账号做 API/browser round-trip。
5. 接入真实模型，完成默认、覆盖关闭、覆盖强度和恢复自动配置四组 Agent 调用。
6. 查询 Langfuse trace 并回填 SPEC 证据。
7. 选择 PR 迁移方案，更新描述、依赖关系和验证结果。
