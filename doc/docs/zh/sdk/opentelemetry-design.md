# Nexent OpenTelemetry 可观测性设计

生成日期：2026-05-06
基准分支：当前 OpenTelemetry 功能分支

## 可观测性基础

可观测性关注的是系统在运行过程中是否能够被理解和定位问题。相比只回答“系统是否还活着”的传统监控，可观测性更强调从运行时信号反推出系统内部状态，帮助研发和运维回答以下问题：

- 当前请求为什么慢？
- Agent 在哪一步失败？
- 大模型调用耗时、首 token 时间和 token 速率是否异常？
- 某个用户、会话或 Agent 的完整执行链路是什么？
- 问题发生时有哪些输入、输出、工具调用和错误上下文？

业界通常把可观测性拆成三大支柱：Metrics、Logs、Traces。三者解决的问题不同，需要组合使用。

| 支柱 | 核心问题 | 典型数据 | 适合场景 | 在 Nexent 中的作用 |
|------|----------|----------|----------|--------------------|
| Metrics | “整体是否异常？” | 计数器、直方图、速率、分位数 | 看趋势、告警、容量评估、SLO/SLA | 统计 LLM 请求耗时、TTFT、token 速率、错误数、Agent step/tool 调用数 |
| Logs | “当时发生了什么？” | 按时间顺序输出的文本或结构化事件 | 查看异常上下文、排查单点错误、审计关键行为 | 保留运行日志，并通过 span event/attribute 记录关键 Agent、LLM、Tool 事件 |
| Traces | “一次请求经历了哪些步骤？” | trace、span、span event、上下游关系 | 分布式调用链、流式 Agent 执行链路、跨服务耗时定位 | 串联 HTTP 接口、Agent run、LLM generate、Tool call 和最终答案 |

三大支柱之间不是替代关系。Metrics 适合发现问题，例如某段时间 LLM 错误数上升；Traces 适合定位问题，例如找到某次 `agent.run` 卡在某个 tool；Logs 适合补充细节，例如错误堆栈、原始提示词摘要或工具返回内容。对于 LLM Agent 场景，单纯的 HTTP 接口指标不足以解释 Agent 行为，因此必须把 Agent、LLM、Tool 等业务语义写入 trace 层级中。

## 智能体可观测性行业洞察

截至当前，智能体可观测性正在从传统 APM 的“接口是否健康、服务是否变慢”，扩展到“智能体为什么这样决策、哪一步引入了错误上下文、工具或检索是否误导了模型、成本和质量是否可控”。这类系统的核心难点不是单次 LLM 调用本身，而是一次用户请求会跨越路由、记忆、规划、检索、工具调用、模型生成、最终答案和反馈评价等多个阶段，并且每个阶段都可能影响最终结果。

智能体可观测性的接入路径通常有几类：

| 接入路径 | 典型方式 | 适合场景 | 需要注意 |
|----------|----------|----------|----------|
| 平台 SDK 直连 | Langfuse SDK、LangSmith SDK、Datadog / New Relic SDK、框架 callback | 快速接入某个平台的专有能力，例如 prompt 管理、评分、评估、成本分析 | 平台绑定更强，后续迁移或双写到其他后端成本较高 |
| OpenTelemetry SDK 直连平台 OTLP endpoint | 应用直接用 OTLP HTTP/gRPC exporter 写入 Phoenix、Langfuse、LangSmith、Datadog 等兼容入口 | 希望保留 OTel 埋点模型，同时减少本地组件 | 鉴权、脱敏、采样、多后端分发逻辑会落在应用配置或平台侧 |
| OpenTelemetry Collector 中转 | 应用只写 Collector，由 Collector 转发到 Phoenix、Langfuse、LangSmith、Grafana Tempo、Zipkin 或企业 APM | 需要统一批处理、采样、脱敏、header 注入、多后端转发和私有化部署 | 多一个运行组件，需要维护 Collector 配置和部署可用性 |
| 平台 agent / 网关中转 | Datadog Agent、New Relic agent 或企业内部 telemetry gateway | 企业已有 APM 基础设施、权限、网络出口和审计要求明确 | 数据模型可能会被平台转换，AI 语义字段需要确认兼容性 |

从知名 Agent/LLM 框架和平台的公开文档看，可观测性方案已经明显分成两层：框架或平台负责表达 Agent/LLM 运行时语义，OpenTelemetry/OTLP 负责把 trace、metric、log 导出到后端。差异主要在于：有些框架原生使用 OTel，有些通过 OpenInference/OpenLIT/OpenLLMetry 等 instrumentation 转成 OTel span，有些则先进入自有 tracing SDK，再通过 processor、callback 或平台集成转发。

| Agent / 平台 | 原生可观测性能力 | 常用观测框架 / SDK | OTel / OTLP 路径 | 语义覆盖重点 | 局限与注意 |
|--------------|------------------|--------------------|------------------|--------------|------------|
| LangChain / LangGraph | LangSmith tracing、thread、feedback、evaluation，面向 chain、graph、run 的调试和评估 | LangSmith SDK、LangSmith OTel、OpenTelemetry SDK、Collector | `LANGSMITH_OTEL_ENABLED=true` 后可生成 OTel spans；LangSmith 提供 OTLP traces endpoint；也支持经 Collector fan-out 到多后端 | chain、graph node、LLM、tool、retriever、thread、feedback、eval | LangSmith 语义最完整；若只使用通用 OTel 后端，需要自行补齐 graph/thread/eval 维度 |
| LlamaIndex | 内置 instrumentation/callback 体系，官方观测页覆盖 LlamaTrace、Phoenix、SigNoz、MLflow、Langfuse、OpenLLMetry、OpenLIT、AgentOps 等 | OpenInference LlamaIndex instrumentation、LlamaTrace/Phoenix、Langfuse、OpenLLMetry、OpenLIT、MLflow | Phoenix/LlamaTrace、SigNoz、Langfuse、OpenLIT 等路径都可通过 OTel/OTLP 导出；常见方式是 `openinference-instrumentation-llama-index` + OTLP exporter | RAG query engine、retriever、index、agent workflow、LLM、tool、token、latency | RAG 语义强，但不同集成对属性映射和评估能力不完全一致 |
| OpenAI Agents SDK | SDK 内置 tracing，默认记录 runner、agent、generation、function tool、guardrail、handoff、speech 等 span | OpenAI Traces dashboard、custom trace processor、外部 tracing processors（Phoenix、MLflow、LangSmith、Langfuse、AgentOps、Datadog 等） | 默认不是 OTel span，而是 OpenAI Agents tracing 模型；要进入 OTLP 通常需要外部 tracing processor 或自定义 processor 做 OTel/OTLP 适配 | agent run、LLM generation、function tool、handoff、guardrail、自定义事件、会话分组 | Agent 语义完整，但与标准 OTel 数据模型之间需要转换层；敏感输入输出默认可能被采集，需显式配置 |
| AutoGen | 新版 AutoGen 内置 tracing/observability，运行时支持 OpenTelemetry，并遵循 agent/tool 与 GenAI 语义约定；旧版 0.2 主要是 logging 和 partner providers | OpenTelemetry SDK、OTLP exporter、Jaeger/Zipkin、OpenAI instrumentor、AgentOps 等 | 可直接配置 OTel `TracerProvider` 和 OTLP exporter，把 AgentChat/GroupChat 运行时事件发到 OTel 兼容后端 | 多 Agent 消息、agent runtime、tool、LLM 调用、group chat、消息元数据 | 版本差异明显；需确认使用的是新版 AgentChat/Core 还是旧版 0.2 logging 集成 |
| Dify | 产品内置 Monitoring Dashboard 和 Run History，可查看应用指标、workflow/node tracing；外部监控支持 Langfuse、LangSmith | Dify 内置监控、Langfuse integration、LangSmith integration | 官方文档主要体现为平台到 Langfuse/LangSmith 的集成和字段映射 | app、workflow/chatflow、node、message、dataset retrieval、tool、moderation、token、user/session | 产品语义强，适合低代码应用监控；开放 OTLP 可迁移性弱于原生 OTel instrumentation |
| CrewAI | CrewAI AMP 内置 tracing，可通过 `tracing=True` 或 `CREWAI_TRACING_ENABLED=true` 追踪 crew/flow；官方观测页列出多种外部平台 | CrewAI AMP、OpenLIT、Langfuse、LangSmith OTel、Langtrace、Arize Phoenix、MLflow、Opik、Weave、Portkey 等 | OpenLIT 是 OTel-native，可配置 `OTEL_EXPORTER_OTLP_ENDPOINT`；LangSmith/CrewAI 集成使用 `opentelemetry-instrumentation-crewai`；Langfuse 可通过 OpenInference CrewAI instrumentation 产生 OTel spans | agent、task、crew、flow、tool、LLM、任务序列、成本、延迟 | 集成选择多但语义不完全统一；CrewAI AMP 与第三方 OTel 路径需要明确数据归属和脱敏策略 |
| smolagents | 官方“Inspecting runs with OpenTelemetry”明确采用 OpenTelemetry 标准记录 agent runs | `smolagents[telemetry]`、OpenInference `SmolagentsInstrumentor`、Phoenix、Langfuse、OpenTelemetry SDK | 使用 `SmolagentsInstrumentor` 生成 OTel spans，可通过 `OTLPSpanExporter` 写 Phoenix，也可通过 Langfuse/其他 OTel 兼容平台接收 | CodeAgent、ToolCallingAgent、managed agents、工具调用、LLM 交互、多步执行 | 轻量、OTel 路径清晰；复杂评估、反馈和产品内权限仍依赖后端平台补齐 |

