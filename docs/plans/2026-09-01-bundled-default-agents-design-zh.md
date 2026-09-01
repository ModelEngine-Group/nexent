# 内置官方智能体设计

## 1. 目标

Nexent 平台安装完成后，官方智能体自动出现在“智能体仓库”中，不再需要在资源管理页点击“安装官方智能体”。官方智能体是平台级只读模板；租户复制后生成自己的智能体副本，副本拥有与普通智能体相同的编辑、版本发布和重新上架权限。

## 2. 资源交付

官方智能体内容由独立资源仓库维护，不放入 Nexent 源码仓库。发布流程将指定行业 profile 与 Nexent 安装包组合：

```text
nexent-installer-medical/
├── deploy/
├── images/
└── official-agents/
    └── medical/
        ├── medical-researcher.zip
        └── clinical-assistant.zip
```

部署配置：

```env
OFFICIAL_AGENT_PROFILE=medical
OFFICIAL_AGENTS_PATH=/mnt/nexent/official-agents/medical
```

Docker 以只读方式挂载资源；Kubernetes 使用外部资源卷或安装包目录挂载。不同的 `general`、`medical`、`finance` 等 profile 使用同一套 Nexent 代码，只加载当前配置的资源。

## 3. 持久化模型

复用现有 `AgentInfo` 和 `AgentRepository` 表，不增加字段、不新增表。使用保留租户值表示平台模板：

```python
OFFICIAL_AGENT_TENANT_ID = "__nexent_official__"
OFFICIAL_AGENT_USER_ID = "__nexent_system__"
```

官方源智能体和仓库条目都属于该保留租户。复用现有按 `agent_id + publisher_tenant_id` 的仓库 upsert 逻辑；启动同步前必须找到并复用已有源智能体，避免重复创建。

不增加数据库唯一索引。只要官方源智能体的 `agent_id` 保持稳定，现有查询和 upsert 即可实现幂等同步。

## 4. 启动同步

数据库连接和迁移完成后，后端执行独立的官方智能体同步任务：

```text
读取 OFFICIAL_AGENTS_PATH
  → 枚举当前 profile 的 bundle
  → 校验并安全解压 ZIP
  → 读取 agent 快照、技能和知识库种子文件
  → 在保留租户下查找或创建源智能体
  → upsert 官方仓库快照
```

同步按 bundle 隔离。单个资源损坏或同步失败只记录日志并跳过，不阻塞 Nexent 启动。资源版本变化时只更新官方模板，不覆盖已经复制到租户的智能体。

ZIP 必须解压到临时目录，并拒绝绝对路径和 `..` 路径穿越；校验完成后才允许持久化。

## 5. 仓库可见性和权限

仓库查询同时返回：

```text
当前租户自己的条目
OR
OFFICIAL_AGENT_TENANT_ID 下的官方条目
```

官方条目对所有租户可见，支持查看详情和复制，但禁止租户编辑、审核、下架或删除。复制成功后可以增加下载次数。

复制读取官方 `agent_info_json` 快照，但使用当前用户和当前租户执行导入。生成的智能体完全归当前租户所有，可编辑、发布版本、提交审核、上架或再次更新仓库。

前端复用现有“智能体仓库”页面和复制流程，仅增加“官方”标识并隐藏官方条目的管理操作，不增加专用安装弹窗。

## 6. 异常和升级

- 未配置 profile 或路径：按默认策略使用 `general` 或关闭同步；
- profile 目录不存在：记录明确日志，主服务继续运行；
- 单个 bundle 无效：只跳过该 bundle；
- 同步失败：回滚当前 bundle，继续处理其他 bundle；
- 重复启动：复用源智能体并更新已有仓库记录；
- 官方资源升级：只更新官方模板，不修改租户副本；
- 租户复制失败：不修改官方模板和其他租户；
- 复制后的智能体重新上架：走普通租户审核流程。

## 7. 验证

后端测试覆盖 profile 解析、ZIP 校验、保留租户初始化、首次同步、重复同步、版本更新、失败隔离、跨租户可见、复制权限、管理操作拦截、复制后的租户归属和普通重新上架。

部署测试覆盖离线包组成、Docker 只读挂载、Kubernetes 注入、默认/缺失 profile 和 profile 隔离。前端测试覆盖官方标识、操作按钮和复制结果。

医疗版验收要求：平台启动后无需手工安装即可在智能体仓库看到医疗智能体；租户可复制、编辑和重新上架；重启不产生重复条目；通用版不加载医疗资源。

## 8. 范围边界

本需求不新增官方智能体 API、数据库表、数据库字段或资源管理安装向导，也不记录租户副本的官方来源链路。
