# 智能体监控前端接入说明

对应个人分支 `codex/ops-monitoring-agent-sync`，已包含联调基线 `dcefefd2d`。本说明包含列表排序及调用量、Token 消耗量、成功率 Top 5 协议，页面联调尚待执行。

## 接口与请求参数

页面通过 Web／Gateway 使用以下地址，均为 `GET`，携带现有登录态 `Authorization: Bearer <session-token>`。Ops 内部路由去掉 `/api` 前缀；启用 Gateway 身份边界时，页面应通过 Gateway 调用。

| 页面用途 | 地址 | 响应位置 |
| --- | --- | --- |
| 指标卡片 | `/api/ops/v1/monitoring/agents/summary` | `data` 为执行指标；`tokens`、`token_status` 在顶层 |
| 明细列表及当前智能体总数 | `/api/ops/v1/monitoring/agents` | `data.items`、`data.total`、`data.current_agent_count` |
| 日趋势 | `/api/ops/v1/monitoring/agents/trends` | `data[]`，日期升序，每天包含执行指标、`tokens` 和 `token_status` |
| Top 5 排行 | `/api/ops/v1/monitoring/agents/rankings` | `data[]`，最多五个有效资源，按 `metric` 降序 |

四者共用 `start_date`、`end_date`（必填，`YYYY-MM-DD`，首尾均包含，最多 366 天），以及可选的 `tenant_id`、`group_ids`、`agent_id`。日期按部署的监控时区解释。多用户组使用重复参数，如 `group_ids=12&group_ids=13`，按执行发起时的组快照取 OR，匹配多个组仍只计一次。

OPS 角色只能读取自己的租户；省略 `tenant_id` 时仍限定当前租户，指定其他租户返回 403。SU 可指定租户，或省略以查看全租户。两者均需 `ops.dashboard:read` 权限。普通用户不具备此访问权限。

| 仅列表支持的参数 | 约定 |
| --- | --- |
| `page` / `page_size` | 从 1 开始；默认 1 / 20；每页最多 100 条 |
| `search` | 最长 100 字符；当前名称或展示名称，不区分大小写 |
| `sort_by` | `execution_count`（默认）、`avg_duration_ms`、`avg_ttft_ms`、`total_tokens`、`success_rate` |
| `descending` | `true`（默认）降序；`false` 升序 |

排序在权限与条件筛选、资源汇总之后执行，再分页。Token 按精确整数比较；跨日成功率先合并成功／失败次数，再计算比率。空值在升降序中均置后；相同值依次按租户 ID、数值型智能体 ID 升序。前端切换筛选或排序时应重新请求第 1 页，不对当前页自行排序。

刷新时重新 GET 当前筛选下的这些接口，读取最新已发布结果；GET 不触发补算或等待发布。当前没有智能体专用的刷新任务接口。排行与北向接口的交付状态见文末。

## 页面字段映射

| 页面字段 | 汇总／列表／趋势字段 | 展示与口径 |
| --- | --- | --- |
| 智能体总数 | 列表 `data.current_agent_count` | 当前未删除的草稿资源数；受租户、单智能体筛选影响，不随日期、发起用户组或名称搜索变化。不要使用列表 `data.total` 或当前页长度代替 |
| 列表总条数 | 列表 `data.total` | 搜索后的资源条数，包含只有历史统计的资源，用于分页 |
| 智能体名称与行标识 | 列表项 `display_name`、`name`、`agent_id`、`tenant_id` | 名称可缺失；可回退展示 ID。全租户列表用 `(tenant_id, agent_id)` 标识行 |
| 当前资源标记 | 列表项 `is_current` | 历史资源为 `false`，可能没有名称、模型及当前配置元数据 |
| 调用量 | 汇总 `data.execution_count`；列表项 `metrics.execution_count`；趋势项 `execution_count` | 主、子执行各计一次；取消、执行中等仍可有调用量，不能用成功数加失败数代替调用量 |
| 成功数／失败数／成功率 | 对应指标对象的 `succeeded_count` / `failed_count` / `success_rate` | 成功率为 0～1，页面乘 100 展示百分比；已确认终态超时失败计失败，取消／进行中／未知不入分母；零分母为 `null` |
| 平均执行耗时 | 对应指标对象的 `avg_duration_ms`，样本数 `duration_sample_count` | 单位毫秒，按轨迹的完整执行边界，监控与轨迹复用同一份计时；轨迹关闭仍可采集。无有效样本为 `null` |
| 首 Token 耗时 | 对应指标对象的 `avg_ttft_ms`，样本数 `ttft_sample_count` | 实际执行起点到首次有效回答片段，单位毫秒；工具、思考、空片段、重连回放不计。样本数与执行耗时独立 |
| 输入／输出／总 Token | 汇总顶层、列表项、趋势项的 `tokens.input_tokens` / `output_tokens` / `total_tokens` | 各为下述用量对象。归实际发出模型请求的智能体，父子合计不重复累计；按模型请求开始日归属，可能与执行指标所在日不同 |
| 执行数据更新／覆盖／滞后 | 响应顶层 `data_as_of` / `coverage_state` / `is_stale` | 四个接口均返回；趋势每个日期另有 `coverage_state` |
| Token 数据更新／覆盖／滞后 | `token_status.data_as_of` / `coverage_state` / `is_stale` | 汇总、列表、趋势及 Token 排行顶层均有；相应资源项和趋势项也有。调用量、成功率排行不附带 Token 数据或状态 |