从对比结果看，行业并不是简单地“统一使用某一个观测平台”，而是在向三种形态收敛：

- 框架原生 OTel：AutoGen 新版、smolagents、Vercel AI SDK、Semantic Kernel 这类更容易直接进入 OTLP/Collector/企业 APM。
- OTel instrumentation 桥接：LlamaIndex、CrewAI、LangChain/LangGraph 常通过 OpenInference、OpenLIT、OpenLLMetry、LangSmith OTel 等层把框架语义转成 OTel span。
- 平台私有 tracing 再导出：OpenAI Agents SDK、Dify、CrewAI AMP 这类先保留自有产品语义，再通过 processor、callback、外部平台集成或字段映射与 OTel/LLMOps 平台互通。

对 Nexent 来说，比较稳妥的策略是：核心埋点直接生成 OpenTelemetry span，并在 span 属性上兼容 OpenInference、OpenTelemetry GenAI、Langfuse/LangSmith 等主流语义；对外只承诺 OTLP 可导出，不把业务链路绑定到某一个平台 SDK。这样既能接入 Phoenix/Langfuse/LangSmith 这类 LLMOps 平台，也能接入 Grafana Tempo、Zipkin、Datadog、New Relic、Elastic、Honeycomb 等通用或企业级观测后端。

因此，智能体可观测性的关键不是选择一个“唯一平台”，也不是强制所有链路都经过 Collector，而是先把遥测数据建模成可迁移、可组合、可扩展的结构：底层用标准 trace/metric/log 表达运行路径和性能，上层用 Agent/LLM/Tool/Retriever/Session/User/Evaluation 等语义补足业务解释能力。这样既能直连 Phoenix、Langfuse、LangSmith 等 AI 可观测平台，也能通过 Collector 接入 Grafana Tempo、Zipkin 或企业已有 APM，避免在产品早期把监控能力锁死在某个供应商或某套私有 SDK 中。

## 为什么使用 OpenTelemetry

```mermaid
timeline
    title 可观测性框架与协议演进时间线
    2010 : Google 发表 Dapper 论文
    2012 : Prometheus 在 SoundCloud 起步
    2015 : Jaeger 在 Uber 内部形成并发展
    2016 : OpenTracing 进入 CNCF
    2017 : OpenCensus 推广 tracing + stats/metrics + tags
    2019 : OpenTracing 与 OpenCensus 合并为 OpenTelemetry
    2021 : OpenTelemetry 晋升 CNCF Incubating
    2022 : OpenTracing 被归档；OpenTelemetry Metrics 发布 RC 并进入 GA 周期
    2023 : OpenCensus 于 7 月 31 日后停止维护
    2024 : Prometheus 持续增强对 OpenTelemetry/OTLP 的互操作
    2026 : OpenTelemetry 于 5 月 11 日 Graduated；OpenTracing compatibility 于 3 月被 deprecated
```

OpenTelemetry 是当前主流的可观测性开放标准，提供统一的 API、SDK、语义约定和 OTLP 传输协议。Nexent 选择 OpenTelemetry 作为监控主干，主要基于以下原因：

- 标准化：用统一的 span、event、metric 表达 HTTP、Agent、LLM、Tool 等运行时信号，减少平台私有模型对业务代码的侵入。
- 可移植：同一套埋点可以通过 OTLP 上报到 Phoenix、Langfuse、LangSmith、Grafana Tempo、Zipkin 或其他兼容后端，切换平台主要调整配置和 Collector pipeline。
- 可扩展：OpenTelemetry Collector 可以在不改业务代码的情况下完成转发、过滤、批处理、认证 header 注入和多后端分发。
- 生态成熟：FastAPI、requests 等基础组件已有自动埋点能力，Nexent 只需要补充 Agent/LLM/Tool 的业务 span。
- 避免锁定：监控平台 SDK 可以作为增强层，但核心链路不依赖某一家平台 SDK，避免平台迁移或本地化部署时重写埋点。
- 适合 Agent 场景：trace 的父子 span 结构天然适合表达 `agent.run -> chain step -> LLM generate/tool call -> final answer` 这类多步骤执行过程。

因此，Nexent 的实现原则是：业务代码只产生 OpenTelemetry 标准信号和少量平台兼容属性，平台差异收敛在配置、Collector 和展示层。

## OTel 规范概要

本文中的 OTel 规范通常指 OpenTelemetry Specification 及其配套规范。它不是某个 SDK，也不是某个监控平台，而是一套兼容性契约：规定可观测性数据应该如何生成、命名、传播、处理和导出。各语言 SDK、Collector、后端平台和自动埋点库按这套契约实现，才能保证跨语言、跨框架、跨后端互通。

一句话概括：OTel 规范是 OpenTelemetry 为 traces、metrics、logs 等可观测性数据制定的一套标准，保证不同语言、框架、Collector 和后端之间能够互通。

OpenTelemetry 规范按 signal 维度独立演进。Tracing、Metrics、Logs、Baggage 是当前主要 signal；Profiles 正在发展中，Events 通常作为 Logs 的特定事件形态讨论。每个成熟 signal 通常由 API、SDK、OTLP、Collector 和 instrumentation/contrib 生态共同组成，语义约定用于保证不同语言和组件在观测同类操作时输出一致的数据。

从实现视角看，OTel 规范可以拆成六个常用层面：

| 规范领域 | 核心概念 | 作用 |
|----------|----------|------|
| Signals | Traces、Metrics、Logs、Baggage、Profiles | 定义可观测性数据类型。Nexent 当前重点使用 Traces 和 Metrics，Logs 通过应用日志与 span event 补充上下文；Profiles 暂不接入 |
| API | Tracer、Meter、Logger、Context、Propagator | 面向业务代码和 instrumentation 的稳定接口，业务埋点只依赖 API，不直接绑定具体 exporter |
| SDK | TracerProvider、MeterProvider、SpanProcessor、MetricReader、Sampler、Resource | 提供采样、批处理、资源描述、导出等运行时能力 |
| Data Model | Span、Metric、LogRecord、Resource、Instrumentation Scope | 定义 telemetry 数据结构，确保不同语言和平台对数据有一致理解 |
| Context Propagation | Context、SpanContext、Baggage、Propagator | 在服务、线程、异步任务和下游请求之间传递 trace 上下文，保证调用链可以串起来 |
| OTLP | OTLP HTTP、OTLP gRPC、protobuf payload | OpenTelemetry 原生传输协议，负责把 traces、metrics、logs 从应用或 Collector 发到后端 |
| Semantic Conventions | 标准属性名、span name、metric name、单位和枚举值 | 统一 HTTP、数据库、RPC、Messaging 等通用语义；AI 场景中 Nexent 额外兼容 OpenInference 和 Langfuse 属性 |

