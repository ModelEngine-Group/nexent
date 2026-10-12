---
name: nexent-daily-test
description: 在 Ubuntu 自托管测试机上编排 Nexent 每日分层全量测试、维护本地测试基线和 P0 Playwright 候选代码，并将证据仅保存在本机。用于 OpenCode 执行 Daily/手工全量测试；不用于 PR 测试或外部结果发布。
---

# Nexent Daily Test

以 `config/test-policy.yaml` 和本批 `agent-input/execution-plan.json` 为执行事实源。测试必须按最低有效层验证：单元/组件、服务/协议、真实 AI Runtime、浏览器 Journey、专项测试不能相互冒充。

## 开始前

确认环境变量 `TEST_ROOT`、`NEXENT_REPO`、`BASE_SHA`、`HEAD_SHA`、`RESULT_DIR` 和 `TEST_BATCH` 均存在。完整读取：

- 需要选择执行层和工具时读 [references/execution-matrix.md](references/execution-matrix.md)。
- 写检查点、报告或判断退出状态时读 [references/result-contract.md](references/result-contract.md)。
- 分析 Git diff、维护测试用例或 P0 Playwright 时读 [references/maintenance-policy.md](references/maintenance-policy.md)。

部署由外层入口调用 `nexent-deploy` 完成。部署证据不存在或站点未就绪时停止功能测试，记录基础设施阻塞；不要把所有用例批量写成产品失败。

## 不可破坏的边界

- 不把测试结果、Excel、截图、Trace、视频、Prompt、模型响应上传 GitHub，不写 `GITHUB_STEP_SUMMARY`，不创建 Issue/PR。
- 不修改 Nexent 业务代码。允许的持久维护目标只有本地测试资产；OpenCode 本批只能向 `RESULT_DIR` 写候选内容，由外层脚本校验后再提升。
- 产品模型、Embedding、Rerank、VLM、STT、TTS 必须使用 `config/models.yaml` 与 `config/secrets.env` 中启用的真实配置；故障注入可以使用本地受控端点。
- OAuth、CAS、外部 A2A/Nacos 的专用 Playwright Journey 服从 `test-policy.yaml`。标记为 `SKIPPED_BY_POLICY` 的项不得启动外部服务、不得改记为 PASS。
- Playwright 只用于 `PW-E2E` Journey；BE-UT、SDK-UT、FE-COMP、API-IT、CONTRACT、AGENT-IT、DEPLOY、SEC、REL 使用各自最低验证层。
- 只清理带本批 `TEST_BATCH`/`run_id` 且能确认由本批创建的数据，不删除共享数据、Docker volume 或历史结果。

## 完成条件

1. `execution-plan.json` 中每个活动项恰有一条本批结果；策略排除项保留预置的 `SKIPPED_BY_POLICY`。
2. 每条执行结果在完成后立即追加到 `checkpoints/results.jsonl`，失败或阻塞附可定位证据。
3. `agent-output/change-set.json`、`case-maintenance.json`、`playwright-maintenance.json` 均存在且符合参考文件约定。
4. 详细日志与证据只在 `RESULT_DIR`；标准输出保持最小且不含 secret、用例详情或模型回答。
5. 不因为后续层失败丢弃前面层的真实结果；最终状态由 D6 汇总确定。
