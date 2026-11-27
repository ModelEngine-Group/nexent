# 清理风险脚本进度

本目录沿用原 Case 的 7 项验收条件。`test.py`、`cleanup_worker.py` 和 `retention_limits.py` 验证本机 POSIX 文件风险、配置加载、批次预算以及真实 PostgreSQL 上的部分受管线程行为。Case 保持 `blocked`，完整验收仍需执行绑定。

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

配置子进程屏蔽本地 dotenv，只保留显式测试环境，从产品环境模块和工厂创建维护器并直接调用维护周期。1001/101 运行工作负载使用产品写入和归档接口构造，准备时间包含实际 meta 提交成本。

## 会话删除清理增补

`test_deleted_conversation_reclaims_fresh_rounds_in_fixed_agent_directory` 验证未过期多轮文件按初始 Agent 目录清理及重复清理幂等。`test_deleted_conversation_waits_for_other_process_file_lock` 使用独立子进程持锁，验证先标记待删、锁释放后冷打开重试删除。

## PostgreSQL 与受管线程

`test_pg_schedule_policies_apply_on_managed_worker_midnight` 用真实 PostgreSQL 保存两个租户的清理策略，受管线程在启动巡检时保留到期候选，到北京时间零点再回收，核对同租户较新文件、另一租户文件及已清理执行的数据库指标。

`test_pg_confirmed_deletion_queues_and_retries_while_periodic_cleanup_is_disabled` 让受管线程查询真实 PostgreSQL 的会话状态。会话标记删除前保留归档，提交删除后提交至维护队列，另一个进程释放文件锁后重试。每项使用独占数据库，线程和锁持有进程退出后删除临时资源。

`test_pg_delete_http_commits_before_archive_cleanup_handoff` 通过 Management 单个和批量删除接口验证事务提交后才交接归档清理。批量请求包含另一租户会话。检查会话、聊天记录和执行摘要的软删除状态，等待文件锁释放后的清理回执。

## 尚缺的完整验收断言

AC-02/03 的附件生命周期、删除事务失败、队列满和重启补偿待验证。AC-04 的最近 Agent 分组、聊天定位与旧游标，以及 AC-06 的真实 PostgreSQL 跨用户多批清理仍依赖完整 HTTP 验收。QUERY-D2 保留固定截止、100 文件 HTTP 批次及正文读取中途权限变化断言。跨宿主共享卷语义由 DEPLOYMENT-D5 验证。