### Signals

OTel 把可观测性数据抽象为多个 signal。每个 signal 有独立 API 和数据模型，但共享 Resource、Context 和传播机制。

- Traces：由一组具有父子关系的 span 构成，用于描述一次逻辑操作的完整路径。Nexent 用 trace 表达 `agent.run` 到 LLM、Tool、Final Answer 的执行链路。
- Metrics：由 counter、histogram、gauge 等 instrument 产生，用于描述聚合后的趋势和分布。Nexent 用 metrics 统计 LLM 延迟、TTFT、token 速率和错误数。
- Logs：以 LogRecord 或传统日志集成的方式表达离散事件。Nexent 当前不把 Logs signal 作为主链路 exporter，但会通过应用日志和 span event 补充错误上下文。
- Baggage：跨进程传播的键值上下文，适合传递租户、用户、实验分组等需要参与过滤和关联的业务标签。使用时需要控制基数和敏感信息。
- Profiles：用于记录代码级资源消耗画像，当前在 OpenTelemetry 体系中仍处于发展阶段。Nexent 暂不采集 profiles，避免引入额外运行时开销。

Nexent 的当前落地策略是：Traces 优先，因为 Agent 运行链路需要父子 span 表达；Metrics 保留，用于趋势、告警和 dashboard；Logs 暂以应用日志和 span event 形态承载，后续如需统一日志采集，可以通过 Collector 增加 Logs pipeline。

### API 与 SDK

OTel 区分 API 和 SDK：

- API 是埋点代码依赖的稳定接口，例如 `trace.get_tracer()`、`start_as_current_span()`、`meter.create_counter()`。
- SDK 是运行时实现，负责创建 provider、处理 span/metric、采样、批量导出和错误处理。

这种分层让库代码可以只依赖 API，而应用在启动时统一配置 SDK。Nexent 的 SDK 埋点遵循这个模型：业务函数只创建 span、event、metric；是否启用、导出到哪里、使用 HTTP 还是 gRPC，全部由 `MonitoringConfig` 和环境变量决定。

这种分层也决定了 Nexent 的边界：

- 业务代码不直接创建 exporter，也不直接引用 Phoenix、Langfuse、Tempo 等平台客户端。
- 初始化层负责创建 SDK provider、resource、processor、reader 和 exporter。
- 平台差异通过 provider profile、OTLP endpoint、header 和 Collector pipeline 表达。

### Resource 与 Instrumentation Scope

Resource 描述 telemetry 来源实体，例如服务名、版本、实例、部署环境、项目名。Nexent 当前写入：

- `service.name`：默认 `nexent-backend`
- `service.version`：当前固定为 `1.0.0`
- `service.instance.id`：当前固定为 `nexent-instance-1`
- `telemetry.provider`：当前 provider profile，例如 `otlp`、`phoenix`、`langfuse`、`grafana`、`zipkin`
- `project.name`：当配置 `MONITORING_PROJECT_NAME` 时写入

Instrumentation Scope 描述产生 telemetry 的 instrumentation 库或模块。后续如果需要区分 Nexent SDK、FastAPI 自动埋点、第三方库埋点，可以在 scope 层面辅助过滤。

### Context Propagation

Trace 的核心是上下文传播。一个请求从 HTTP 入口进入后，后续 Agent step、LLM 调用、Tool 调用必须处在同一个 trace 上下文中，监控页面才能显示正确的父子层级。

OTel 的 Context 是执行范围内的不可变上下文容器，用于承载当前 span、baggage 等跨切面数据。Propagator 负责把这些上下文编码到请求边界，例如 HTTP header，再由下游服务还原。对 Nexent 来说，同进程内的 async、generator、线程和工具调用上下文保持比跨服务 header 传播更关键。

Nexent 的关键处理包括：

- 业务入口只绑定一次 `AgentRunMetadata`，保存 tenant、user、agent、conversation、query、language、memory 等请求级元数据。
- SDK 在 `NexentAgent.agent_run_with_observer` 中创建顶层 `agent.run` span，并在 Agent loop、LLM、Tool 等生命周期中自动继承上下文。
- `monitor_endpoint` 保留为兼容 API 和低层 escape hatch，不再作为业务层新增埋点的推荐方式。
- Agent、LLM、Tool span 统一写入 OpenInference 和 Nexent 自定义属性，避免业务 trace 绑定到单一平台字段。

### Semantic Conventions

Semantic Conventions 规定常见遥测字段的命名和含义，例如 HTTP 方法、URL、状态码、错误类型、metric 单位等。使用语义约定的价值是让不同服务、语言和平台对同一类数据有一致理解。

Nexent 采用三层语义：

- OTel 通用语义：用于 service、resource、HTTP 自动埋点、metric instrument 等基础字段。
- OpenInference 语义：用于 AI span 类型，例如 `openinference.span.kind=AGENT|CHAIN|LLM|TOOL|RETRIEVER`，适配 Phoenix 等 AI observability 平台。

当平台展示存在差异时，Nexent 优先保持业务 span 的通用 OpenTelemetry / OpenInference 语义，不写入平台专用字段。

### OTLP 与 Collector Pipeline

OTLP 是 OpenTelemetry 原生传输协议，支持 HTTP 和 gRPC。Nexent 后端只需要把数据发到 OTLP endpoint，后端平台差异交给 Collector 处理。

Collector pipeline 通常由三部分组成：

- Receiver：接收应用上报的 OTLP traces/metrics/logs。
- Processor：执行批处理、内存限制、资源属性补充、过滤、采样等处理。
- Exporter：把数据转发到 Phoenix、Langfuse、Tempo 或其他 OTLP 兼容后端。

OTLP 是 request/response 风格协议，客户端发送 export 请求，服务端返回成功、部分成功或失败响应。Nexent 当前支持：

- OTLP HTTP：默认协议，便于通过网关、云平台和本地 Collector 接入。
- OTLP gRPC：适合内部网络或偏高吞吐场景。
- base endpoint 与 signal endpoint：支持配置 base endpoint，再由 SDK 推导 `/v1/traces` 和 `/v1/metrics`，也支持直接配置 signal-specific endpoint，避免路径重复拼接。

这种架构的好处是：应用侧配置保持稳定，平台迁移和本地化部署主要改 Collector 配置。例如 `grafana` 形态下 traces 转发到 Tempo；`phoenix` 形态下 traces 转发到 Phoenix；`otlp` 形态下先通过 debug exporter 验证数据是否产生。

## 设计目标

Nexent 的监控能力以 OpenTelemetry 为主干，SDK 和后端只负责生成标准 span、event、metric，并通过 OTLP 导出。Phoenix、Langfuse、LangSmith、Grafana Tempo、Zipkin 和标准 OTLP 后端作为可配置 exporter 接入，业务代码不绑定单一平台。

核心目标：

