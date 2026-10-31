# Nexent Model Architecture

Nexent provides a comprehensive model architecture supporting multiple AI model types through OpenAI-compatible interfaces. The SDK supports large language models, multimodal models, embedding models, and speech processing capabilities.

## 📋 Overview

The models module provides standardized interfaces for various AI model providers and types:

## 🎯 Supported Model Categories

### 🤖 Large Language Models (LLM)
- **OpenAI-compatible models**: Any provider following OpenAI API specification
- **Long context models**: Support for extended context windows
- **Multimodal language models**: Text + image processing capabilities
- **Local deployment**: Ollama, vLLM, and other self-hosted solutions

### 🎭 Vision Language Models (VLM)
- **Multimodal understanding**: Process text, images, and documents simultaneously
- **OpenAI-compatible VLMs**: GPT-4V, Claude-3, and compatible models
- **Document analysis**: OCR, table extraction, and visual reasoning

### 🔤 Embedding Models
- **Universal compatibility**: All OpenAI-compatible embedding services
- **Multi-backend support**: Jina, OpenAI-compatible, DashScope, Siliconflow, and other embedding services
- **Multilingual support**: International language processing
- **Multimodal embeddings**: Multimodal embedding models additionally provide the `get_multimodal_embeddings` method for mixed text + image input (`JinaEmbedding`, `DashScopeMultimodalEmbedding`, `SiliconflowMultimodalEmbedding`)
- **Specialized embeddings**: Document, code, and domain-specific embeddings
- **Vector database integration**: Seamless integration with vector stores

### 🎤 Speech Processing Models
- **Text-to-Speech (TTS)**: Multiple provider support
- **Speech-to-Text (STT)**: Real-time and batch processing
- **Voice cloning**: Advanced voice synthesis capabilities
- **Multilingual speech**: Support for multiple languages and accents

The SDK provides STT/TTS model classes in `nexent.core.models` (`BaseSTTModel` / `BaseTTSModel` abstract base classes, plus `VolcSTTModel`, `VolcTTSModel`, `AliSTTModel`, `AliTTSModel` implementations, where the Aliyun implementations are based on the DashScope Qwen Realtime WebSocket protocol). On top of these, the backend voice service (backend/apps/voice_app.py) provides a unified voice service that runs both speech recognition (STT) and speech synthesis (TTS) on a single port, using WebSocket for real-time communication:

- STT WebSocket: `/voice/stt/ws` (runtime service, port 5014) — the first message is a JSON config (text or binary JSON) that may include `model_factory`, `api_key`, `model_appid`, `access_token`, `language`, `base_url`, etc., falling back to tenant model configuration when omitted; subsequent messages stream PCM audio data in binary chunks
- TTS WebSocket: `/voice/tts/ws` (runtime service, port 5014) — the first message is JSON text `{"text": "text to synthesize"}`, optionally carrying `model_factory`, `api_key`, `model_appid`, `access_token`, `base_url`, `tenant_id`, `model_name`, etc.; the response is binary audio chunks (MP3 by default)

## 🏗️ Model Implementation Classes

## 💡 Usage

```python
from nexent.core.models import OpenAIModel

# Initialize OpenAI model
model = OpenAIModel(
    model_id="your-model-id",
    api_key="your-api-key",
    api_base="your-api-base"
)
```

## 🧭 Model Capabilities & Governance

- **Full model type coverage**: llm / vlm (vlm2-vlm4 categories, supporting image/video/audio understanding) / embedding / rerank / stt / tts / realtime (DashScope realtime WebSocket)
- **Provider extensibility**: STT/TTS inherit from `BaseSTTModel` / `BaseTTSModel` (Volcano Engine, Aliyun, ModelEngine, DashScope, etc.)
- **Retry mechanism**: `ModelRetryConfig` in core/models/retry.py (max_attempts, backoff_base_seconds, max_backoff_seconds, jitter) retries transient errors with exponential backoff
- **Optional logprobs**: automatically passed through when the model configuration includes logprobs
- **Metadata parameter mechanism**: supports metadata passthrough with prompt injection protection
- **Concurrency governance**: tenant-level model concurrency limits and timeout configuration

## ⚙️ Configuration

All configuration is passed through constructor parameters; the SDK does not read environment variables — services read configuration centrally and pass it to the SDK.

For detailed usage examples and API reference, see the SDK documentation.