`metrics` 整体可能为 `null`，其中单个指标也可能为 `null`；页面显示“—”，真实零值显示 0。仅有模型归属用量的历史资源可以有 Token 而 `metrics=null`。

每种 Token 的用量对象包含 `value`（十进制整数字符串或 `null`）、`known_count`、`eligible_count`、`coverage_rate`（0～1 或 `null`）。覆盖率按有实际用量的模型请求数计算，不是成功率。部分缺失时 `value` 为已知用量之和，应保留覆盖提示；全部缺失时 `value=null`，与已知 `"0"` 不同。无覆盖时该字段对象本身也可能是 `null`。前端保留字符串精度，格式化时避免转成可能丢精度的 `Number`。

`coverage_state` 为 `covered` / `partial` / `uncovered`；`is_stale=true` 表示写入或发布仍有滞后，仍可能返回上次已发布值。`is_stale=false` 不代表覆盖完整。`data_as_of` 是查询所覆盖发布数据的保守源快照时间，可为空，不是页面请求完成时间。执行指标和 Token 不保证同一发布时间，不能把两套状态合成一个。

## 请求／响应示例

以下为统一字段的协议示例，非本轮新增实测。使用租户 `example`、智能体 21 和两天窗口，响应中的时间为示例；缺失首 Token 保留空值。页面同样支持去掉 `agent_id` 查看全部资源。

汇总请求：

```http
GET /api/ops/v1/monitoring/agents/summary?tenant_id=example&start_date=2026-11-18&end_date=2026-11-19&group_ids=12&agent_id=21
Authorization: Bearer <session-token>
```

```json
{
  "data": {
    "execution_count": 4, "succeeded_count": 1, "failed_count": 3, "success_rate": 0.25,
    "avg_duration_ms": 10.0, "duration_sample_count": 4,
    "avg_ttft_ms": null, "ttft_sample_count": 0
  },
  "data_as_of": "2026-11-20T04:01:48+00:00", "coverage_state": "partial", "is_stale": false,
  "tokens": {
    "input_tokens": {"value": "14", "known_count": 2, "eligible_count": 2, "coverage_rate": 1.0},
    "output_tokens": {"value": "0", "known_count": 2, "eligible_count": 2, "coverage_rate": 1.0},
    "total_tokens": {"value": "14", "known_count": 2, "eligible_count": 2, "coverage_rate": 1.0}
  },
  "token_status": {"data_as_of": "2026-11-20T04:01:49+00:00", "coverage_state": "partial", "is_stale": false}
}
```

列表请求；成功率升序改成 `sort_by=success_rate&descending=false`：

```http
GET /api/ops/v1/monitoring/agents?tenant_id=example&start_date=2026-11-18&end_date=2026-11-19&group_ids=12&agent_id=21&sort_by=total_tokens&descending=true&page=1&page_size=20
Authorization: Bearer <session-token>
```