- Agent 流式运行期间保持 trace 上下文，覆盖 API、服务准备、Agent 异步 generator、Agent 线程、LLM 流式输出、Python 解释器执行、真实工具调用和最终答案。
- 通过 OpenInference 属性描述 Agent/LLM/Tool/Retriever 语义，同一套业务埋点可服务多个 OTLP 后端。
- 支持 `otlp`、`phoenix`、`langfuse`、`langsmith`、`grafana`、`zipkin` provider profile。
- 通过环境变量统一控制后端导出配置、本地部署形态和前端监控入口。
- 支持 base endpoint 和 signal-specific endpoint，避免 `/v1/traces`、`/v1/metrics` 路径重复拼接。
- FastAPI/requests 自动埋点可配置，默认压制流式接口中的 ASGI `receive/send` 噪声。

## 技术栈

| 分类 | 实现 |
|------|------|
| 标准框架 | OpenTelemetry API/SDK |
| 导出协议 | OTLP HTTP、OTLP gRPC |
| Trace exporter | `opentelemetry-exporter-otlp` HTTP/gRPC trace exporter |
| Metric exporter | `opentelemetry-exporter-otlp` HTTP/gRPC metric exporter |
| 自动埋点 | FastAPI instrumentation、requests instrumentation；requests 默认关闭 |
| AI 语义 | OpenInference 属性、Langfuse OTel 属性、Nexent 自定义业务属性 |
| Agent 框架 | SmolAgents `CodeAgent` 扩展、Nexent `CoreAgent`、`NexentAgent` |
| 配置 | 环境变量 |
| Collector | `otel/opentelemetry-collector-contrib`，支持 debug、Phoenix、Langfuse、LangSmith、Grafana/Tempo、Zipkin 部署形态 |

## 总体架构

```mermaid
flowchart LR
  Backend[Nexent Backend / SDK] --> OTel[OpenTelemetry TracerProvider / MeterProvider]
  OTel --> Exporter[OTLP Trace / Metric Exporter]
  Exporter --> Collector[OpenTelemetry Collector]
  Collector --> Phoenix[Arize Phoenix]
  Collector --> Langfuse[Langfuse]
  Collector --> Tempo[Grafana Tempo]
  Collector --> Zipkin[Zipkin]
  Collector --> Other[OTLP Backend]

  Backend --> FastAPI[FastAPI Auto Instrumentation]
  Backend --> Manual[Manual AI Spans]
  Manual --> OI[OpenInference Attributes]
  Manual --> LF[Langfuse Attributes]
```

## 配置模型

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ENABLE_TELEMETRY` | `false` | 监控总开关 |
| `MONITORING_PROVIDER` | `otlp` | 监控 provider 和部署形态：`otlp`、`phoenix`、`langfuse`、`langsmith`、`grafana`、`zipkin` |
| `MONITORING_DASHBOARD_URL` | 空 | 前端顶栏监控入口跳转 URL，后端只读取并透传该值 |
| `MONITORING_PROJECT_NAME` | `nexent` | 平台项目名 |
| `OTEL_SERVICE_NAME` | `nexent-backend` | OpenTelemetry service name |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://localhost:4318` | OTLP base endpoint |
| `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` | 空 | 可选 trace 专用 endpoint |
| `OTEL_EXPORTER_OTLP_METRICS_ENDPOINT` | 空 | 可选 metric 专用 endpoint |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | `http` | `http` 或 `grpc` |
| `OTEL_EXPORTER_OTLP_HEADERS` | 空 | 通用 `key=value,key2=value2` header |
| `OTEL_EXPORTER_OTLP_AUTHORIZATION` | 空 | `Authorization` header，常用于 Phoenix bearer auth 和 Langfuse Basic Auth |
| `OTEL_EXPORTER_OTLP_X_API_KEY` | 空 | `x-api-key` header，用于兼容需要该 header 的平台 |
| `OTEL_EXPORTER_OTLP_LANGFUSE_INGESTION_VERSION` | 空 | Langfuse 摄取版本，例如 `4` |
| `LANGSMITH_API_KEY` | 空 | LangSmith API Key，后端直连时映射为 `x-api-key`，Collector 转发时注入 exporter header |
| `LANGSMITH_PROJECT` | 空 | 可选 LangSmith project header |
| `LANGSMITH_OTLP_TRACES_ENDPOINT` | `https://api.smith.langchain.com/otel/v1/traces` | Collector 转发到在线 LangSmith 的 trace endpoint |
| `OTEL_EXPORTER_OTLP_METRICS_ENABLED` | `true` | 是否导出 metric |
| `MONITORING_INSTRUMENT_REQUESTS` | `false` | 是否启用 requests 自动 HTTP client span |
| `MONITORING_FASTAPI_EXCLUDED_URLS` | 空 | FastAPI 自动埋点排除 URL，逗号分隔正则 |
| `MONITORING_FASTAPI_EXCLUDE_SPANS` | `receive,send` | 排除 ASGI 内部 `receive/send` span，流式接口建议保持默认 |
| `OTEL_COLLECTOR_VERSION` | `0.150.0` | 本地 OpenTelemetry Collector Contrib 镜像版本 |
| `PHOENIX_VERSION` | `15` | 本地 Phoenix 镜像版本 |
| `LANGFUSE_VERSION` | `3` | 本地 Langfuse Web/Worker 镜像版本 |
| `LANGFUSE_POSTGRES_VERSION` | `15-alpine` | 本地 Langfuse Postgres 镜像版本 |
| `LANGFUSE_CLICKHOUSE_VERSION` | `26.3-alpine` | 本地 Langfuse ClickHouse 镜像版本 |
| `LANGFUSE_MINIO_VERSION` | `RELEASE.2023-12-20T01-00-02Z` | 本地 Langfuse MinIO 镜像版本 |
| `LANGFUSE_REDIS_VERSION` | `alpine` | 本地 Langfuse Redis 镜像版本 |
| `GRAFANA_VERSION` | `12.4` | 本地 Grafana 镜像版本 |
| `GRAFANA_PORT` | `3002` | 本地 Grafana UI 端口 |
| `GRAFANA_DEFAULT_LANGUAGE` | `zh-Hans` | 本地 Grafana 默认界面语言 |
| `TEMPO_VERSION` | `2.10.5` | 本地 Tempo 镜像版本，避免浮动 tag 带来的配置兼容性漂移 |
| `TEMPO_PORT` | `3200` | 本地 Tempo HTTP API 端口 |
| `ZIPKIN_VERSION` | `latest` | 本地 Zipkin 镜像版本 |
| `ZIPKIN_PORT` | `9411` | 本地 Zipkin UI/API 端口 |

## Endpoint 规则

HTTP exporter 支持两种输入：

- base endpoint：`https://cloud.langfuse.com/api/public/otel`
- signal endpoint：`https://cloud.langfuse.com/api/public/otel/v1/traces`

SDK 会按 signal 派生最终地址：

| 输入 | Trace endpoint | Metric endpoint |
|------|----------------|-----------------|
| `https://host/api/public/otel` | `https://host/api/public/otel/v1/traces` | `https://host/api/public/otel/v1/metrics` |
| `https://host/api/public/otel/v1/traces` | 原值 | `https://host/api/public/otel/v1/metrics` |
| `https://host/api/public/otel/v1/metrics` | `https://host/api/public/otel/v1/traces` | 原值 |

## 平台接入

### 纯 OTLP / 自建 Collector

```bash
MONITORING_PROVIDER=otlp
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318
OTEL_EXPORTER_OTLP_PROTOCOL=http
```

前端顶栏监控入口不再根据 provider 在代码中映射 UI 端口和路径。后端读取 `MONITORING_DASHBOARD_URL` 并通过 `/monitoring/status` 返回给前端；该值为空时前端不显示监控入口。因此本地 Grafana 形态需要在后端 `.env` 中设置：

```bash
MONITORING_PROVIDER=grafana
MONITORING_DASHBOARD_URL=http://localhost:3002/d/nexent-llm-agent/nexent-agent-trace-monitoring?orgId=1
```

### Phoenix

Phoenix 通过 OpenInference 属性识别 AI span 类型，核心字段是 `openinference.span.kind`。

