# Agent Development

On the Agent Development page, you can generate an agent from natural-language requirements or configure it manually, then debug, publish, and manage versions in the same workspace. An agent can combine models, tools, skills, knowledge bases, and collaborative agents to complete tasks.

## Quick Navigation

This module contains the following pages:

| Page                                                                   | Description                                                                                                                            |
| ---------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| [Model Configuration](./agent-development/model-configuration)         | Connect and manage AI models, including LLMs, embedding models, vision-language models, rerank models, and speech models (TTS and STT) |
| [Knowledge Configuration](./agent-development/knowledge-configuration) | Create knowledge bases, check personal capacity, process documents, and manage chunks so agents can retrieve private data              |
| [Memory Configuration](./agent-development/memory-configuration)       | Manage tenant, user, and agent memory, and use Dreaming to consolidate stable short-term memories into long-term memory                 |
| [Agent Configuration](./agent-development/agent-configuration)         | Generate a complete configuration or optimize selected parts, adjust settings manually, bind resources, debug, publish, and manage versions |
| [Add External A2A Agents](./agent-development/a2a-external)             | Discover third-party agents through URL or Nacos and use them for agent collaboration                                                   |
| [Publish as A2A Agent](./agent-development/a2a-publish)                 | Make a published agent available for external systems to discover and call                                                             |

## Main Steps

1. **Configure Models** – Connect the AI models required by the agent in Model Management
2. **Prepare Knowledge Bases** – Create a knowledge base, upload documents, and confirm that their status is **Ready**
3. **Configure Memory** – Enable memory and configure a Dreaming schedule when needed
4. **Build the Agent** – Describe the business requirement and let Nexent recommend resources and generate the configuration, or fill in each setting manually
5. **Debug and Publish** – Verify prompts, tools, and collaboration flows, then publish a version after validation
