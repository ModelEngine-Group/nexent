# Nexent SDK

Nexent is a powerful, enterprise-grade Agent SDK that revolutionizes intelligent agent development. Built on proven enterprise architecture, it provides a comprehensive solution for building production-ready AI agents with distributed processing, real-time streaming, multi-modal capabilities, and an extensive ecosystem of tools and models.

## 🚀 Installation and Usage

For detailed installation instructions and usage guides, see our **[Basic Usage Guide](./basic-usage#using-agent_run-recommended-for-streaming)** for both `CoreAgent.run` and streaming `agent_run`.

## ⭐ Key Features

### 🏢 Enterprise-grade Agent Framework
Extended from SmolAgents, built specifically for enterprise environments with proper scaling and monitoring capabilities.

### ⚡ Distributed Processing Capabilities
High-performance asynchronous architecture based on asyncio, supporting large-scale data batch processing and optimization.

### 🔧 Rich Agent Tool Ecosystem
Support for EXA, Tavily, Linkup web search, IMAP/SMTP email functionality, and Model Context Protocol tool integration.

### 🎭 Multi-modal Support
Integrated STT & TTS voice services, support for image understanding and processing, and long context models.

### 📊 Powerful Data Processing Capabilities
Processing multiple document formats (currently 17 extensions supported) with intelligent chunking strategies and memory streaming processing.

### 🔍 Vector Database Integration
Enterprise-grade Elasticsearch vector search with hybrid search and large-scale optimization support.

### 🌉 Gateway Adapter Architecture
LLM/Embedding/Rerank/VLM models are integrated through `AdapterRegistry` with unified registration by `(factory, modality)`, and transport-layer parameters are configurable (`core/gateway/registry.py`, `transport.py`).

### 🧠 Memory & Dreaming
Three-tier Tenant/User/Agent memory + proactive memory tools + Dreaming memory consolidation (`memory/dreaming/`).

### 🏁 Benchmark
Built-in `agent_runner`, `acon_eval`, and `eventqa_eval` evaluation scaffolds plus a general-purpose evaluation comparison harness.

For detailed features and usage instructions, please refer to **[Features Explained](./features)** and **[Basic Usage Guide](./basic-usage)**.

## 🤖 Agent Framework

Nexent provides complete intelligent agent solutions with multi-model support, MCP integration, dynamic tool loading, and distributed execution.

- Quick streaming run: **[Streaming with agent_run](./basic-usage#using-agent_run-recommended-for-streaming)**
- Detailed Agent development and usage: **[Agents](./core/agents)**

## 🛠️ Tool Collection

Nexent provides a rich tool ecosystem supporting multiple types of task processing. All tools follow unified development standards to ensure consistency and extensibility.

For detailed tool development standards and comprehensive tool documentation, please refer to: **[Tool Development Guide](./core/tools)**

## 📊 Data Processing Capabilities

Enterprise-grade document processing capabilities providing distributed processing support for 20+ document formats, intelligent chunking strategies, and memory optimization.

For detailed data processing capabilities and usage examples, please refer to: **[Data Processing Guide](./data-process)**

## 🔍 Vector Database Capabilities

Provides enterprise-grade vector search and document management capabilities with multiple search modes, embedding model integration, and large-scale optimization.

For comprehensive vector database integration and configuration, please refer to: **[Vector Database Guide](./vector-database)**

## 🤖 Model Services

Provides unified multi-modal AI model services with support for various model types and providers.

For comprehensive model integration and usage documentation, please refer to: **[Model Architecture Guide](./core/models)**

For more detailed usage instructions, please refer to the dedicated documentation for each module. 