```bash
MONITORING_PROVIDER=phoenix
OTEL_EXPORTER_OTLP_ENDPOINT=https://app.phoenix.arize.com/s/YOUR_SPACE
OTEL_EXPORTER_OTLP_AUTHORIZATION="Bearer YOUR_PHOENIX_API_KEY"
OTEL_EXPORTER_OTLP_METRICS_ENABLED=false
MONITORING_PROJECT_NAME=nexent-production
```

### Langfuse

Langfuse 的 OTLP HTTP base endpoint 是 `/api/public/otel`，使用 Basic Auth。实时摄取建议带 `x-langfuse-ingestion-version=4`。

```bash
MONITORING_PROVIDER=langfuse
OTEL_EXPORTER_OTLP_ENDPOINT=https://cloud.langfuse.com/api/public/otel
OTEL_EXPORTER_OTLP_AUTHORIZATION="Basic BASE64_PUBLIC_SECRET"
OTEL_EXPORTER_OTLP_LANGFUSE_INGESTION_VERSION=4
OTEL_EXPORTER_OTLP_METRICS_ENABLED=false
```

当前实现不写入 `langfuse.*` 专用 span 属性，Langfuse 通过 OTLP 接收通用 OpenTelemetry / OpenInference span。

### LangSmith

LangSmith 的在线 OTLP trace endpoint 为 `https://api.smith.langchain.com/otel/v1/traces`，使用 `x-api-key` header 认证，可通过 `Langsmith-Project` header 指定项目。推荐仍让 Nexent 后端上报到本地 Collector，由 Collector 注入 LangSmith API Key 并转发 traces：

```bash
MONITORING_PROVIDER=langsmith
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318
OTEL_EXPORTER_OTLP_PROTOCOL=http
OTEL_EXPORTER_OTLP_METRICS_ENABLED=false
```

Collector 侧配置 `LANGSMITH_API_KEY`、`LANGSMITH_PROJECT` 和 `LANGSMITH_OTLP_TRACES_ENDPOINT`。LangSmith 当前形态只转发 traces，metrics 进入 Collector debug pipeline。

### Zipkin

Zipkin 通过 Collector 的 Zipkin exporter 接收 traces。推荐 Nexent 后端仍然只上报到本地 Collector，由 Collector 转发到 Zipkin v2 spans endpoint：

```bash
MONITORING_PROVIDER=zipkin
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318
OTEL_EXPORTER_OTLP_PROTOCOL=http
OTEL_EXPORTER_OTLP_METRICS_ENABLED=false
MONITORING_DASHBOARD_URL=http://localhost:9411
```

Zipkin 当前本地形态只转发 traces；metrics 进入 Collector debug pipeline。

## 本地化部署设计

本地化部署通过 `docker/start-monitoring.sh` 选择形态。所有形态都保留 OpenTelemetry Collector 作为入口，Nexent 后端统一上报到 `http://otel-collector:4318` 或宿主机的 `http://localhost:4318`，平台差异只体现在 Collector exporter 和本地服务组合上。

| 形态 | Collector 配置 | 本地服务 | 数据去向 | 说明 |
|------|----------------|----------|----------|------|
| `otlp` | `otel-collector-config.yml` | Collector | debug exporter | 最小形态，用于验证 span/metric 是否产生，或手动改配置转发到云端平台；`collector` 仅作为启动脚本兼容别名 |
| `phoenix` | `otel-collector-phoenix-config.yml` | Collector + Phoenix | `http://phoenix:6006/v1/traces` | Phoenix 容器同时提供 UI 和 OTLP HTTP/gRPC trace collector，适合本地 trace debug |
| `langfuse` | `otel-collector-langfuse-config.yml` | Collector + Langfuse Web/Worker + Postgres + ClickHouse + MinIO + Redis | `http://langfuse-web:3000/api/public/otel/v1/traces` | Langfuse v3 依赖多组件，适合完整 LLMOps 能力验证 |
| `langsmith` | `otel-collector-langsmith-config.yml` | Collector | `https://api.smith.langchain.com/otel/v1/traces` | 在线 LangSmith trace 分析；API Key 只配置在 Collector 环境 |
| `grafana` | `otel-collector-grafana-config.yml` | Collector + Grafana + Tempo | traces 转发到 `tempo:4317`，metrics 只进入 Collector debug pipeline | Grafana + Tempo trace 查询 |
| `zipkin` | `otel-collector-zipkin-config.yml` | Collector + Zipkin | traces 转发到 `zipkin:9411/api/v2/spans`，metrics 只进入 Collector debug pipeline | Zipkin trace 查询 |

启动命令：

```bash
cd docker
./start-monitoring.sh --stack otlp
./start-monitoring.sh --stack phoenix
./start-monitoring.sh --stack langfuse
./start-monitoring.sh --stack langsmith
./start-monitoring.sh --stack grafana
./start-monitoring.sh --stack zipkin
```

部署脚本职责：

- 创建或复用 `nexent-network`。
- 首次启动时从 `monitoring.env.example` 生成 `monitoring.env`。
- 根据 `MONITORING_PROVIDER` 或 `--stack` 选择 Docker Compose profile。
- 根据部署形态设置 `OTEL_COLLECTOR_CONFIG_FILE`。
- Langfuse 本地形态下，如果 `LANGFUSE_OTLP_AUTH_HEADER` 未显式配置，则使用初始化项目的 public/secret key 生成 Basic Auth header。
- LangSmith 在线形态要求 `LANGSMITH_API_KEY`，启动时会校验该变量，避免 Collector 静默丢弃鉴权失败的 trace。

### Phoenix 本地形态

Phoenix 使用 `arizephoenix/phoenix` 镜像，默认暴露：

| 端口 | 用途 |
|------|------|
| `6006` | Phoenix UI 和 OTLP HTTP `/v1/traces` |
| `4319` | 映射到容器内 gRPC OTLP `4317`，避免与 Collector gRPC 端口冲突 |

Compose 中设置 `PHOENIX_WORKING_DIR=/mnt/data` 并挂载 `phoenix-data` volume，确保本地重启后 trace 数据不丢失。Collector 使用 `otlphttp/phoenix` exporter 的 base endpoint `http://phoenix:6006`，由 Collector 按 OTLP HTTP 规则追加 `/v1/traces`。

### Langfuse 本地形态

Langfuse v3 本地形态按自托管架构拆分为应用容器和存储组件：

| 组件 | 用途 |
|------|------|
| `langfuse-web` | UI、API、OTLP HTTP ingestion |
| `langfuse-worker` | 异步消费和处理 trace 事件 |
| `langfuse-postgres` | 事务型元数据 |
| `langfuse-clickhouse` | trace/observation/score 分析数据 |
| `langfuse-minio` | S3 兼容对象存储，保存事件和大对象 |
| `langfuse-redis` | 队列和缓存 |

初始化参数通过 `LANGFUSE_INIT_*` 配置，默认创建 `nexent-local` 项目和本地 API Key。Collector 使用 `otlphttp/langfuse` exporter，endpoint 为 `http://langfuse-web:3000/api/public/otel`，并携带：

```yaml
headers:
  Authorization: ${env:LANGFUSE_OTLP_AUTH_HEADER}
  x-langfuse-ingestion-version: "4"
```

默认密钥仅用于本地验证。生产或共享环境必须替换认证密钥、数据库密码、对象存储密钥和 `LANGFUSE_ENCRYPTION_KEY`，并补充备份、高可用和升级策略。

### Grafana 本地形态

Grafana 本地形态面向 trace 调试：

| 组件 | 用途 |
|------|------|
| `grafana` | 展示 Nexent Agent trace dashboard，并预置 Tempo datasource |
| `tempo` | 接收 Collector 转发的 OTLP traces，并提供 Grafana Explore 查询后端 |

