# 三平面解耦 + Management 竞争力规划（架构分析）

## 完成内容
- 结合代码完成 runtime / management / 运维监控 三条解耦主线的现状盘点与目标设计，产出 `deliverables/product-strategy/decoupling-management-competitiveness-2026-10-12.md`（与 10-08 竞分报告同目录衔接）。
- 关键代码证据：
  - 进程切分已完成：config_service(5010)=Management、runtime_service(5014)=Runtime、mcp(5011/5015)、northbound(5013)，helm 可独立 replicas。
  - 耦合热点 C1-C4：`management/services/agent/run.py`（2462 行执行引擎）挂在 runtime 进程；`runtime_proxy_service` 代理持有 SSE 会话；runtime 直读配置表（`agents/create_agent_info.py`）；可观测只有写侧（SDK monitor 2876 行 + buffer 直写 PG）读侧仅 2 路由、无前端、无 /metrics、无告警。
  - 可复用资产：agent_version_service（publish/rollback/compare/快照）、durable lease 调度、监控独立连接池、health 契约、三层配额框架（仅存储维度）。
- 结论：解耦重点不是再拆进程，而是代码归属、配置快照契约、监控读写分离；Observability 提为第四平面，审计+计量+trace 共用异步摄入管道。
- Management 补齐清单 M1-M7（P0 审计表化+token 计量 → P1 三维配额/灰度发布/身份/可观测管理面 → P2 运营级管理台/生态审核），含 3 个 ADR 与分阶段验收标准。

## 后续项
- P0a 边界清理可即刻启动（零功能变化）：run.py 迁移 + import 边界 CI 检查。
- 待出：run.py 依赖图迁移 PR 清单、Observability 摄入管道设计稿。
