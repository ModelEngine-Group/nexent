# Nexent 规格与性能测试方案

## 1. 概述

本文档定义 Nexent 平台的的的规格参数验证的的与与与性能基准测试与与方案。

### 测试环境要求

| 组件     | 要求                                       |
| ------ | ---------------------------------------- |
| 后端服务   | 已启动的 Nexent 后端 (FastAPI)                 |
| 数据库    | MySQL/PostgreSQL 实例（测试专用）                |
| Python | >= 3.11，安装依赖：sqlalchemy, aiohttp, psutil |
| 访问凭证   | 管理员 token + 测试租户 ID                      |

### 数据隔离策略

所有测试数据使用 perf\_test\_ 前缀，回滚脚本统一按前缀删除。

***

## 2. 规格参数测试

### 2.1 规格参数表

| 编号   | 规格参数          | 参考值    | 验证点          |
| ---- | ------------- | ------ | ------------ |
| S-01 | 最大租户数         | 100    | 第101个创建应失败   |
| S-02 | 单租户最大用户数      | 10,000 | 第10001个创建应失败 |
| S-03 | 单租户最大用户组数     | 1,000  | 第1001个创建应失败  |
| S-04 | 单租户管理员数       | 1,000  | 第1001个设置应失败  |
| S-05 | 单租户 Agent 数量  | 1,000  | 第1001个创建应失败  |
| S-06 | 单会话对话轮数       | 100    | 第101条应被拒绝或截断 |
| S-07 | 单用户历史会话条数     | 1,000  | 第1001个创建应失败  |
| S-08 | 单租户知识库数量      | 10,000 | 第10001个创建应失败 |
| S-09 | 单用户下知识库数量     | 1,000  | 第1001个创建应失败  |
| S-10 | 单租户 MCP 服务数量  | 1,000  | 第1001个创建应失败  |
| S-11 | 单租户 Skill 数量  | 1,000  | 第1001个创建应失败  |
| S-12 | 单 Agent 记忆条目数 | 10,000 | 第10001条应失败   |

### 2.2 测试方法

采用   直接数据库写入 + API 验证   模式：

1. 数据准备：SQLAlchemy 批量 INSERT 创建 N 条数据（N = 上限值）
2. 验证：通过 API 尝试创建第 N+1 条，断言返回错误
3. 回滚：使用统一前缀删除所有测试数据

### 2.3 通过标准

- 第 N+1 次创建请求返回明确的错误（400/403/409）
- 错误信息包含具体的限制说明
- 数据库中实际存储数量 <= 上限值

***

## 3. 性能参数测试

### 3.1 性能指标表

| 编号   | 性能参数            | 测量方法                           | 采集指标              |
| ---- | --------------- | ------------------------------ | ----------------- |
| P-01 | 单 Agent 最大并发执行数 | 对同一 Agent 发送 50 个并发 /agent/run | 成功率、P95 延迟、错误率    |
| P-02 | 最大并发 Agent 执行数  | 200 个不同 Agent 同时 /agent/run    | 成功率、P95 延迟、CPU/内存 |
| P-03 | 平台 API 速率限制     | 短时间窗口内持续请求                     | 429 比例、RPM        |

### 3.2 监控指标

| 指标       | 采集方式                     |
| -------- | ------------------------ |
| CPU 使用率  | psutil.cpu\_percent()    |
| 内存使用率    | psutil.virtual\_memory() |
| API 响应延迟 | 请求耗时统计                   |
| 错误率      | HTTP 4xx/5xx 比例          |

### 3.3 通过标准

| 指标       | 目标               |
| -------- | ---------------- |
| 并发成功率    | >= 95%           |
| P95 响应延迟 | <= 30s（简单 Agent） |
| API 错误率  | <= 5%            |
| CPU 峰值   | <= 80%           |
| 内存峰值     | <= 系统可用 80%      |

***

## 4. 执行流程