```json
{
  "data": {
    "items": [{
      "tenant_id": "example", "agent_id": 21, "name": "sort-21", "display_name": null,
      "model_ids": null, "configured_group_ids": [12, 99], "current_version_no": null, "is_current": true,
      "metrics": {
        "execution_count": 4, "succeeded_count": 1, "failed_count": 3, "success_rate": 0.25,
        "avg_duration_ms": 10.0, "duration_sample_count": 4, "avg_ttft_ms": null, "ttft_sample_count": 0
      },
      "tokens": {
        "input_tokens": {"value": "14", "known_count": 2, "eligible_count": 2, "coverage_rate": 1.0},
        "output_tokens": {"value": "0", "known_count": 2, "eligible_count": 2, "coverage_rate": 1.0},
        "total_tokens": {"value": "14", "known_count": 2, "eligible_count": 2, "coverage_rate": 1.0}
      },
      "token_status": {"data_as_of": "2026-11-20T04:01:49+00:00", "coverage_state": "partial", "is_stale": false}
    }],
    "total": 1, "current_agent_count": 1
  },
  "data_as_of": "2026-11-20T04:01:48+00:00", "coverage_state": "partial", "is_stale": false,
  "token_status": {"data_as_of": "2026-11-20T04:01:49+00:00", "coverage_state": "partial", "is_stale": false}
}
```

日趋势请求：

```http
GET /api/ops/v1/monitoring/agents/trends?tenant_id=example&start_date=2026-11-18&end_date=2026-11-19&group_ids=12&agent_id=21
Authorization: Bearer <session-token>
```

```json
{
  "data": [
    {
      "statistic_date": "2026-11-18", "coverage_state": "partial",
      "execution_count": 1, "succeeded_count": 1, "failed_count": 0, "success_rate": 1.0,
      "avg_duration_ms": 10.0, "duration_sample_count": 1, "avg_ttft_ms": null, "ttft_sample_count": 0,
      "tokens": {
        "input_tokens": {"value": "4", "known_count": 1, "eligible_count": 1, "coverage_rate": 1.0},
        "output_tokens": {"value": "0", "known_count": 1, "eligible_count": 1, "coverage_rate": 1.0},
        "total_tokens": {"value": "4", "known_count": 1, "eligible_count": 1, "coverage_rate": 1.0}
      },
      "token_status": {"data_as_of": "2026-11-20T04:01:49+00:00", "coverage_state": "partial", "is_stale": false}
    },
    {
      "statistic_date": "2026-11-19", "coverage_state": "covered",
      "execution_count": 3, "succeeded_count": 0, "failed_count": 3, "success_rate": 0.0,
      "avg_duration_ms": 10.0, "duration_sample_count": 3, "avg_ttft_ms": null, "ttft_sample_count": 0,
      "tokens": {
        "input_tokens": {"value": "10", "known_count": 1, "eligible_count": 1, "coverage_rate": 1.0},
        "output_tokens": {"value": "0", "known_count": 1, "eligible_count": 1, "coverage_rate": 1.0},
        "total_tokens": {"value": "10", "known_count": 1, "eligible_count": 1, "coverage_rate": 1.0}
      },
      "token_status": {"data_as_of": "2026-11-20T04:01:49+00:00", "coverage_state": "covered", "is_stale": false}
    }
  ],
  "data_as_of": "2026-11-20T04:01:48+00:00", "coverage_state": "partial", "is_stale": false,
  "token_status": {"data_as_of": "2026-11-20T04:01:49+00:00", "coverage_state": "partial", "is_stale": false}
}
```

缺失用量的字段示例为 `{"value":null,"known_count":0,"eligible_count":1,"coverage_rate":0.0}`；确认零次请求且覆盖完整时为 `{"value":"0","known_count":0,"eligible_count":0,"coverage_rate":null}`。无成功率样本时，成功数和失败数可均为 0，但 `success_rate=null`。

错误状态沿用现有接口：未登录或 Gateway 身份校验失败 401，无权限或越租户 403，参数错误 422，监控依赖不可用 503。不要将错误响应当作零指标。

## Top 5 排行

现有排行接口增加 `metric`，可选 `execution_count`（默认）、`total_tokens`、`success_rate`。省略时调用量 Top 5 的行为和响应保持不变。排行复用相同授权、筛选和资源汇总，固定降序；不使用列表的 `sort_by`、`descending` 或分页参数。