Collector trace pipeline 使用 `otlp/tempo` exporter 转发到 `tempo:4317`。Tempo 启用 `metrics-generator` 的 `local-blocks` processor，用于支持 Grafana trace breakdown 中的 TraceQL metrics 查询。Collector metrics pipeline 保留为 debug exporter，用于兼容后端仍开启 OTLP metrics 的场景，但本地 Grafana 形态不提供独立指标存储和指标 dashboard。

### Zipkin 本地形态

Zipkin 本地形态面向轻量 trace 查询：

| 组件 | 用途 |
|------|------|
| `zipkin` | 接收 Collector 转发的 traces，并提供 trace 查询 UI |

Collector trace pipeline 使用 `zipkin` exporter 转发到 `http://zipkin:9411/api/v2/spans`。Collector metrics pipeline 保留为 debug exporter。

默认访问地址：

- Zipkin UI：`http://localhost:9411`

## Span 语义映射

| Nexent 场景 | OpenInference |
|-------------|---------------|
| Agent 入口 | `openinference.span.kind=AGENT` |
| 服务准备、流式生成、线程执行、普通步骤 | `openinference.span.kind=CHAIN` |
| LLM 调用 | `openinference.span.kind=LLM` |
| 工具调用 | `openinference.span.kind=TOOL` |
| 检索类调用 | `openinference.span.kind=RETRIEVER` |

上下文属性：

| 属性 | 说明 |
|------|------|
| `input.value` / `output.value` | OpenInference 输入输出 |
| `metadata` | OpenInference JSON metadata |
| `session.id` / `user.id` | OpenInference 会话和用户 |
| `tag.tags` | OpenInference tags |

## 埋点信息

| 埋点 | 位置 | 类型 | 内容 | 目的 |
|------|------|------|------|------|
| FastAPI 自动 span | `MonitoringManager.setup_fastapi_app` | HTTP server | route、method、status、duration | API 入口耗时和错误定位 |
| FastAPI `receive/send` 排除 | `fastapi_exclude_spans` | 降噪配置 | 默认 `receive,send` | 避免 SSE 流式接口生成大量 `unknown POST /agent/run http ...` |
| requests 自动 span | `MonitoringConfig.instrument_requests` | HTTP client | 外部请求 URL、method、status | 默认关闭；需要分析外部 HTTP 依赖时开启 |
| `AgentRunMetadata` | `run_agent_stream` 边界 | context | tenant、user、agent、conversation、query、language、memory、文件数 | 业务层只绑定一次请求上下文，后续 span 由 SDK 自动继承 |
| `agent.run` | `NexentAgent.agent_run_with_observer` | AGENT | query、session、user、tenant、agent、metadata、tags | 作为一次 Agent 运行的顶层业务 trace |
| `agent.run.loop` | `NexentAgent.agent_run_with_observer` | CHAIN | Agent loop、step、最终输出 | 追踪实际 Agent 执行生命周期 |
| `{display_name or model_id}.generate` | `sdk/nexent/core/models/openai_llm.py` | LLM / generation | 模型、温度、top_p、消息、输入输出、token、TTFT、chunk 数 | LLM 性能、成本、输出和异常分析 |
| `python_interpreter` | `sdk/nexent/core/agents/core_agent.py` | TOOL | 生成代码、step number、执行输出、日志、是否最终答案 | 观测 CodeAgent 解释器执行 |
| 真实工具名 | `sdk/nexent/core/agents/nexent_agent.py` | TOOL | local/MCP/langchain/builtin 工具输入输出 | 观测真实工具可用性、延迟、错误和输入输出 |
| `FinalAnswerTool` | `sdk/nexent/core/agents/core_agent.py` | TOOL | 最终答案输出 | 让 Phoenix/Langfuse 中能明确看到最终答案节点 |
| `monitor_endpoint` | SDK 兼容 API | AGENT / CHAIN | 自定义 operation、参数、错误 | 低层 escape hatch；不推荐业务层新增常规埋点 |
| `start_agent_run` / `trace_agent_step` / `trace_retriever_call` | SDK 公共 API | AGENT / CHAIN / RETRIEVER | Agent metadata、输入输出、session、user | SDK 生命周期埋点和少量自定义层级埋点 |
| `trace_tool_call` | SDK 公共 API | TOOL | 工具名、输入、输出、耗时、错误 | SDK 用户自定义工具埋点 |

### 事件清单

| Span / 位置 | Event | 主要属性 | 目的 |
|-------------|-------|----------|------|
| `agent.run` | `agent.run.started` / `agent.run.completed` / `agent.run.error` | `error.*` | 观测一次 Agent 运行的开始、结束和异常 |
| LLM span | `completion_started` / `first_token_received` / `token_generated` / `completion_finished` / `model_stopped` / `error_occurred` | `model_id`、`temperature`、`top_p`、`message_count`、`total_duration`、`output_length`、`chunk_count`、`error.*` | 分析模型参数、流式输出耗时、停止和异常 |
| Tool span | span 属性 `agent.tool.input` / `agent.tool.output` | JSON 字符串、`agent.tool.duration_ms`、`error.*` | 分析工具输入输出、耗时和异常 |

## 指标

| 指标 | 类型 | 维度 | 用途 |
|------|------|------|------|
| `llm.request.duration` | histogram | model、operation | LLM 请求延迟 |
| `llm.token.generation_rate` | histogram | model | token/s |
| `llm.time_to_first_token` | histogram | model | 首 token 延迟 |
| `llm.token_count.prompt` | counter | model | 输入 token 成本 |
| `llm.token_count.completion` | counter | model | 输出 token 成本 |
| `llm.error.count` | counter | model、operation | LLM 错误率 |
| `agent.step.count` | counter | agent、step type、tool | Agent 步骤和工具调用量 |
| `agent.execution.duration` | histogram | agent、status | Agent 总耗时 |
| `agent.error.count` | counter | agent、error type | Agent 异常统计 |

## Agent 运行数据流

```mermaid
flowchart TD
  U[用户] --> FE[前端 Chat]
  FE --> API[POST /agent/run]
  API --> HTTP[FastAPI HTTP span: 可配置隐藏]
  API --> Bind[绑定 AgentRunMetadata]
  Bind --> Mem[解析 memory 开关]
  Mem --> Strategy{with_memory / no_memory}
  Strategy -->|with_memory| G1[generate_stream_with_memory]
  Strategy -->|no_memory| G2[generate_stream_no_memory]
  G1 --> AR[agent_run async generator]
  G2 --> AR
  AR --> Thread[agent_run_thread]
  Thread --> NX[NexentAgent / CoreAgent]
  NX --> A0[agent.run span: AGENT]
  A0 --> Step[agent.run.loop: CHAIN]
  Step --> LLM[Model.generate: LLM / generation]
  Step --> PY[python_interpreter: TOOL]
  PY --> Tool[Real local / MCP / langchain / builtin tool: TOOL]
  PY --> Final[FinalAnswerTool: TOOL]
  LLM --> Attr1[OpenInference + Langfuse attrs]
  Tool --> Attr1
  Final --> Attr1
  Attr1 --> OTel[OpenTelemetry Tracer/Meter Provider]
  OTel --> Collector[OTLP Collector]
  Collector --> Phoenix[Phoenix]
  Collector --> Langfuse[Langfuse]
  Collector --> Tempo[Grafana Tempo]
  Collector --> Zipkin[Zipkin]
  Collector --> Other[OTLP Backend]
```

预期平台树形结构：

```text
agent.run                         agent
└─ agent.run.loop                  chain
   ├─ Model.generate               llm / generation
   ├─ python_interpreter           tool
   │  └─ RealTool                  tool
   └─ FinalAnswerTool              tool
```

FastAPI HTTP span 可以保留在最上层用于接口视角，也可以通过 `MONITORING_FASTAPI_EXCLUDED_URLS=/agent/run` 在 AI trace 视图中隐藏。