\`

1. 初始化测试环境（创建测试租户、管理员）
2. 执行规格测试 test\_spec\_limits.py -> spec\_results.json
3. 执行性能测试 test\_performance.py -> perf\_results.json
4. 回滚数据 rollback\_test\_data.py
   \`

## 5. 脚本说明

| 脚本                      | 功能     | 需回滚   |
| ----------------------- | ------ | ----- |
| test\_spec\_limits.py   | 规格参数验证 | 是     |
| test\_performance.py    | 性能基准测试 | 是     |
| rollback\_test\_data.py | 清理测试数据 | 自身即回滚 |

### 运行命令

\`ash
export NEXENT\_BASE\_URL=<http://localhost:8080>
export NEXENT\_ADMIN\_TOKEN=\<admin\_token>
export NEXENT\_DB\_URL=mysql://user:pass\@localhost:3306/nexent

python test/perf/test\_spec\_limits.py
python test/perf/test\_performance.py
python test/perf/rollback\_test\_data.py
\`

<br />

### 测试脚本

脚本 功能 测试原理 test\_spec\_limits.py S-01 \~ S-12 规格限制验证 SQLAlchemy 批量写入 + API 溢出验证 ：先用 SQL 直写 N 条数据填满表，再通过 HTTP API 创建第 N+1 条，断言返回 4xx 错误。比逐条 API 创建快 100 倍以上。 test\_performance.py P-01 \~ P-03 性能基准 线程池并发 + psutil 监控 ：ThreadPoolExecutor 并发发送 /agent/run 请求，统计 P50/P95/P99 延迟、成功率、429 比例，同时后台线程采集 CPU/内存占用。 rollback\_test\_data.py 测试数据回滚 按 perf\_test\_ 前缀级联删除 ：按依赖关系顺序删除 18+ 张表（agent→memory→conversation→user→tenant），幂等、支持 --dry-run 。

### 🔑 关键设计决策

1. 数据隔离 ：所有测试数据用 perf\_test\_ 前缀，回滚时 DELETE FROM ... WHERE id LIKE 'perf\_test\_%' ，不会误伤正式数据
2. 批量写入 ：规格测试用 SQLAlchemy bulk\_insert 替代 API 逐条创建，10,000 条数据写入从小时级降到秒级
3. 双路径验证 ：API 验证（测试实际业务限制）+ 数据库验证（测试存储层上限）
4. 幂等回滚 ： rollback\_test\_data.py 可重复执行，残留数据自动清理
5. 实时监控 ：性能测试用 psutil 后台线程采集 CPU/内存，与请求指标同步输出

### 📝 使用方法

```
# 1. 设置环境变量
export NEXENT_BASE_URL=http://localhost:8080
export NEXENT_ADMIN_TOKEN=<admin_token>
export NEXENT_DB_URL=mysql://user:pass@localhost:3306/nexent

# 2. 运行规格测试（约 30-60 分钟）
python test/perf/test_spec_limits.py
python test/perf/test_spec_limits.py --only S-01 S-02  # 可选：只跑指定
项

# 3. 运行性能测试（约 10-20 分钟）
python test/perf/test_performance.py --agents 200 --concurrency 50

# 4. 回滚测试数据（必执行！）
python test/perf/rollback_test_data.py --dry-run  # 先预览
python test/perf/rollback_test_data.py           # 实际删除
```

### ⚠️ 注意事项

- 规格测试参考值（100、10000 等）可在脚本顶部 SPEC\_LIMITS 字典中修改
- 性能测试参数（并发数、时长）可通过命令行参数调整
- 建议在独立测试环境执行，避免对业务数据库造成压力
- 若测试中途中断，直接运行 rollback\_test\_data.py 即可清理残留

## 6. 注意事项

1. 建议在测试环境执行，避免数据库压力影响正式业务
2. 测试数据使用 perf\_test\_ 前缀，回滚脚本严格按前缀删除
3. 回滚脚本幂等，支持重复执行
4. 测试中断后直接运行回滚脚本即可清理残留数据

