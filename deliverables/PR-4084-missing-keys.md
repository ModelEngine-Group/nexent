# PR #4084 — 54 个缺失 i18n key 精确定位清单

基于 PR head `ff5b9d414` 全量扫描（`t()` 静态 key × en/zh common.json 交叉比对）。
所有 key 在 **en 和 zh 两侧均缺失**。修复方式：在 `frontend/public/locales/en/common.json` 和 `zh/common.json` 各补 54 个 key。

## 重灾区 1：官方智能体安装弹窗（27 个）— 英文界面显示 key 字符串

文件：`frontend/components/agent/InstallOfficialAgentsModal.tsx`（全部裸调 `t()`，无 fallback）

| Key | 行号 |
| --- | --- |
| officialAgent.wizard.select | 135 |
| officialAgent.wizard.rename | 138 |
| officialAgent.wizard.mcp | 141 |
| officialAgent.wizard.model | 143 |
| officialAgent.wizard.back | 440 |
| officialAgent.wizard.next | 454 |
| officialAgent.wizard.installing | 465 |
| officialAgent.wizard.install | 466 |
| officialAgent.installModal.selectAtLeastOne | 205 |
| officialAgent.installModal.failed | 321, 976, 985 |
| officialAgent.installModal.title | 425 |
| officialAgent.rename.checkFailed | 223 |
| officialAgent.rename.checking | 356 |
| officialAgent.rename.title | 613 |
| officialAgent.rename.desc | 616 |
| officialAgent.rename.conflictWith | 636 |
| officialAgent.rename.name | 654 |
| officialAgent.install.goConfigure | 580, 997 |
| officialAgent.status.installed | 585, 972 |
| officialAgent.card.untitled | 531, 960 |
| officialAgent.modelStep.placeholder | 280, 775 |
| officialAgent.modelStep.desc | 752 |
| officialAgent.modelStep.embeddingLabel | 789 |
| officialAgent.modelStep.embeddingPlaceholder | 296 |
| officialAgent.mcpPreview.desc | 676 |
| officialAgent.mcpPreview.installed | 709 |
| officialAgent.mcpPreview.toInstall | 716 |
| officialAgent.step.inProgress | 898 |
| officialAgent.step.done | 937 |
| officialAgent.step.failed | 916 |

## 重灾区 2：工作台创建结果卡片（8 个）— 英文界面显示中文

文件：`frontend/features/workbench/components/CreationResultCards.tsx`（`t()` 第二参数中文 fallback）

| Key | 行号 | 中文 fallback |
| --- | --- | --- |
| workbench.creation.agentType | 62, 76 | "智能体应用" |
| workbench.creation.agentDraftReady | 81 | "草稿已生成" |
| workbench.creation.agentDraftSaved | 82 | "草稿已保存" |
| workbench.creation.openAgent | 96 | — |
| workbench.creation.skillCreated | 179 | — |
| workbench.creation.skillReady | 180 | — |
| workbench.creation.openSkills | 189 | — |
| workbench.creation.saveSkill | 219 | — |

## 重灾区 3：模型管理对话框（7 个）— 中文界面显示英文（反向问题）

| Key | 文件 | 行号 | 用户看到 |
| --- | --- | --- | --- |
| modelConfig.addDialog.baseUrl | ModelAddDialog.tsx | 647, 1179 | "Base URL" |
| modelConfig.addDialog.apiKey | ModelAddDialog.tsx | 670, 1163 | "API Key" |
| modelConfig.editDialog.apiKey | ModelEditDialog.tsx | 421 | "API Key" |
| modelConfig.editDialog.baseUrl | ModelEditDialog.tsx | 439 | "Base URL" |
| modelConfig.batchEdit.apiKey | ModelManagerDialog.tsx | 313 | "API Key" |
| modelConfig.batchEdit.baseUrl | ModelManagerDialog.tsx | 325 | "Base URL" |
| modelConfig.advancedConfig.topP | ModelAdvancedConfig.tsx | 183 | 英文兜底 |

注：PR 自己补了 modelConfig.addDialog.* 52 个 key，恰好漏掉 apiKey/baseUrl 这两个。

## 散点（12 个）

| Key | 文件 | 行号 | 页面 |
| --- | --- | --- | --- |
| common.selected | conversation-knowledge-scope-modal.tsx | 640 | 聊天知识库范围 |
| common.select | conversation-knowledge-scope-modal.tsx | 641 | 同上 |
| cfg.error.loadList | modelConfig.tsx | 582 | 模型列表加载失败 |
| cfg.error.loadListFailed | modelConfig.tsx | 583 | 同上 |
| knowledgeBase.message.noFiles | KnowledgeBaseConfiguration.tsx | 906 | 知识库空态 |
| mcpTools.publish.tagsInheritedHint | PublishConfirmModal.tsx | 286 | MCP 发布确认 |
| notifications.deepLink.mcpNotFound | my-mcp.tsx | 228 | 通知跳转 |
| a2a.security.requirementRequired | A2AAgentDiscoveryModal.tsx | 124 | A2A 发现弹窗 |
| common.error.loadFailed | space/evaluators/page.tsx | 26 | 评估器页 |

## 附：存量占位符不匹配（非本 PR 引入，建议一并修）

| Key | 问题 |
| --- | --- |
| agentEvaluation.step1.runningProgress | en `{{current}}/{{total}}` vs zh `{{done}}/{{remaining}}/{{total}}` |
| agentEvaluation.step1.runningHint | en 有 `{{done}}{{total}}`，zh 无占位符 |
| agentEvaluation.history.caseCount | en `{{count}}` vs zh `{{n}}` |
| chatStreamFinalMessage.maxStepsMessage | en 有 `{{completedSteps}}`，zh 无 |
| businessLogic.config.modal.deleteContent | zh 有 `{{name}}`，en 无 |
| mcpTools.repository.authorFallback | zh 有 `{{name}}`，en 无 |