## 监控页面结构

```mermaid
flowchart TB
  Page[Agent 监控页] --> Filters[筛选区: 时间 / 租户 / 用户 / Agent / 会话 / 模型 / 状态]
  Page --> KPIs[指标区: 成功率 / P95 / TTFT / tokens/s / token 成本 / 工具错误数]
  Page --> TraceList[Trace 列表: Agent / 会话 / 用户 / 状态 / 耗时 / Token / 模型 / 最后错误]
  Page --> Detail[Trace 详情]
  Detail --> Waterfall[Span 瀑布图: agent / chain / llm / tool]
  Detail --> Timeline[Agent 时间线: 准备 / 记忆 / LLM / 工具 / 最终答案]
  Detail --> LLMPanel[LLM 面板: prompt / output / token / TTFT / generation rate]
  Detail --> ToolPanel[工具面板: 工具名 / 输入 / 输出 / 耗时 / 错误]
  Detail --> Session[会话和用户上下文]
  Detail --> Raw[原始 OTel 属性和 events]
  Detail --> Eval[反馈、评分和评估]
```

监控平台之间不能只按“是否能收 trace”比较。对智能体场景，更关键的是是否理解 LLM/Agent 语义、是否支持评估和反馈、是否适合本地化部署、是否能与企业已有 APM 合流。下面按 Nexent 可能接入的平台做比较：

| 平台 | 类型 | 部署形态 | 主要接入方式 | AI / Agent 语义 | Metrics / Logs | 评估 / 反馈 | 适合场景 | Nexent 当前适配 |
|------|------|----------|--------------|-----------------|----------------|-------------|----------|----------------|
| Phoenix | AI 原生可观测性 / 实验分析 | 云服务或自托管 | OTLP、OpenInference、Phoenix SDK | OpenInference 生态匹配好，适合展示 LLM、retriever、agent、tool 等语义 | 重点在 trace 和实验分析，通用 infra 监控不是核心 | 支持 eval、dataset、实验分析 | 本地 trace debug、RAG/LLM 质量分析、OpenInference 语义验证 | 写入 OpenInference 属性；支持本地 Phoenix stack 和 OTLP 转发 |
| Langfuse | LLMOps / Prompt 与 Trace 平台 | 云服务或自托管 | OTLP、Langfuse SDK、API | 对 trace、observation、session、user、prompt、metadata 支持完整 | 提供 LLM 应用维度 dashboard，通用 infra 监控不是重点 | 支持 score、feedback、eval、prompt 管理 | 需要 prompt 管理、用户会话、反馈和成本闭环的 LLM 应用 | 支持本地 Langfuse stack 和 OTLP 转发；业务 span 不写入 `langfuse.*` 专用属性 |
| LangSmith | LangChain / LangGraph 生态观测与评估 | 云服务为主 | LangSmith SDK、OTLP endpoint | 与 LangChain/LangGraph run、thread、feedback、evaluation 生态贴合 | 重点在应用 trace 和评估，不替代通用 APM | 评估、dataset、反馈、回归测试能力强 | 使用 LangChain/LangGraph 或需要在线评估闭环 | 支持 Collector 注入 `x-api-key` 和 `Langsmith-Project` 转发 traces |
| Grafana Tempo + Grafana | 通用 trace 后端 / Dashboard | 自托管或云服务 | OTLP、Jaeger、Zipkin 等，经 Collector 常见 | 不内置 LLM/Agent 专用语义，需要 dashboard 和属性约定补充 | Grafana 生态可接 Prometheus、Loki、Tempo 组合 | 不提供原生 LLM 评估，需要外部系统 | 私有化、本地化、已有 Grafana/Prometheus/Loki 体系 | 支持本地 Tempo + Grafana stack，预置 Tempo datasource 和 trace dashboard |
| Zipkin | 轻量分布式 tracing | 自托管 | Zipkin API，通常由 Collector exporter 转发 | 只理解通用 trace/span，不理解 LLM/Agent 语义 | 不提供 metrics/logs 平台能力 | 不提供评估能力 | 最小本地 trace 查询、验证转发链路、低成本调试 | 支持本地 Zipkin stack，Collector 转发 traces |
| Datadog LLM Observability | 全栈 APM + LLM Observability | 云服务 / Agent | Datadog SDK、Agent、OTel/OTLP 等 | 支持 LLM 应用 traces、prompt/completion、成本、质量和安全维度 | 全栈 metrics/logs/traces/APM/infra 能力强 | 支持 LLM evaluations、质量和安全监控 | 企业已有 Datadog，需把 AI 应用纳入统一生产监控 | 可通过标准 OTLP/Collector 或平台 SDK 接入，当前未内置本地 stack |
| New Relic AI Monitoring | 全栈 APM + AI Monitoring | 云服务 / Agent | New Relic agent、OTel/OTLP 等 | 关注 LLM app 性能、错误、成本和模型交互 | 全栈 APM、infra、logs、browser/mobile 生态完整 | 提供 AI 应用监控与分析能力，评估深度依赖平台能力 | 企业已有 New Relic，关注生产运行和统一告警 | 可通过标准 OTLP/Collector 或平台 agent 接入，当前未内置本地 stack |
| Elastic Observability | 全栈可观测性 / 搜索分析 | 云服务或自托管 | Elastic APM agent、OTel/OTLP、EDOT | 支持 LLM observability 和 OTel 语义，适合把 AI trace 与日志、指标、搜索分析合并 | logs、metrics、traces、搜索分析能力强 | 侧重监控、分析和 dashboard，业务评估闭环仍需额外设计 | 已有 Elastic Stack、重视日志检索、私有化和统一搜索分析 | 可通过 OTLP/Collector 对接，当前未内置本地 stack |
| Honeycomb | 事件驱动可观测性 / 高基数分析 | 云服务 | OTLP、OpenTelemetry SDK、Events API / libhoney | 擅长高基数 trace/event 分析，AI 语义通过属性和 OTel GenAI 约定表达 | 强在 trace/event 和指标分析，日志通常通过事件化方式分析 | 不提供完整 LLMOps 评估闭环 | 需要按租户、用户、agent、tool 做高维切片分析 | 可通过 OTLP/Collector 对接，当前未内置本地 stack |
| Nexent 自建页 | 产品内业务观测 | 自建 | 复用 OTel 属性和业务数据库 | 最能理解租户、会话、Agent 配置、权限、版本和业务动作 | 需要自建指标、查询、存储和告警 | 可与产品反馈、评分和评估闭环深度结合 | 产品内闭环、权限隔离、面向终端用户或运维角色的监控页 | 当前先通过 OTLP 对接外部平台，后续可基于同一批属性构建自有页面 |

从选型上可以把平台分成三类：

- AI 原生平台优先解决“Agent 为什么这样回答、prompt/tool/retrieval 是否有效、质量如何评估”的问题，适合研发调试和 LLMOps 闭环。
- 通用 trace 后端优先解决“链路是否完整、哪一步慢、部署是否轻量和可私有化”的问题，适合本地调试和私有化基础能力。
- 全栈 APM 优先解决“生产系统整体是否健康、AI 服务如何纳入企业统一监控、告警和审计”的问题，适合已有企业监控体系的团队。

按使用场景选择时，可以简化成下面的矩阵：

| 场景 | 优先平台 | 原因 | 代价 |
|------|----------|------|------|
| 本地开发和快速看 trace | Phoenix、Zipkin、Grafana Tempo | 自托管简单，能快速验证 span 层级、Collector 转发和属性是否正确 | 对质量评估、prompt 管理和业务闭环支持有限 |
| RAG / Agent 质量分析 | Phoenix、Langfuse、LangSmith | 更理解 prompt、completion、retriever、tool、session、feedback 和 eval | 平台语义差异较大，需要保留可迁移的 OTel 属性 |
| 企业生产统一监控 | Datadog、New Relic、Elastic、Honeycomb | 能和服务、基础设施、日志、指标、告警、权限体系合流 | AI 业务语义需要通过 OTel GenAI/OpenInference/自定义属性补齐 |
| 产品内用户态监控页 | Nexent 自建页 + 外部 trace 后端 | 能结合租户、权限、Agent 配置、会话、反馈和产品操作 | 需要自建查询、聚合、权限隔离和可视化能力 |

