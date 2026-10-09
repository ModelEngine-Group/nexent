# AIDP 创建知识库：联调接口适配

记录日期：2026-10-09。以用户提供的 AIDP 浏览器请求、返回和参数模板为依据，旧接口文档与这些信息冲突时采用实际接口信息。

## 本次行为

- 创建页通过一次 `ModelService/Tenants/aidp/Service?app=KnowledgeBase` 查询获取模型，按顶层 `model_type` 分为 embedding、vlm、llm。下拉显示 `display_name`，提交 `model_name`。不使用虚构的默认模型标识。
- 开启知识图谱后查询 `KnowledgeBases/GraphConfigTemplate?language=chinese`；切换提示词语言后按 `english` 查询。接口的 `param_value` 用于初始值，`regexp` 用于校验和枚举选项，`template` 用于不同领域的默认提示词。
- 默认提示词随语言和领域切换；用户手工修改的内容保持，点击“使用默认模板”才主动恢复当前模板。接口查询失败时提供重试，并阻止相应创建请求。
- `is_modifiable` 保留在模板返回中，表示创建后参数是否支持修改，不据此禁止创建时选择语言、领域和提示词。本次不增加图谱编辑功能。
- 知识图谱里的向量检索 TOP K 删除，不改成另一个未经确认的图谱字段。“检索匹配”模块里的 `topk` 保留，默认 10；相似度默认 0.6。其他已有字段显示名称尽量保持。
- 十八个问号提示采用 [截图文案记录](aidp-create-knowledge-tooltips.md)。原界面“构图过程开启大模型思考”与接口禁用思考含义相反，提示补充说明正反对应关系。
- 文件列表导入方式固定显示“本地导入 / Local import”，不读取 `import_source_dir` 或其他目录字段。
- 列表和详情的创建人通过 `aidp_kb_permission_t.owner_user_id` 查询当前租户有效的 `user_tenant_t.user_email`，与 Nexent 用户管理所使用的账号名称一致。列表按当前页批量查询，不逐条查询用户。历史记录没有创建用户或用户不可用时显示“—”，不显示远端空 `user_name` 或用户 ID，不把当前浏览者当成创建人。
- 更新时间、文件数、容量本次保持现状。ES 知识库不在本次范围。

## 创建请求

Nexent 前端提交结构化配置，后端将 `graph_config` 序列化成 JSON **字符串**，再调用 AIDP 的 `PUT /KnowledgeBase/Tenants/aidp/KnowledgeBases`。

开启图谱时，字符串内容只包含模板的七个参数及所选 LLM：

```json
{
  "retrieve_subgraph_hop": "2",
  "no_think_mode": "是",
  "prompt_language": "中文",
  "domain": "常规",
  "prompt_text": "从模板接口获取的提示词或用户编辑后的内容",
  "synonym_merge_enable": "否",
  "disambiguation_enable": "否",
  "llm_model_name": "从模型接口选择的 model_name"
}
```

数值跳数使用字符串；开关使用“是 / 否”；领域使用“医疗 / 金融 / 常规 / 法律法规”，语言使用“中文 / 英文”。提示词长度为 1–4096 个 Unicode 字符，不再按 2048 个 UTF-8 字节计算。界面开启思考时，`no_think_mode` 提交“否”。

外层保留 `is_personal`、`chunk_mode`、切片长度与重叠数、向量模型、`topk`、`similarity`、`caption_enable`、`vlm_model`、`is_exist_graph` 等实际请求字段。不再发送 `smartsplit`。Nexent 权限与用户组仍只写入本地权限表。关闭图谱后不发送其配置或隐藏的 LLM；关闭 VLM 后发送 `caption_enable=0` 和空 `vlm_model`。

## Mock 与验证边界

Mock 新增七项图谱模板返回、三类模型及其显示名和类型，创建时保存参数供详情回显，并严格拒绝旧图谱 TOP K、布尔值、英文枚举、非字符串跳数和无效提示词。新增回归检查覆盖这些联调报错，避免 mock 再次静默丢弃图谱字段。

验证包括前端表单查询与提交、模板联动及手工内容保留、真实表单控件的十八项提示与字符边界，以及后端转发到 mock 的创建和详情回读。用户查询按当前租户进行，不需要数据库迁移。

英文 mock 提示词是合成测试数据，并非正式 AIDP 的模板。另一台电脑联调时仍需验证英文模板真实返回、正式模型标识以及实际创建响应。本地 mock 通过不等同于正式 AIDP 联调通过。

2026-10-09 补充：中文 mock 原先使用一句话测试数据，造成页面默认提示词过短。现改为用户提供的完整中文接口响应，保存在 `test/ext_components/aidp/mock_servers/graph_config_template_chinese.json`，包含四个领域的完整模板。页面仍从接口读取，没有在产品前端或 Nexent 后端内置这四份提示词。

全局正式测试资产检查另有历史缺失绑定、已有脚本哈希不匹配等问题；本次新增的 `AKPR-D1-011` 实现单独登记，不将全局资产检查报告为通过。

## 本次检查结果

- AIDP 服务、管理路由、mock 和创建人查询回归：404 项通过。
- 用户数据库回归：52 项通过，包含新增的租户过滤检查。
- 前端 AIDP 组件与上传相关回归：19 项通过，包含真实创建表单的十八项提示及 Unicode 字符边界检查。
- `npm run type-check` 通过；本次修改的 AIDP 组件、服务与图谱工具 ESLint 检查通过；backend 修改文件的 Ruff 和 frontend 修改文件的 Prettier 检查通过。
- 更广的 ESLint 检查在 `frontend/services/api.ts`、`frontend/types/agentConfig.ts` 中报告 10 处既有 `no-explicit-any`，这些行不属于本次新增代码。
- 正式测试资产设计阶段检查通过，并重新生成派生 Excel。实现阶段全局检查仍报告 24 项既有绑定缺失或哈希不一致；本次新增的创建表单绑定没有出现在错误报告中。
- 本次未重启本地 deploy 服务，也未在正式 AIDP 环境执行浏览器联调。
