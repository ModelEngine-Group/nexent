# 清理风险脚本进度

本目录沿用原 Case 的 7 项验收条件。`test.py`、`cleanup_worker.py` 和 `retention_limits.py` 当前实现本机 POSIX 文件风险、配置加载和批次预算部分；Case 保持 `blocked`，完整脚本未齐备前不声明 `execution.yaml` 或完整验收映射。

| 已编写的断言 | 对应原合同部分 | 额外证明边界 |
| --- | --- | --- |
| `test_retention_process_death_does_not_resurrect_and_cold_retry_finishes` 的 3 个参数 | AC-07、AC-02 的不重新发布部分 | 子进程在确认撤引用、unlink、目录同步后退出；父进程重新创建存储读取持久标记并重试，核验实际字节和幂等计数 |
| `test_retention_failed_deletion_is_not_counted_and_pending_marker_survives_seven_days` 的 3 个参数 | AC-07、AC-05 的墓碑部分 | 子进程注入 unlink/目录同步/删除收据写入错误；未确认删除不计成功，越过 7 天仍保留待删项，确认删除后才开始墓碑期限 |
| `test_retention_run_lock_blocks_deletion_across_processes_without_losing_marker` | AC-07 的运行文件锁 | 子进程持有真实 flock，父进程清理产生 pending，释放后可重试 |
| `test_retention_cleanup_batch_lock_is_exclusive_across_processes` | AC-07 的批次互斥 | 子进程持有实际 cleanup.lock，另一个进程的清理不能撤引用或删除 |
| `test_retention_active_runs_and_fixed_storage_agent_survive_old_run_reclamation` | AC-01、AC-04 的文件部分 | 初始 Agent 目录固定；切换 Agent 后，长期活跃运行与今日运行保留，旧墓碑回收后可继续归档 |
| `test_retention_terminal_boundary_and_shortening_never_extend_existing_expiry` | AC-01、AC-05 的存储期限部分 | 终态起算、收紧不可放宽、恰好到期边界 |
| `test_retention_fixed_manual_cutoff_keeps_newer_run_and_default_policy` | AC-06 的文件截止部分 | 推进时钟后重用同一截止，保留较新运行，不修改默认保留期 |
| `test_retention_independent_process_loads_cleanup_defaults_and_explicit_configuration` 的 3 个参数 | AC-05 的配置加载部分 | 独立进程从集中环境模块读取默认 30 天/3600 秒、关闭清理及显式 7 天/60 秒；实际后端工厂创建维护器，检查文件保留和下次维护截止 |
| `test_retention_scheduled_slow_delete_yields_using_real_monotonic_deadline` | AC-07 的定时工作截止 | 独立进程的实际 unlink 延迟超过 2 秒，检查只完成当前删除原子步骤，其他已撤引用文件保留待删，冷读后重试 |
| `test_retention_hard_scan_limit_preserves_all_fresh_files` | AC-07 的 1000 次检查上限 | 通过实际写入接口生成 1001 个运行，过大的请求上限被限制为 1000，下一段只检查剩余一项；全部未过期文件保持 |
| `test_retention_hard_delete_limit_reports_only_confirmed_files_and_bytes` | AC-07 的 100 次删除上限 | 实际生成 101 份过期 OTLP，第一批最多删除 100 份并逐文件核对逻辑字节，下一批完成最后一份，重复调用不重复计数 |

这些断言按原合同编写；收集成功不代表运行通过。传统 UT 与本 Case 独立计数。已有 UT 的规则断言继续保留；新增脚本针对真实进程退出、文件锁和冷打开后持久状态，不另建 D1。

## 准备与资源释放

所有目录都由 pytest 的 `tmp_path` 派生；每次使用独占临时目录，清理只指向本测试拥有的会话。子进程通过当前解释器启动，执行完成由 subprocess 回收；持锁进程在 finally 关闭输入并等待，超时则终止并回收。运行文件 writer 在 finally 关闭。夹具退出前校验另一租户 OTLP、受保护资源替身的 hash，随后删除独占目录并确认不存在。

身份授权是受控边界，聊天和附件文件是受保护资源替身；它们不能证明真实 PG 聊天、附件服务或租户授权。该文件风险部分不需要共享工厂、业务资产、数据库、Provider 或网络服务。完整 Case 接入实际 HTTP/PG 后仍须重新声明 preparation、资源所有权及完整 execution.yaml，并在正式执行时核验清理回执。

配置子进程屏蔽本地 dotenv，只保留显式测试环境，从产品环境模块和工厂创建维护器；调用真实维护周期但不启动受管后台线程。1001/101 运行工作负载使用产品写入和归档接口构造，因此包含真实 meta 提交成本，正式执行时需记录准备时间。这些脚本均未执行，不据其存在宣称定时唤醒、端到端延迟或工作负载达标。

## 尚缺的完整验收断言

AC-02/03 的真实会话删除及聊天/附件生命周期；AC-04 的真实 PG 最近 Agent 分组、聊天定位与旧游标；AC-05 的受管定时线程启停、唤醒与周期触发；AC-06 的真实 PG 跨用户多批行为。已有 QUERY-D2 的固定截止、100 文件 HTTP 批次和缓存过期断言保留复用；其新增 `test_trj_query_content_chunk_rechecks_state_after_physical_read` 先完成实际正文解码，再注入到期、真实本地清理或受控目录撤权，要求当前已读块不作为成功正文返回，后续重试也拒绝。该 HTTP 脚本已静态收集，未运行，PG 权限仍是受控边界。新增文件配额及 2 秒脚本同样尚未运行；完整运行仍需核验协议层合并后的批次和资源清理。跨宿主共享卷语义由 DEPLOYMENT-D5 验证。

本轮只执行 `pytest --collect-only`、Ruff、版权及静态资产检查。用户已要求暂缓正式验收，不运行以上测试断言。
