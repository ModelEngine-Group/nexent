
### Requirement: 系统 SHALL 配置 Grafana 仪表板自动加载
系统 SHALL 确保 `docker/monitoring/grafana/provisioning/dashboards/dashboards.yml` 正确配置文件类型数据源，`path` 指向 `/var/lib/grafana/dashboards`，与 Docker Compose 卷挂载路径一致。Grafana 启动时 SHALL 自动加载 `nexent-llm-performance.json` 仪表板。

#### Scenario: 仪表板自动加载
- **WHEN** 执行 `bash docker/start-monitoring.sh` 启动监控服务
- **THEN** 访问 Grafana UI 时 SHALL 自动显示 "Nexent LLM Performance Dashboard" 仪表板，无需手动导入

### Requirement: 系统 SHALL 提供包含故障率的 Grafana 面板
系统 SHALL 在 Grafana 仪表板中包含以下面板：概览统计行（总请求数、错误率、故障率、今日成本）、时间序列行（请求耗时 P95/P50、Token 生成速率、TTFT、错误率 vs 故障率对比）、模型对比行（各模型平均耗时、各模型故障率对比 Bar Gauge、Token 吞吐量）、成本与告警行（成本趋势、成本占比饼图、告警统计表格）。故障率面板 SHALL 使用 `sum(rate(llm_failure_count_total[5m])) / sum(rate(llm_request_total[5m])) * 100` PromQL 查询。

#### Scenario: 故障率对比面板正确展示
- **WHEN** Prometheus 收集到多个模型的故障数据
- **THEN** "错误率 vs 故障率对比" 面板 SHALL 显示两条曲线：错误率（包含可恢复错误）和故障率（仅不可恢复故障），故障率 SHALL 始终 ≤ 错误率

#### Scenario: 模型故障率 Bar Gauge 使用阈值颜色
- **WHEN** 某模型故障率为 0.3%
- **THEN** Bar Gauge SHALL 显示绿色（< 0.5%）
- **WHEN** 某模型故障率为 0.8%
- **THEN** Bar Gauge SHALL 显示黄色（0.5% - 1%）
- **WHEN** 某模型故障率为 2.5%
- **THEN** Bar Gauge SHALL 显示红色（> 1%）

### Requirement: 系统 SHALL 提供仪表板模板变量
系统 SHALL 在 Grafana 仪表板中定义 `model_filter`（模型多选过滤）、`tenant_filter`（租户过滤）、`agent_filter`（智能体过滤）模板变量。所有面板的 PromQL 查询 SHALL 使用 `$model_filter` 等变量实现动态过滤。

#### Scenario: 使用模型过滤变量
- **WHEN** 用户在 Grafana 中选择 `model_filter` 为 `gpt-4o`
- **THEN** 所有面板 SHALL 仅显示 `gpt-4o` 模型的数据
