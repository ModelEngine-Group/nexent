# Model Configuration

In the Nexent sidebar, select **Agent Development → Model Configuration**. On the **Model Settings** page, use **Default Configuration** to choose the models Nexent uses when no model is explicitly configured. Use **Model Library** to add and manage models. When setting up Nexent for the first time, add a model to the library, then select it in Default Configuration.

<!-- TODO: Add a screenshot of the Model Settings page showing Default Configuration and Model Library. -->

## 🤖 Model Configuration

### Add a single model

1. In **Model Library**, select **Add Model → Single**.
2. Select a **Provider** and **Model Type**. Nexent fills in the service address for preset providers. You can edit it to match your deployment. For a custom service, enter its **Base URL**.
3. Enter the provider's **Model ID** or **Model Name**, such as `Qwen/Qwen3-8B`. The optional **Display Name** identifies the model in Nexent and defaults to the model name. Enter the **API Key** or other credentials shown in the form as required by your provider.
4. For a large language model, Nexent tries to match a **Model profile**. Review the match and select a profile manually if needed. A profile can prefill model settings. Review the values against what your service supports before saving. For other model types, use **Advanced Settings** where available, such as to configure chunking for an embedding model.
5. Select **Verify Connectivity** to test the connection. Review your settings, then select **Add Model**. The new model appears in Model Library.

<!-- TODO: Add a screenshot of the Single tab showing an LLM form and its matched model profile. -->

### Add models in batches

1. In **Model Library**, select **Add Model → Batch**.
2. Select a **Provider**, confirm or enter the **Base URL**, and enter the **API Key** if the provider requires one. Select **Fetch model list**. The endpoint must support model listing.
3. Search for and select the models to import. Use the controls on individual rows to change the model type or configure a model.
4. Verify models individually or select **Batch verify** to check the selected models. When ready, select **Add N models**.

When the ModelEngine integration is enabled, **Sync ModelEngine Models** opens the **Batch** tab directly.

<!-- TODO: Add a screenshot of the Batch tab after fetching the model list and selecting models. -->

### Set default models

In **Default Configuration**, open a dropdown and choose a model of the corresponding type from the library. Nexent saves your selection automatically. If the model you need is missing, add it to Model Library first.

| Priority | Models | Purpose |
| --- | --- | --- |
| Required | Large language model | Provides default chat, reasoning, and question answering. |
| Recommended | Text embedding and image understanding | Text embedding supports knowledge base indexing, semantic search, and memory. Image understanding supports questions about images. |
| Optional | Multimodal embedding, rerank, image generation, video understanding, audio understanding, speech recognition, and speech synthesis | Configure these for multimodal retrieval, reranking, multimodal processing, or voice input and output. |

Read the confirmation prompt before changing an active embedding model. This may affect existing files, knowledge bases, or memory.

### Manage the model library

- Search by model name or filter by **Type** and **Provider**. Each row shows the connection status. Models selected in Default Configuration carry a default badge.
- To change or remove a model, select **Edit** or **Delete** in its **Actions** column. Editable fields vary by model type. To change the model or profile used by a saved LLM outlet, add a new outlet.
- Select **Batch Edit**, then choose a connection group to update its **API Key** or **Base URL**. Use **Batch Delete** to select and remove one or more models in a single operation.

Accounts with view-only access cannot change defaults or manage models.

<!-- TODO: Add a screenshot of the Model Library with row actions and batch controls. -->

### Check model connectivity

- **Check the default models**. Select **Check Model Connectivity** at the top right of **Default Configuration** to verify the selected defaults. A green status indicates an available connection. You can view failure details and retry a failed check.
- **Check one model**. Find the model in **Model Library** and select **Verify Connectivity** on its row. If the check fails, review the **Base URL**, model ID or name, credentials, and provider permissions, then retry.

<!-- TODO: Add a screenshot showing a connectivity result and the retry control. -->

### 🤖 Supported Providers

#### Large Language Models

Nexent supports any **OpenAI-compatible** provider, including:

- [SiliconFlow](https://siliconflow.cn/)
- [Ali Bailian](https://bailian.console.aliyun.com/)
- [TokenPony](https://www.tokenpony.cn/)
- [DeepSeek](https://platform.deepseek.com/)
- [OpenAI](https://platform.openai.com/)
- [Anthropic](https://console.anthropic.com/)
- [Moonshot](https://platform.moonshot.cn/)

Getting started:

1. Sign up at the provider's portal.
2. Create and copy an API key.
3. Locate the API endpoint (usually ending with `/v1`).
4. In Nexent, go to **Model Library → Add Model** and enter the connection details from the provider.

#### Multimodal Models

Use the same API key and URL as LLMs but specify a multimodal model name, for example **Qwen/Qwen2.5-VL-32B-Instruct** on SiliconFlow.

#### Embedding Models

Use the same API key as LLMs but typically a different endpoint (often `/v1/embeddings`), for example **BAAI/bge-m3** from SiliconFlow.

#### Rerank Models

Use the same API key as LLMs but typically a different endpoint (often `/v1/rerank`).

#### Speech Models

Currently supports VolcEngine Voice and Aliyun Bailian voice models. VolcEngine requires `appid` and `token`, while Aliyun Bailian uses the same API key as the large language model.

**VolcEngine**
- **Website**: [volcengine.com/product/voice-tech](https://www.volcengine.com/product/voice-tech)
- **Free tier**: Available for individual use
- **Highlights**: High-quality Chinese/English TTS
- Recommended models: **Doubao Text-to-Speech Model 2.0** and **Large Model Streaming Speech Recognition**
- **Getting started**:

  1. Register a VolcEngine account.
  2. Enable the Voice Technology service.
  3. Create an app and generate `appid` and `token`.
  4. Configure the TTS/STT settings in the Add Model page.

**Aliyun Bailian**
- **Website**: [aliyun.com/benefit/scene/voice](https://www.aliyun.com/benefit/scene/voice)
- Recommended models: **Qwen3-TTS-Instruct-Flash-Realtime / Qwen3-TTS-Flash-Realtime** and **Qwen3-ASR-Flash-Realtime**
- **Getting started**:

  1. Register an Aliyun account.
  2. Enable the Qwen real-time voice service.
  3. Create an app and generate an API Key.
  4. Configure the TTS/STT settings in the Add Model page.

## 💡 Need Help

If you run into provider issues:

1. Review the provider's documentation.
2. Check API key permissions and quotas.
3. Test with the provider's official samples.
4. Ask the community in our [Discord server](https://discord.gg/tb5H3S3wyv).

## 🚀 Next Steps

After closing the Model Configuration flow, continue with:

1. **[Knowledge Base](./knowledge-configuration)** – Create and manage knowledge bases.
2. **[Agent Configuration](./agent-configuration)** – Build and configure agents.

Need help? Check the **[FAQ](../../quick-start/faq)** or open a thread in [GitHub Discussions](https://github.com/ModelEngine-Group/nexent/discussions).