因此 Nexent 的策略不是只绑定一个平台，而是以 OpenTelemetry/OTLP 和兼容语义属性作为主干：本地默认支持 Phoenix、Langfuse、Grafana Tempo、Zipkin 等便于验证的形态；线上或企业环境可以把同一批 traces 转发到 LangSmith、Datadog、New Relic、Elastic、Honeycomb 或其他 OTLP 兼容后端。

推荐路径：

1. 短期使用 OTLP 对接 Phoenix/Langfuse/LangSmith，满足调试和分析。
2. 中期在 Nexent 增加 trace 跳转、轻量指标概览和异常聚合。
3. 长期按租户、会话、Agent 版本建立自有监控页，同时保留 OTLP 双写能力。

## 已修复的设计风险

| 风险 | 修复 |
|------|------|
| 业务层埋点耦合过高 | 业务入口只绑定 `AgentRunMetadata`，Agent/LLM/Tool 语义 span 下沉到 SDK 生命周期 |
| `/v1/traces` 路径重复拼接 | SDK 支持 base endpoint 和 signal endpoint 自动归一化 |
| Collector header 无法兼容平台 | Collector 默认只 debug；平台转发配置拆分 `Authorization`、`x-api-key`、`x-langfuse-ingestion-version` |
| Phoenix 只看到接口看不到 Agent | SDK 顶层 `agent.run` 标记为 AGENT，内部 `agent.run.loop` 标记为 CHAIN |
| Phoenix/Langfuse 中出现大量 `unknown POST /agent/run http ...` | 默认排除 FastAPI ASGI `receive/send` span；requests 自动埋点默认关闭；可配置隐藏 `/agent/run` HTTP span |
| Langfuse 字段耦合过重 | 不写入 `langfuse.*` 专用 span 属性，仅保留 OTLP 转发和 OpenInference 语义 |
| LLM span 不明显或缺输出 | LLM span 命名为 `{display_name or model_id}.generate`，并写入 `output.value` |
| 工具 span 缺失 | 在 `NexentAgent.create_single_agent` 统一包装 local/MCP/langchain/builtin 工具，并在 `CoreAgent` 增加 `python_interpreter` 和 `FinalAnswerTool` span |
| 单测漏掉 SDK 生命周期路径 | 增加 AgentRunMetadata、Agent/chain、LLM/Tool 继承上下文测试 |

## 使用建议

只看 Agent 业务链路时：

```bash
MONITORING_FASTAPI_EXCLUDE_SPANS=receive,send
MONITORING_FASTAPI_EXCLUDED_URLS=/agent/run
MONITORING_INSTRUMENT_REQUESTS=false
```

同时看接口入口和 Agent 业务链路时：

```bash
MONITORING_FASTAPI_EXCLUDE_SPANS=receive,send
MONITORING_FASTAPI_EXCLUDED_URLS=
MONITORING_INSTRUMENT_REQUESTS=false
```

需要排查外部 HTTP 依赖时：

```bash
MONITORING_INSTRUMENT_REQUESTS=true
```

## 参考

- OpenTelemetry Collector: https://opentelemetry.io/docs/collector/
- OpenTelemetry OTLP Specification: https://opentelemetry.io/docs/specs/otlp/
- OpenTelemetry GenAI Semantic Conventions: https://opentelemetry.io/docs/specs/semconv/gen-ai/
- OpenInference Semantic Conventions: https://arize-ai.github.io/openinference/spec/semantic_conventions.html
- LangSmith Trace with OpenTelemetry: https://docs.langchain.com/langsmith/trace-with-opentelemetry
- LangGraph Observability: https://docs.langchain.com/langgraph-platform/langsmith-observability
- LlamaIndex Observability: https://docs.llamaindex.ai/en/stable/module_guides/observability/
- LlamaIndex OpenTelemetry Integration: https://docs.llamaindex.ai/en/stable/api_reference/observability/otel/
- OpenAI Agents SDK Tracing: https://openai.github.io/openai-agents-python/tracing/
- Semantic Kernel Telemetry: https://learn.microsoft.com/en-us/semantic-kernel/concepts/enterprise-readiness/observability/telemetry-with-console
- CrewAI Tracing: https://docs.crewai.com/en/observability/tracing
- CrewAI OpenTelemetry Export: https://docs.crewai.com/en/enterprise/guides/capture_telemetry_logs
- CrewAI OpenLIT Integration: https://docs.crewai.com/en/observability/openlit
- AgentOps CrewAI Integration: https://docs.agentops.ai/v1/integrations/crewai
- AutoGen Agent Observability: https://microsoft.github.io/autogen/stable/user-guide/agentchat-user-guide/agent-observability.html
- AutoGen Tracing and Observability: https://microsoft.github.io/autogen/stable/user-guide/agentchat-user-guide/tracing.html
- Dify Monitoring Dashboard: https://docs.dify.ai/en/use-dify/monitor/analysis
- Dify Langfuse Integration: https://docs.dify.ai/en/use-dify/monitor/integrations/integrate-langfuse
- Dify LangSmith Integration: https://docs.dify.ai/en/use-dify/monitor/integrations/integrate-langsmith
- Dify Agent Node: https://docs.dify.ai/en/guides/workflow/node/agent
- smolagents Inspecting runs with OpenTelemetry: https://huggingface.co/docs/smolagents/en/tutorials/inspect_runs
- smolagents Phoenix tracing guide: https://huggingface.co/blog/smolagents-phoenix
- Vercel AI SDK Telemetry: https://ai-sdk.dev/docs/ai-sdk-core/telemetry
- Haystack Tracing: https://docs.haystack.deepset.ai/docs/tracing
- Phoenix Setup Tracing: https://arize.com/docs/phoenix/tracing/how-to-tracing/setup-tracing
- Phoenix Setup OTEL: https://arize.com/docs/phoenix/tracing/how-to-tracing/setup-tracing/setup-using-phoenix-otel
- Phoenix Authentication: https://arize.com/docs/phoenix/deployment/authentication
- Phoenix Self-Hosting: https://arize.com/docs/phoenix/self-hosting
- Phoenix Docker Deployment: https://arize.com/docs/phoenix/self-hosting/deployment-options/docker
- Langfuse OpenTelemetry: https://langfuse.com/integrations/native/opentelemetry
- Langfuse Self-Hosting: https://langfuse.com/self-hosting
- Langfuse Docker Compose: https://langfuse.com/self-hosting/local
- Langfuse Overview: https://langfuse.com/docs
- LangSmith OpenTelemetry: https://docs.langchain.com/langsmith/otel-gateway-trace-redaction
- Datadog LLM Observability: https://docs.datadoghq.com/llm_observability/
- New Relic AI Monitoring: https://docs.newrelic.com/docs/ai-monitoring/intro-to-ai-monitoring/
- Elastic OpenTelemetry: https://www.elastic.co/docs/solutions/observability/apm/opentelemetry/
- Elastic EDOT data streams: https://www.elastic.co/docs/reference/opentelemetry/data-streams
- Honeycomb Send Data: https://docs.honeycomb.io/send-data/
- Honeycomb for LLMs: https://docs.honeycomb.io/send-data/llm/
- Grafana Tempo: https://grafana.com/docs/tempo/latest/
- Zipkin OpenTelemetry Collector exporter: https://opentelemetry.io/docs/collector/configuration/#exporters
- Zipkin Docker image: https://hub.docker.com/r/openzipkin/zipkin
