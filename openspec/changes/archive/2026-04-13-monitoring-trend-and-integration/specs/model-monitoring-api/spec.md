## 新增需求

### 需求：聚合趋势端点
后端 SHALL 提供 `GET /monitoring/trend` 端点，返回时间序列趋势数据。SHALL 接受可选查询参数：`interval`（1h/6h/1d/7d）、`time_range`（24h/7d/30d）和 `model_id`（可选）。

#### 场景：获取所有模型的聚合趋势
- **WHEN** 客户端发送 `GET /monitoring/trend?time_range=24h&interval=1h` 且不含 `model_id`
- **THEN** 端点返回趋势数据点列表，每个点包含聚合指标（request_count 求和、error_rate 求平均、failure_rate 求平均、avg_duration 求平均、cost 求和、tokens 求和）以及 `models` 对象包含分模型明细

#### 场景：获取单一模型的趋势
- **WHEN** 客户端发送 `GET /monitoring/trend?time_range=24h&interval=1h&model_id=model-1`
- **THEN** 端点返回仅包含该模型指标的趋势数据点列表，不含 `models` 分模型明细对象

### 需求：趋势端点认证
聚合趋势端点 SHALL 要求通过 `authorization` 头进行认证，使用与其他所有监控端点相同的 `get_current_user_id` 模式。

#### 场景：未认证请求被拒绝
- **WHEN** 客户端发送 `GET /monitoring/trend` 且不含 authorization 头
- **THEN** 端点返回 HTTP 401 或抛出认证错误

#### 场景：已认证请求成功
- **WHEN** 客户端发送 `GET /monitoring/trend` 且含有效 authorization 头
- **THEN** 端点返回 `ConversationResponse(code=0, message="success", data=[...])`
