# ModelEngine Data Engineering and Model Engineering Integration Guide

This document provides a detailed guide on how to integrate ModelEngine's Data Engineering (DataMate) and Model Engineering (ModelLite) in the Nexent platform.

## 1. ModelEngine Overview

ModelEngine provides an end-to-end AI toolchain for data processing, knowledge generation, model fine-tuning and deployment, as well as RAG (Retrieval Augmented Generation) application development. It aims to shorten the cycle from data to model, and from data to AI application deployment. ModelEngine offers low-code orchestration, flexible execution scheduling, high-performance data bus and other technologies. Combined with built-in data processing operators, RAG framework and extensive ecosystem capabilities, it provides data development engineers, model development engineers, and application development engineers with an efficient, easy-to-use, open, flexible, out-of-the-box, and lightweight full-process AI development experience.

## 2. Integrating Model Engineering (ModelLite)

### 2.1 Model Engineering Overview

ModelLite is a toolchain for model fine-tuning and model inference, hosting and providing access to various AI models. After integrating ModelLite model services in Nexent, you can:

- Sync all models deployed on the ModelEngine platform
- Use Large Language Models (LLM) for conversation generation
- Use Embedding models for knowledge base processing
- Use Vision Language Models (VLM) for image processing

### 2.2 Configuration Steps

#### Step 1: Obtain ModelEngine Credentials

1. Visit your ModelEngine platform
2. Create an API Key (for authentication)
3. Record the ModelEngine host address (format: `https://<host>:<port>`)

> ⚠️ **Note**: Make sure you have deployed the required models on ModelEngine, otherwise you won't see any models after syncing.

#### Step 2: Configure ModelEngine Models in Nexent

1. Log in to Nexent platform
2. Go to **Model Management** page
3. Click **Sync ModelEngine Configuration** button in **Model Settings** (when deploying Nexent, need to change the value of MODEL_ENGINE_ENABLED variable to True in the .env file)
4. Fill in the following information in the popup:
   - **Host Address**: ModelEngine service URL (e.g., `https://<host>:<port>`)
   - **Model Type**: Select the model type to integrate
   - **API Key**: ModelEngine API Key
5. After configuration, click **Get Models** button. The system will automatically fetch all available models deployed on ModelEngine. Enable the models as needed.
6. Successfully synced models will appear in the model list, marked with "ModelEngine" as the source.

---

## 3. Integrating Data Engineering (DataMate)

### 3.1 What is Datamate

DataMate is an enterprise-level data processing platform for model fine-tuning and RAG retrieval. It supports core functions such as data collection, data management, operator marketplace, data cleaning, data synthesis, data annotation, data evaluation, and knowledge generation. By integrating Datamate, you can:

- Reuse existing Datamate knowledge base resources
- Retrieve Datamate documents in Nexent agents

### 3.2 Configuration Steps

#### Step 1: Install and Start Datamate Service

First, you need to deploy the Datamate service. For detailed installation instructions, refer to [Datamate Official Documentation](https://github.com/ModelEngine-Group/DataMate).

After startup, record the Datamate service address (e.g., `https://<host>:<port>`).

#### Step 2: Configure Datamate in Nexent

1. Log in to Nexent platform
2. Go to **Knowledge Base** page
3. Click **DataMate Configuration** button
4. Fill in the Datamate server address:
   - **Datamate URL**: Datamate service address (e.g., `https://<host>:<port>`)
5. After configuration, click **Sync** button. The system will automatically fetch all knowledge bases from Datamate
6. After successful sync, knowledge bases will appear in the knowledge base list, marked with source as "DataMate"

#### Step 3: Create or Edit Knowledge Base Retrieval Agent

1. Go to **Agent Development** page
2. Create a new agent or edit an existing one

#### Step 4: Add Tools

In the agent configuration page:

1. Find the **Tool Configuration** section
2. Click **Local Tools > Search** button
3. Select `datamate_search` tool from the tool list: for retrieving Datamate knowledge bases
4. Configure `datamate_search` tool parameters:

   a) Fill in the Datamate server address (usually auto-filled from your previous configuration)

   b) Click **Select Knowledge Base** button

   c) Select Datamate knowledge bases to retrieve from the knowledge base list (multiple selection supported)

   d) Click **Confirm** to save configuration

---

## 4. Comprehensive Usage Example

### Scenario: Creating a Knowledge Base Retrieval Agent

1. **Configure ModelEngine Models**
   - Go to Model Management page
   - Click ModelEngine Configuration, fill in API Key and host address
   - After syncing models, select a Large Language Model as the agent's runtime model

2. **Integrate Datamate Knowledge Base**
   - Go to Knowledge Base page
   - Click DataMate Configuration, fill in Datamate server address
   - Click Sync DataMate Knowledge Bases to get available knowledge base list

3. **Create Agent**
   - Go to Agent Management, create a new agent
   - Add `datamate_search` tool in tool configuration
   - Select synced Datamate knowledge bases
   - Write system prompt, for example: "You are a professional product assistant. You can answer user questions based on documents from the Datamate knowledge base."

4. **Test Usage**
   - Interact with the agent on the chat page
   - Ask product-related questions, the agent will automatically retrieve relevant content from Datamate knowledge base and respond

---

## 5. Related Resources

- [Nexent Official Documentation](https://modelengine-group.github.io/nexent)
- [ModelEngine Official Documentation](https://support.huawei.com/enterprise/zh/fusioncube/modelengine-pid-261508006)
- [Datamate Official Documentation](https://github.com/ModelEngine-Group/DataMate)

---

## 6. Technical Support

If you encounter issues during usage, feel free to ask questions on [GitHub Discussions](https://github.com/ModelEngine-Group/nexent/discussions)
