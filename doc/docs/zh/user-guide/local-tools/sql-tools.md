---
title: SQL 数据库工具
---

# SQL 数据库工具

SQL 数据库工具组支持连接和查询 MySQL、PostgreSQL、SQL Server 等关系型数据库，让 AI 智能体能够直接读取和操作数据库数据。

## 工具清单

- `mysql_database`：连接 MySQL 数据库执行 SQL 查询
- `postgres_database`：连接 PostgreSQL 数据库执行 SQL 查询
- `mssql_database`：连接 SQL Server 数据库执行 SQL 查询

## 使用场景示例

- 从业务数据库中查询报表数据，供智能体分析汇总
- 跨数据库关联查询，获取分散在多个表中的关联信息
- 实时查询业务状态，为智能体提供最新数据参考

## 参数要求与行为

### 通用参数
- `sql`：要执行的 SQL 查询语句，必填
- `parameters`：参数化查询的参数值列表，可选
- `max_rows`：最大返回行数，默认 100
- `timeout`：查询超时时间（秒），默认 10

### 数据库连接参数

| 数据库 | 连接参数 |
|--------|----------|
| MySQL | `host`、`user`、`password`、`database`、`port`（默认 3306） |
| PostgreSQL | `host`、`user`、`password`、`database`、`port`（默认 5432） |
| SQL Server | `host`、`user`、`password`、`database`、`port`（默认 1433） |

### 安全限制
- 禁止执行 `DROP DATABASE`、`GRANT`、`REVOKE`、`CREATE USER`、`INTO OUTFILE`、`LOAD DATA INFILE` 等危险操作
- `UPDATE` 和 `DELETE` 语句必须包含 `WHERE` 子句
- 自动添加 `LIMIT` 限制返回行数

### 返回格式
```json
{
  "status": "success",
  "columns": ["id", "name", "email"],
  "rows": [[1, "张三", "zhang@example.com"]],
  "row_count": 1,
  "execution_time_ms": 45.23
}
```

## 操作指引

1. **准备数据库连接信息**：获取主机地址、端口、数据库名、用户名和密码
2. **配置工具**：在智能体工具配置中添加对应数据库工具，填写连接参数
3. **测试连接**：使用简单查询验证连接是否正常
4. **构造查询**：让智能体理解自然语言需求，生成对应 SQL 执行

## 安全与最佳实践

- 生产环境建议使用只读账号，限制操作权限
- 敏感信息如数据库密码可通过密钥管理服务存储
- 合理设置 `max_rows` 避免一次性返回过多数据
- 建议开启数据库连接的 SSL/TLS 加密选项

## 常见数据库连接示例

| 数据库 | 连接地址示例 | 参数占位符 |
|--------|-------------|------------|
| MySQL | `localhost:3306` | `?` |
| PostgreSQL | `localhost:5432` | `$1, $2, ...` |
| SQL Server | `localhost:1433` | `?` |

> 不同数据库的参数占位符格式不同，PostgreSQL 使用 `$1, $2` 格式，其他使用 `?`。
