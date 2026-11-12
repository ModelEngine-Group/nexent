# Data Process 退役开发入口

本分支 `feat-data-process-retirement` 从 `045a69912` 创建，承接 AgentOS stacked PR #4280。当前阶段只整理规格，尚未删除 data-process 的产品代码、镜像或运行容器。

完整 SPEC 保存在独立同步的 nexent-doc 文档目录，不复制进代码仓库。

```text
nexent-doc/docs/Developing/four-service-runtime-decoupling/changes/
  management-data-process-retirement/
    proposal.md
    design.md
    task.md
    source-audit.md
```

已扫描 822 份 Markdown，记录 63 份相关候选。最新 AgentOS 规格优先于旧四服务文档中保留 Data Process 的历史方案。

| 能力 | 目标所有者 |
| --- | --- |
| 文件接收、清洗、格式转换、文件任务状态、摘要编排 | Management |
| 最终检索分块、向量化、相似度检索、重排、索引执行 | Runtime KnowledgeBase |
| 对象、关系、队列及向量读写适配 | Infrastructure |

Management 与 Runtime 只通过 AgentOS 交换授权请求、产物引用和状态。跨服务不传本地路径、不导入对方 Celery app、不拼接旧 /tasks URL。

实施顺序为契约冻结、Management 清洗、Runtime KB、消费者切换、任务恢复与维护，最后删除旧镜像和部署资产。详细文件清单、接口、AC、测试设计及维护回滚门槛见独立 SPEC。

开发前应确认三项设计决定。

- Management 保留解析器内部的非大模型 OCR/layout/table 权重，CLIP 图片筛选归 Runtime。
- SDK 纯解析算法的公共 API 暂保留，本批不借镜像退役静默删除。
- Runtime 文本分析需要清洗时，通过签名 AgentOS 反向请求 Management。

所有新能力与新拓扑验收均待实施。父 PR 的旧私有入口测试迁移、异步接纳与旧过载 D2 语义，以及既有前端测试绑定缺失继续单独跟踪，不能以本规划文档交付声明已解决。
