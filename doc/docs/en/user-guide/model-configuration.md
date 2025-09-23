# Model Configuration

In the Model Configuration module, you can connect various types of AI models, including large language models, vector models, and vision language models. Nexent supports multiple model providers, allowing you to flexibly choose the most suitable models for your needs.

## 🔄 Sync ModelEngine Models

Nexent will soon support seamless integration with the ModelEngine platform, enabling automatic synchronization and use of all models you have deployed on ModelEngine. Stay tuned!

## 🛠️ Add Custom Models

### Add a Single Model

1. **Add a custom model**
   - Click the "Add Custom Model" button to open the add model dialog.
2. **Select model type**
   - Click the model type dropdown and select the type you want to add (Large Language Model/Embedding Model/Vision Language Model).
3. **Configure model parameters**
   - **Model Name (required):** Enter the model name as used in requests.
   - **Display Name:** Optionally set a display name for the model (defaults to the model name).
   - **Model URL (required):** Enter the API endpoint provided by the model provider.
   - **API Key:** Enter your API key.
4. **Connectivity Verification**
   - Click the "Verify" button. The system will send a test request and return the result.
5. **Save Model**
   - After configuration, click "Add" to add the model to the available models list.
<div style="display: flex; justify-content: left;">
  <img src="./assets/model/add-model.png" style="width: 50%; height: auto;" />
</div>

### Batch Add Models

To improve import efficiency, Nexent provides a batch model import feature.

1. **Batch Add Models**
   - In the add model dialog, enable the batch add switch.
2. **Select Model Provider**
   - Click the model provider dropdown and select a provider.
3. **Select Model Type**
   - Click the model type dropdown and select the type you want to add (LLM/Vector/Visual).
4. **Enter API Key (required)**
   - Enter your API key.
5. **Get Models**
   - Click the "Get Models" button to retrieve a list of models.
6. **Select Models**
   - The fetched models are disabled by default. You need to manually enable the models you want to use.
7. **Save Models**
   - After configuration, click "add" to add all selected models to the available models list.

<div style="display: flex; justify-content: left;">
  <img src="./assets/model/add-model-batch.png" style="width: 50%; height: auto;" />
</div>

🔧 Edit Custom Models

When you need to edit model configurations or delete models you no longer use, follow these steps:

1. Click the "Edit Custom Models" button.
2. Select the model type to edit or delete (LLM/Vector/Visual).
3. Choose whether to batch edit models or edit a single-instance custom model.
4. For batch edits, you can toggle model switches and add or remove models. Click the "Edit Configuration" button in the top-right to apply configuration edits to the selected models in bulk.
5. If you are editing a single-instance custom model, click the delete button 🗑️ to remove the target model. To edit its configuration, click the model name to open the edit dialog.

<div style="display: flex; gap: 8px;">
  <img src="./assets/model/edit-model-1.png" style="width: 50%; height: 100%;" />
  <img src="./assets/model/edit-model-2.png" style="width: 50%; height: 80%;" />
</div>
<br>
<div style="display: flex; gap: 8px;">
  <img src="./assets/model/edit-model-3.png" style="width: 50%; height: 100%;" />
  <img src="./assets/model/edit-model-4.png" style="width: 50%; height: 80%;" />
</div>
<br>
<div style="display: flex; gap: 8px;">
  <img src="./assets/model/edit-model-5.png" style="width: 50%; height: 100%;" />
  <img src="./assets/model/edit-model-6.png" style="width: 50%; height: 80%;" />
</div>


## ⚙️ Configure System Models

After adding models, you need to configure the system base model, which will be used for basic functions such as title generation and real-time file reading. When agents are running, you can specify specific models for each agent.

### Base Model Configuration
The system base model is used for core platform functions, including:
- Title generation
- Real-time file reading
- Basic text processing

**Configuration Steps:**
- Click the base model dropdown to select a model from the added large language models as the system base model.

### Agent Model Configuration
When creating and configuring agents, you can specify specific models for each agent:
- Each agent can independently select the large language model to use
- Support configuring different models for different agents to meet various business needs
- Agent model configuration will be set in the agent configuration page

## ✅ Check Model Connectivity

Regularly checking model connectivity is important for stable system operation. With the connectivity check feature, you can promptly discover and resolve model connection issues, ensuring service continuity and reliability.

**Check Process:**
- Click the "Check Model Connectivity" button
- The system will automatically test the connection status of all configured system models

**Status Indicators:**
- 🔵 **Blue dot:** Checking, please wait
- 🔴 **Red dot:** Connection failed, check configuration or network
- 🟢 **Green dot:** Connection normal, model is available

**Troubleshooting Suggestions:**
- Check if the network connection is stable
- Verify that the API key is valid and not expired
- Confirm the service status of the model provider
- Check firewall and security policy settings

For detailed configuration information about model providers, please refer to our **[Model Provider Guide](../getting-started/model-providers)**.

## 🚀 Next Steps

After completing model configuration, we recommend you click "Next" to continue with:

1. **[Knowledge Base Configuration](./knowledge-base-configuration)** – Create and manage knowledge bases
2. **[Agent Configuration](./agent-configuration)** – Create and configure agents

If you encounter any issues during model configuration, please refer to our **[FAQ](../getting-started/faq)** or join our [Discord community](https://discord.gg/tb5H3S3wyv) for support. 