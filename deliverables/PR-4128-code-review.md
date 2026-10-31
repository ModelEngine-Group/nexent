# PR #4128 Code Review — Daily preflight CWD 修复 + AIDP journey mock-only 化

- **PR**: [ModelEngine-Group/nexent#4128](https://github.com/ModelEngine-Group/nexent/pull/4128) `🐛 Fix(e2e): resolve the Daily checkout without the cwd and run the AIDP journey on the mock only`
- **作者**: cj2026-bit · 2 commits · 15 files · +152/−448（净删 296 行）
- **基准**: merge-base `be5d1cf7d`；⚠️ develop 已领先 **14 个提交**，合入前需 rebase
- **性质**: 纯 e2e 测试基础设施（test-e2e/），不改产品代码

---

## 总体评价

**两个修复都做得很扎实，验证方法堪称模范。** 这是一个"事故驱动"的 PR：10-15 的 Daily 定时跑在启动 36 秒后崩溃，作者不仅修了根因，还用 1:1 WSL 仿真完整复现了旧崩溃、验证了新版本绿灯——这种验证深度在 e2e 基础设施 PR 里少见。同时顺手退役了整个 profile 选择机制（净删 296 行），理由明确（短中期无真实 AIDP 环境），清理彻底无残留。

## 修复 1：Daily preflight 的 CWD 崩溃

**问题**：Daily launcher 从 GitHub runner 工作目录（`/home/jason/actions-runner/_work/...`）启动，而 checkout 在 `/root/project/nexent`。`static_config_problems` 内部调用 `repository_root()` 按进程工作目录向上找仓库根 → 找不到 → `ValueError: Cannot locate repository root` → Daily 拒绝启动。

**修复**：`static_config_problems(home, records, *, repo)` 增加显式 `repo` 参数（`local_preflight.py` L63），调用链逐环验证：
- `daily-launch.py` L80：`suite.doctor(repo, ...)` —— repo 来自 launcher 自身文件位置推导（`sync_checkout(repo, ...)` 早已解析）✅
- `suite.py` L107-108：`doctor(repo, home, records)` 原样传给 `static_config_problems` ✅
- `local_preflight.py` 删除了 `repository_root` import，preflight 内**不再有任何从 cwd 解析仓库的路径** ✅

**评价**：依赖注入替代环境推断，是这类问题的标准正解。连带的 profile-config 批量门槛（一个可选 case 缺机器本地配置就挟持整个 Daily）也一并移除——这与"per-case dependency"的设计契约重新对齐。

## 修复 2：AIDP journey 退役 profile 选择机制

**问题背景**：mock/real 双 profile 机制（`config/aidp-journey.yaml` 选择 `mock` 或 `real_smoke`）需要每台机器维护本地配置文件，而短中期没有真实 AIDP 环境可测——机制空转还成为 Daily 的启动门槛。

**改动验证**（逐项核查）：

| 项 | 结果 |
| --- | --- |
| `PW-KB-AIDP-01/execution.yaml` | 改为直接声明 `required_mock_services: [knowledge-provider]`，与兄弟 mock case（AGT-071 等）同构 ✅ |
| spec 固定 ORACLE 常量 | `kbId: "aidp-kb-product"` 等 5 字段，`oracleForProfile()` 及 5 个 `NEXENT_TEST_AIDP_REAL_*` 环境变量全部删除 ✅ |
| `ext_attach.py` | `resolve_profile_selection` / `_load_profile_config` 约 100 行删除，全库无残留调用 ✅ |
| validator | `profile_selection` 从 EXECUTION_FIELDS 移除（字段出现即报未知字段错误，防御性拒绝）✅ |
| schema/example | `aidp-journey.schema.json` / `aidp-journey.example.yaml` 删除，无引用残留 ✅ |
| 测试 | 删除 7 个 profile 专项测试，attach 核心测试**保留 22 个**（锁/重置/身份校验/不可达阻断等关键路径全覆盖）✅ |
| 误伤检查 | FAF-D3-001 / TFP-D3-001 / TPC-D3-001 等的 `real_smoke` 是普通 `profiles` 声明（非 profile_selection），**不受影响**；`IMPLEMENTATION_FIELDS` 保留 `profiles` 正确 ✅ |

**AGENTS.md 合规**：D1-D5 资产规约要求"Preserve all existing D1 Cases"，本 PR 未删 case 本身，只改执行方式且 changes/ 下有完整记录（AIDP-JOURNEY-MOCK-ONLY-20261016.yaml），符合变更追溯要求。

## 验证声明可信度核查

- 声明"4 个 PW journey 失败为 pre-existing UI drift"——diff 确认本 PR **未触碰任何 page objects**（publish dialog / agent-editor locator 漂移源于 develop 侧 UI 重构），归因可信 ✅
- 声明"437 工具测试通过、17 个 pre-existing 失败"——量级与改动面匹配 ✅
- 1:1 WSL 仿真（复现旧崩溃 bb4cdad0c + 新版本 D0-D6 绿灯）——验证深度超预期 ✅

## 🟡 建议

1. **develop 漂移 14 个提交（合入前必须处理）**：本 PR 改的 `PW-KB-AIDP-01/test.spec.ts` 与 develop 侧大量 UI 重构（agent editor #4103 等）存在交集，PR 自己声明的 4 个 PW journey 失败正是这个漂移的症状。rebase 后需重跑该 case 确认 mock 链路（attach → recall → oracle → citation）仍绿，否则"可合并"的前提不成立。
2. **profile 机制退役的回程成本**：将来真实 AIDP 环境就绪时，需要重新引入 real_smoke 路径。建议在 changes/ 记录之外，给 `PW-KB-AIDP-01/execution.yaml` 的 notes 加一句 "real-environment journey tracking: <issue 链接>"，让回程有锚点。💭 轻微。
3. **ORACLE 硬编码进 spec**：种子文案（"AIDP Search provides low-latency retrieval"）与 ext-knowledge mock 的种子数据是隐式契约，mock 侧改种子会静默打破 oracle。建议在 ext-knowledge-mock 的 README（本 PR 已改）里反向声明这个契约关系。💭 轻微。

## 结论

| 项 | 结论 |
| --- | --- |
| 🔴 严重 | 0 |
| 🟡 建议 | 1（rebase 后重跑 PW-KB-AIDP-01，其余 2 条轻微） |
| 质量 | 修复方向正确、清理彻底、验证深度模范 |

**可合并**——前提是 rebase develop 后 PW-KB-AIDP-01 在 mock 链路上确认仍绿（PR 验证时的 4 个失败虽归因为 pre-existing，但 rebase 后的最终状态需要一把绿灯证据）。
