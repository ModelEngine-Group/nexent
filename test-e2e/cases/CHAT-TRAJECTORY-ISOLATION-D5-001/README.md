# 轨迹隔离验证

本目录的脚本通过独占 PostgreSQL 数据库、实际 Ops 路由、真实请求签名中间件和本地轨迹存储验证部分隔离条件。

| 脚本断言 | 已覆盖范围 |
| --- | --- |
| `test_pg_authorized_actors_cannot_cross_scope_and_revocation_rechecks_cached_reference` | AC-01、AC-02 的管理员正向读取、非管理员及跨租户拒绝、角色撤销后旧正文引用失效 |
| `test_pg_tenant_move_revokes_old_reads_without_rebinding_the_trajectory` | AC-04 的租户迁移后新旧租户均无法读取旧归档，拒绝旧归属采集，恢复关系后允许读取 |
| `test_pg_manual_cleanup_is_restricted_to_the_authorized_tenant` | AC-05 的普通角色清理拒绝、OPS 范围拒绝、SU 显式指定租户后仅删除该租户归档 |

执行使用现有 PostgreSQL 配置和 `isolated_product_database`。用例创建独占数据库与轨迹根目录。清理阶段关闭 HTTP 客户端、回收受管线程、删除轨迹根目录、恢复进程数据库连接并删除独占数据库。

远端凭证脱敏、浏览器入口、文件替换竞态、完整跨归属正文和清理游标仍待覆盖。用例保持 `blocked`，完整验收保留原标准。
