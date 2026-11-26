# ModelEngine 数据工程和模型工程对接指南

本文档介绍如何在 Nexent 平台中对接 ModelEngine 的模型工程（ModelLite）和数据工程（DataMate），以及相关部署开关的作用范围。

## 1. ModelEngine 介绍

ModelEngine 提供从数据处理、知识生成，到模型微调和部署，以及 RAG（Retrieval Augmented Generation）应用开发的 AI 训推全流程工具链，用于缩短从数据到模型、数据到 AI 应用的落地周期。ModelEngine 提供低代码编排、灵活的执行调度、高性能数据总线等技术，结合内置的数据处理算子、RAG 框架以及广泛的生态能力，为数据开发工程师、模型开发工程师、应用开发工程师提供高效易用、开放灵活、开箱即用、轻量的全流程 AI 开发体验。

对接 ModelEngine 由部署开关 `MODEL_ENGINE_ENABLED` 控制（默认关闭，需在部署环境变量中设置为 `true`）。该开关同时影响：

- 「模型配置」页面中「同步ModelEngine模型」按钮的显示
- 「知识库配置」页面中「DataMate配置」按钮的显示与 DataMate 连接测试
- 知识库「同步」按钮的行为（开启时同时同步本地与 DataMate 知识库）

## 2. 对接模型工程（ModelLite）

### 2.1 模型工程介绍

ModelLite 是一个面向模型微调和模型推理的工具链，托管并提供多种 AI 模型的访问服务。在 Nexent 中对接 ModelLite 模型服务后，您可以：

- 导入在 ModelEngine 平台上部署的所有模型
- 使用大语言模型（LLM）进行对话生成
- 使用向量化模型（Embedding）进行知识库处理
- 使用视觉语言模型（VLM）处理图片

### 2.2 配置步骤

#### 步骤 1：获取 ModelEngine 访问凭证

1. 访问您的 ModelEngine 平台
2. 创建 API Key（用于身份验证）
3. 记录 ModelEngine 服务的访问地址（格式：`https://<host>:<port>`）

> ⚠️ **注意**：确保您已在 ModelEngine 平台上部署了需要的模型，否则导入后将无法看到模型列表。

#### 步骤 2：在 Nexent 中批量导入 ModelEngine 模型

1. 登录 Nexent 平台，进入「模型配置」页面
2. 点击 **同步ModelEngine模型** 按钮（仅 `MODEL_ENGINE_ENABLED` 开启且具有模型管理权限的账号可见），系统会打开「添加模型」弹窗并定位到 **批量添加** 页签
3. 在 **从服务商导入** 中选择服务商 **ModelEngine**：
   - **Base URL**：自动填充 ModelEngine 服务地址，可手动修改
   - **API Key**：ModelEngine 平台创建的 API Key
   - 如需自定义连接行为，可展开高级设置配置 SSL 校验、超时时间和自定义请求头
4. 点击 **获取模型列表**，系统将自动拉取 ModelEngine 上部署的所有可用模型
5. 在返回的模型列表中**勾选**需要导入的模型：
   - 每行可修改模型类型（LLM、Embedding、Rerank、STT、TTS、VLM 等，默认按模型自动识别）
   - 可选：对单个模型或批量执行连通性检测（不影响提交）
6. 点击 **添加 N 个模型** 完成导入

导入成功的模型将显示在模型列表中，并带有 **ModelEngine** 来源标识。

> 💡 **说明**：也可在「模型配置」→「添加模型」→「批量添加」页签中手动选择 ModelEngine 服务商完成导入，效果与同步按钮一致。

---

## 3. 对接数据工程（DataMate）

### 3.1 什么是 DataMate

DataMate 是面向模型微调与 RAG 检索的企业级数据处理平台，支持数据归集、数据管理、算子市场、数据清洗、数据合成、数据标注、数据评估、知识生成等核心功能。通过对接 DataMate，您可以：

- 复用已有的 DataMate 知识库资源
- 在 Nexent 智能体中检索 DataMate 中的文档

### 3.2 配置步骤

#### 步骤 1：安装和启动 DataMate 服务

首先，您需要部署 DataMate 服务。详细安装步骤请参考 [DataMate 官方文档](https://github.com/ModelEngine-Group/DataMate)。

启动后，记录 DataMate 的服务地址（如 `https://<host>:<port>`）。

#### 步骤 2：在 Nexent 中配置 DataMate

1. 登录 Nexent 平台，进入「知识库配置」页面
2. 点击 **DataMate配置** 按钮（仅 `MODEL_ENGINE_ENABLED` 开启时显示）
3. 在弹窗中填写 **DataMate URL** 并保存。保存时系统会自动测试连接并同步一次 DataMate 知识库，成功后提示「DataMate配置已保存」
4. 之后可随时点击页面右上角 **同步** 按钮刷新知识库列表：开关开启时会合并展示本地知识库与 DataMate 知识库

同步成功的知识库将显示在知识库列表中，来源标记为「来自datamate」。

> ⚠️ **注意**：DataMate 知识库为外部只读资源——不能在 Nexent 中编辑其名称与权限、上传或删除文件、删除知识库；如需变更请前往 DataMate 平台操作。

#### 步骤 3：创建或编辑知识库检索智能体

1. 进入「智能体配置」页面
2. 创建新智能体或编辑现有智能体

#### 步骤 4：添加工具

在智能体配置页面：

1. 找到 **工具管理** 区域，将 `datamate_search` 工具添加到智能体
2. 点击该工具行的 **配置** 按钮：
   - **server_url**：Datamate 服务器地址（已配置过 DataMate URL 时会自动填充）
   - 点击 **选择知识库**，从列表中选择要检索的 Datamate 知识库（可多选），确认保存
3. 配置对该智能体的所有调用生效

---

## 4. 综合使用示例

### 场景：创建一个知识库检索智能体

1. **导入 ModelEngine 模型**
   - 进入「模型配置」页面
   - 点击「同步ModelEngine模型」，选择 ModelEngine 服务商并填写 API Key
   - 获取模型列表并勾选导入，选择一个大语言模型作为智能体的运行模型

2. **对接 DataMate 知识库**
   - 进入「知识库配置」页面
   - 点击「DataMate配置」，填写 DataMate 服务器地址并保存
   - 通过「同步」获取可用的知识库列表

3. **创建智能体**
   - 进入「智能体配置」，创建新智能体
   - 在工具管理中添加 `datamate_search` 工具并选择已同步的 Datamate 知识库
   - 编写系统提示词，例如："你是一个专业的产品助手，可以根据 Datamate 知识库中的文档回答用户问题。"

4. **测试使用**
   - 在「智能体对话」页面与智能体交互
   - 询问产品相关问题，智能体将自动从 Datamate 知识库检索相关内容并回答

---

## 5. 相关资源

- [Nexent 官方文档](https://modelengine-group.github.io/nexent)
- [ModelEngine 官方文档](https://support.huawei.com/enterprise/zh/fusioncube/modelengine-pid-261508006)
- [Datamate 官方文档](https://github.com/ModelEngine-Group/DataMate)
- [Dify 知识库对接](./dify)、[RAGFlow 知识库对接](./ragflow)、[iData 知识库对接](./idata)、[AIDP 知识库对接](./aidp)

---

## 6. 技术支持

如果在使用过程中遇到问题，欢迎在 [GitHub Discussions](https://github.com/ModelEngine-Group/nexent/discussions) 提问