总 Token 按已发布的已知用量之和比较，保留用量覆盖率；成功率按合并后的成功数和失败数计算。成功率排行项额外返回 `metrics.success_sample_count`，等于 `succeeded_count + failed_count`，不是调用量；不设额外的最小样本门槛。

空值资源不入榜，已知零值可入榜；相同值按租户 ID、智能体 ID 升序。少于五个有效资源按实际数量返回，全部无效返回 `data: []`。只有 Token 排行读取模型已发布用量并返回 `tokens`、`token_status`；其余两类排行不依赖模型统计。

以下示例筛选单个智能体，因此最多一条；省略了资源名称等元数据，其余字段位置与列表一致。日期和数值与上面的协议示例一致，并非额外实测记录。

```http
GET /api/ops/v1/monitoring/agents/rankings?tenant_id=example&start_date=2026-11-18&end_date=2026-11-19&group_ids=12&agent_id=21&metric=total_tokens
Authorization: Bearer <session-token>
```

```json
{
  "data": [{
    "tenant_id": "example", "agent_id": 21,
    "metrics": {"execution_count": 4, "succeeded_count": 1, "failed_count": 3, "success_rate": 0.25, "avg_duration_ms": 10.0, "duration_sample_count": 4, "avg_ttft_ms": null, "ttft_sample_count": 0},
    "tokens": {
      "input_tokens": {"value": "14", "known_count": 2, "eligible_count": 2, "coverage_rate": 1.0},
      "output_tokens": {"value": "0", "known_count": 2, "eligible_count": 2, "coverage_rate": 1.0},
      "total_tokens": {"value": "14", "known_count": 2, "eligible_count": 2, "coverage_rate": 1.0}
    },
    "token_status": {"data_as_of": "2026-11-20T04:01:49+00:00", "coverage_state": "partial", "is_stale": false}
  }],
  "data_as_of": "2026-11-20T04:01:48+00:00", "coverage_state": "partial", "is_stale": false,
  "token_status": {"data_as_of": "2026-11-20T04:01:49+00:00", "coverage_state": "partial", "is_stale": false}
}
```

```http
GET /api/ops/v1/monitoring/agents/rankings?tenant_id=example&start_date=2026-11-18&end_date=2026-11-19&group_ids=12&agent_id=21&metric=success_rate
Authorization: Bearer <session-token>
```

```json
{
  "data": [{
    "tenant_id": "example", "agent_id": 21,
    "metrics": {"execution_count": 4, "succeeded_count": 1, "failed_count": 3, "success_rate": 0.25, "avg_duration_ms": 10.0, "duration_sample_count": 4, "avg_ttft_ms": null, "ttft_sample_count": 0, "success_sample_count": 4}
  }],
  "data_as_of": "2026-11-20T04:01:48+00:00", "coverage_state": "partial", "is_stale": false
}
```

## 联调状态

已有排序阶段的验证记录保留。本轮排行相关单测 166 项、正式智能体链路用例 23 项通过，覆盖筛选、跨日汇总、缺失值、已知零值、同值顺序、不足五条、有效样本数及默认调用量排行兼容。Token 排行也覆盖仅有历史用量而无执行指标的资源。

待联调：页面真实登录经 Web／Gateway 调用以上四个接口，核对筛选、单位、百分比、空值、两套更新状态与刷新行为；团队部署环境中的模型服务、真实租户和用户组对账留在联调阶段。现有主子智能体、smolagents／九问验证证据保留；九问文本协议回退、混合引擎树及专门的已确认超时失败实跑不在已有实测证据内，这些是证据边界，本轮不新增验收要求或补测。

| 交付项 | 当前状态 |
| --- | --- |
| 调用量 Top 5 | 已实现：`GET /api/ops/v1/monitoring/agents/rankings`，按 `execution_count` 降序 |
| Token 消耗量 Top 5 | 已实现：同一排行接口传 `metric=total_tokens` |
| 调用成功率 Top 5 | 已实现：同一排行接口传 `metric=success_rate`，返回有效样本数 |
| 北向接口 | 暂缓 |
