# ModelEngine 数据工程和模型工程对接指南

本文档详细介绍如何在 Nexent 平台中对接 ModelEngine 的数据工程(DataMate)和模型工程(ModelLite)。

## 1. ModelEngine介绍

ModelEngine提供从数据处理、知识生成，到模型微调和部署，以及RAG（Retrieval Augmented Generation）应用开发的AI训推全流程工具链，用于缩短从数据到模型、 数据到AI应用的落地周期。ModelEngine提供低代码编排、灵活的执行调度、高性能 数据总线等技术，结合内置的数据处理算子、RAG框架以及广泛的生态能力，为数据 开发工程师、模型开发工程师、应用开发工程师提供高效易用、开放灵活、开箱即用、轻量的全流程AI开发体验。

## 2. 对接模型工程（ModelLite）

### 2.1 模型工程介绍

ModelLite是一个面向模型微调和模型推理的工具链，托管并提供多种 AI 模型的访问服务。在 Nexent 中对接 ModelLite 模型服务后，您可以：

- 同步在 ModelEngine 平台上部署的所有模型
- 使用大语言模型 (LLM) 进行对话生成
- 使用向量化模型 (Embedding) 进行知识库处理
- 使用视觉语言模型 (VLM) 处理图片

### 2.2 配置步骤

#### 步骤 1：获取 ModelEngine 访问凭证

1. 访问您的 ModelEngine 平台
2. 创建 API Key（用于身份验证）
3. 记录 ModelEngine 的主机地址（格式：`https://<host>:<port>`）

> ⚠️ **注意**：确保您已在 ModelEngine 平台上部署了需要的模型，否则同步后将无法看到模型列表。

#### 步骤 2：在 Nexent 中配置 ModelEngine模型

1. 登录 Nexent 平台
2. 进入 **模型管理** 页面
3. 点击**模型设置中**的 **同步ModelEngine 配置** 按钮 (部署Nexent时，需将.env文件中 MODEL_ENGINE_ENABLED变量值改为 True)
4. 在弹窗中填写以下信息：
   - **主机地址**：ModelEngine 服务的 URL（如 `https://<host>:<port>`）
   - **模型类型**：选择对接的模型类型
   - **API Key**：ModelEngine API Key
5. 配置完成后，点击 **获取模型** 按钮，系统将自动获取 ModelEngine 上部署的所有可用模型，根据需要启用对应的模型。
6. 同步成功的模型将显示在模型列表中，并标记为 "ModelEngine" 来源。

---

## 3. 对接数据工程（DataMate）

### 3.1 什么是 Datamate

DataMate是面向模型微调与RAG检索的企业级数据处理平台，支持数据归集、数据管理、算子市场、数据清洗、数据合成、数据标注、数据评估、知识生成等核心功能。通过对接 Datamate，您可以：

- 复用已有的 Datamate 知识库资源
- 在 Nexent 智能体中检索 Datamate 中的文档

### 3.2 配置步骤

#### 步骤 1：安装和启动 Datamate 服务

首先，您需要部署 Datamate 服务。详细安装步骤请参考 [Datamate 官方文档](https://github.com/ModelEngine-Group/DataMate)。

启动后，记录 Datamate 的服务地址（如`https://<host>:<port>`）。

#### 步骤 2：在 Nexent 中配置 Datamate

1. 登录 Nexent 平台
2. 进入 **知识库** 页面
3. 点击 **DataMate 配置** 按钮
4. 填写 Datamate 服务器地址：
   - **Datamate URL**：Datamate 服务的地址（如 `https://<host>:<port>`）
5. 配置完成后，点击 **同步** 按钮，系统将自动获取 Datamate 中的所有知识库
6. 同步成功后，知识库将显示在知识库列表中，标记来源为 "DataMate"

#### 步骤 3：创建或编辑知识库检索智能体

1. 进入 **智能体开发** 页面
2. 创建新智能体或编辑现有智能体

#### 步骤 4：添加工具

在智能体配置页面：

1. 找到 **工具配置** 部分
2. 点击 **本地工具 > search** 按钮
3. 从工具列表中选择`datamate_search`工具：用于检索 Datamate 知识库
4. 配置`datamate_search`工具参数：

   a) 填写 Datamate 服务器地址（通常会自动填充您之前配置的地址）

   b) 点击 **选择知识库** 按钮

   c) 从知识库列表中选择要检索的 Datamate 知识库（可多选）

   d) 点击 **确定** 保存配置

---

## 4. 综合使用示例

### 场景：创建一个知识库检索智能体

1. **配置 ModelEngine 模型**
   - 进入模型管理页面
   - 点击 ModelEngine 配置，填写 API Key 和主机地址
   - 同步模型后，选择一个大语言模型作为智能体的运行模型

2. **对接 Datamate 知识库**
   - 进入知识库页面
   - 点击 DataMate 配置，填写 Datamate 服务器地址
   - 点击同步 DataMate 知识库，获取可用的知识库列表

3. **创建智能体**
   - 进入智能体管理，创建新智能体
   - 在工具配置中添加 `datamate_search` 工具
   - 选择已同步的 Datamate 知识库
   - 编写系统提示词，例如："你是一个专业的产品助手，可以根据 Datamate 知识库中的文档回答用户问题。"

4. **测试使用**
   - 在对话页面与智能体交互
   - 询问产品相关问题，智能体将自动从 Datamate 知识库检索相关内容并回答

---

## 5. 相关资源

- [Nexent 官方文档](https://modelengine-group.github.io/nexent)
- [ModelEngine 官方文档](https://support.huawei.com/enterprise/zh/fusioncube/modelengine-pid-261508006)
- [Datamate 官方文档](https://github.com/ModelEngine-Group/DataMate)

---

## 6. 技术支持

如果在使用过程中遇到问题，欢迎在 [GitHub Discussions](https://github.com/ModelEngine-Group/nexent/discussions) 提问
