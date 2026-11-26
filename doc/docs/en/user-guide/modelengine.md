# ModelEngine Data Engineering and Model Engineering Integration Guide

This document describes how to integrate ModelEngine's model engineering (ModelLite) and data engineering (DataMate) in the Nexent platform, and the scope of the related deployment switch.

## 1. ModelEngine Overview

ModelEngine provides an end-to-end AI toolchain for data processing, knowledge generation, model fine-tuning and deployment, as well as RAG (Retrieval Augmented Generation) application development. It aims to shorten the cycle from data to model, and from data to AI application deployment. ModelEngine offers low-code orchestration, flexible execution scheduling, high-performance data bus and other technologies. Combined with built-in data processing operators, RAG framework and extensive ecosystem capabilities, it provides data development engineers, model development engineers, and application development engineers with an efficient, easy-to-use, open, flexible, out-of-the-box, and lightweight full-process AI development experience.

ModelEngine integration is controlled by the deployment switch `MODEL_ENGINE_ENABLED` (disabled by default; set it to `true` in deployment environment variables). The switch affects:

- Whether the "Sync ModelEngine Models" button appears on the Model Configuration page
- Whether the "DataMate Configuration" button appears on the Knowledge Base Configuration page, and the DataMate connection test
- The behavior of the knowledge base "Sync" button (when enabled, both local and DataMate knowledge bases are synced)

## 2. Integrating Model Engineering (ModelLite)

### 2.1 Model Engineering Overview

ModelLite is a toolchain for model fine-tuning and model inference, hosting and providing access to various AI models. After integrating ModelLite model services in Nexent, you can:

- Import all models deployed on the ModelEngine platform
- Use LLMs (Large Language Models) for conversation generation
- Use embedding models for knowledge base processing
- Use VLMs (Vision Language Models) to process images

### 2.2 Configuration steps

#### Step 1: Obtain ModelEngine access credentials

1. Visit your ModelEngine platform
2. Create an API Key (for authentication)
3. Note the ModelEngine service address (format: `https://<host>:<port>`)

> ⚠️ **Note**: Make sure the required models are already deployed on the ModelEngine platform, otherwise the model list will be empty after import.

#### Step 2: Batch import ModelEngine models in Nexent

1. Sign in to the Nexent platform and open the Model Configuration page
2. Select the **Sync ModelEngine Models** button (visible only when `MODEL_ENGINE_ENABLED` is enabled and the account has model management permissions). The Add Model dialog opens on the **Batch Add** tab
3. Under **Import from provider**, choose the provider **ModelEngine**:
   - **Base URL**: auto-filled with the ModelEngine service address, editable
   - **API Key**: the API Key created on the ModelEngine platform
   - Expand advanced settings to configure SSL verification, timeout, and custom headers if needed
4. Select **Fetch Model List** to pull all available models deployed on ModelEngine
5. **Check** the models to import in the returned list:
   - Each row allows changing the model type (LLM, Embedding, Rerank, STT, TTS, VLM, etc., auto-detected by default)
   - Optional: run a connectivity check for one row or in batch (not required for submission)
6. Select **Add N Models** to finish the import

Imported models appear in the model list with the **ModelEngine** source badge.

> 💡 **Note**: You can also import manually via Model Configuration → Add Model → Batch Add by selecting the ModelEngine provider; the result is identical to the sync button.

---

## 3. Integrating Data Engineering (DataMate)

### 3.1 What is DataMate

DataMate is an enterprise data processing platform for model fine-tuning and RAG retrieval, supporting data collection, data management, an operator marketplace, data cleaning, data synthesis, data labeling, data evaluation, knowledge generation, and other core capabilities. By integrating DataMate, you can:

- Reuse existing DataMate knowledge base resources
- Retrieve documents stored in DataMate within Nexent agents

### 3.2 Configuration steps

#### Step 1: Install and start the DataMate service

Deploy the DataMate service first. For installation details, refer to the [DataMate documentation](https://github.com/ModelEngine-Group/DataMate).

After startup, note the DataMate service address (e.g., `https://<host>:<port>`).

#### Step 2: Configure DataMate in Nexent

1. Sign in to the Nexent platform and open the Knowledge Base Configuration page
2. Select the **DataMate Configuration** button (visible only when `MODEL_ENGINE_ENABLED` is enabled)
3. Enter the **DataMate URL** in the dialog and save. On save, the system tests the connection and syncs DataMate knowledge bases once, then shows "DataMate configuration saved"
4. Use the **Sync** button at the top of the page at any time to refresh the list: when the switch is enabled, local and DataMate knowledge bases are shown together

Synced knowledge bases appear in the list with the source label "from datamate".

> ⚠️ **Note**: DataMate knowledge bases are external read-only resources — you cannot edit their name or permissions, upload or delete files, or delete the knowledge base in Nexent; perform such changes on the DataMate platform.

#### Step 3: Create or edit a knowledge retrieval agent

1. Open the Agent Configuration page
2. Create a new agent or edit an existing one

#### Step 4: Add the tool

On the agent configuration page:

1. Locate the tool management area and add the `datamate_search` tool to the agent
2. Select **Configure** on the tool row:
   - **server_url**: the Datamate server address (auto-filled when a DataMate URL has been configured)
   - Select **Select Knowledge Bases**, choose the Datamate knowledge bases to retrieve (multiple allowed), and confirm
3. The configuration applies to all calls of this agent

---

## 4. End-to-end example

### Scenario: create a knowledge retrieval agent

1. **Import ModelEngine models**
   - Open the Model Configuration page
   - Select "Sync ModelEngine Models", choose the ModelEngine provider, and enter the API Key
   - Fetch the model list, check the models to import, and pick an LLM as the agent's runtime model

2. **Integrate DataMate knowledge bases**
   - Open the Knowledge Base Configuration page
   - Select "DataMate Configuration" and enter the DataMate server address
   - Use "Sync" to fetch the available knowledge base list

3. **Create the agent**
   - Open Agent Configuration and create a new agent
   - Add the `datamate_search` tool and select the synced Datamate knowledge bases
   - Write a system prompt, e.g.: "You are a professional product assistant that answers user questions based on documents in the Datamate knowledge base."

4. **Test and use**
   - Interact with the agent on the Agent Chat page
   - Ask product-related questions; the agent retrieves relevant content from the Datamate knowledge base and answers

---

## 5. Related resources

- [Nexent documentation](https://modelengine-group.github.io/nexent)
- [ModelEngine documentation](https://support.huawei.com/enterprise/zh/fusioncube/modelengine-pid-261508006)
- [DataMate documentation](https://github.com/ModelEngine-Group/DataMate)
- [Dify Integration](./dify), [RAGFlow Integration](./ragflow), [iData Integration](./idata), [AIDP Integration](./aidp)

---

## 6. Technical support

If you run into problems, ask in [GitHub Discussions](https://github.com/ModelEngine-Group/nexent/discussions)
