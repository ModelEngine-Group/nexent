# Nexent 模型模块

本模块提供了多种AI模型服务，包括语音服务、嵌入模型、大语言模型和视觉语言模型。每个模型都遵循统一的接口设计，支持配置管理和错误处理。

## 📋 目录

- [语音服务 (STT & TTS)](#语音服务-stt--tts)
- [嵌入模型](#嵌入模型)
- [大语言模型](#大语言模型)
- [视觉语言模型](#视觉语言模型)
- [模型能力与治理](#模型能力与治理)

## 🎤 语音服务 (STT & TTS)

SDK 在 `nexent.core.models` 中提供 STT/TTS 模型类（`BaseSTTModel` / `BaseTTSModel` 抽象基类，以及 `VolcSTTModel`、`VolcTTSModel`、`AliSTTModel`、`AliTTSModel` 实现，其中阿里云实现基于 DashScope Qwen Realtime WebSocket 协议）。在此之上，后端语音服务（backend/apps/voice_app.py）提供一个统一的语音服务，在单个端口上同时运行语音识别(STT)和语音合成(TTS)服务，使用WebSocket进行实时通信。

### 功能特点

- **语音识别(STT)**: 通过WebSocket连接进行实时音频转写
- **语音合成(TTS)**: 通过WebSocket流式传输将文本转换为音频
- **单一端口**: 两种服务在同一端口上运行，简化部署和使用
- **仅WebSocket**: 两种服务使用一致的WebSocket API模式
- **流式处理**: 支持实时流式音频识别和合成，提供低延迟体验
- **错误处理**: 完善的错误处理和状态反馈机制


### API端点

#### 语音识别(STT)

- WebSocket: `/voice/stt/ws`（runtime 服务，端口 5014）
  - **首条消息**: JSON 配置（文本或二进制 JSON 均可），可包含 `model_factory`、`api_key`、`model_appid`、`access_token`、`language`、`base_url` 等字段；缺省时回退到租户模型配置
  - **后续消息**: 以二进制块流式传输 PCM 音频数据
  - **音频要求**: 16kHz采样率, 16位深度, 单声道, PCM原始格式
  - **响应格式**: 实时JSON转写结果
  - **响应字段**:
    - 火山引擎: 转发火山原始 payload，识别文本位于 `result.text`
    - 阿里云: `{"text": "识别文本", "is_final": true/false}`
    - `vad`: VAD 事件（`started` / `stopped`，阿里云实现）
    - `status`: 服务状态信息（`ready` / `processing`）
    - `error`: 如有错误，包含错误信息

#### 语音合成(TTS)

- WebSocket: `/voice/tts/ws`（runtime 服务，端口 5014）
  - **首条消息**: 发送JSON格式的文本: `{"text": "要合成的文本"}`，可额外携带 `model_factory`、`api_key`、`model_appid`、`access_token`、`base_url`、`tenant_id`、`model_name` 等配置
  - **响应格式**: 二进制音频块 (默认为MP3格式)
  - **完成信号**: 最终消息: `{"status": "completed"}`
  - **错误响应**: `{"error": "错误信息"}`

## 🔗 嵌入模型

嵌入模型提供了将文本、图像等多种数据类型转换为向量表示的能力，支持多种后端服务。

### 功能特点

-   **多后端支持**: 支持 Jina、OpenAI 兼容、DashScope、Siliconflow 等嵌入服务。
-   **统一文本接口**: 所有模型均提供统一的 `get_embeddings` 方法，接受字符串或字符串列表作为输入，方便处理纯文本数据。
-   **多模态能力**: 多模态嵌入模型额外提供 `get_multimodal_embeddings` 方法，处理包含文本和图像的混合输入。支持 `JinaEmbedding`（`jina-clip-v2`）、`DashScopeMultimodalEmbedding`（`tongyi-embedding-vision`）、`SiliconflowMultimodalEmbedding`（`Qwen3-VL-Embedding` 系列）。
-   **图像输入格式**: `image` 值支持 URL 和原始 bytes。bytes 会自动编码为 base64 data URI（Jina / Siliconflow 按 MIME 类型检测，DashScope 固定转为 PNG）。
-   **参数化配置**: 所有配置通过构造函数参数传入，SDK 不读取环境变量。

### 使用示例

#### 获取文本嵌入 (所有模型通用)

所有嵌入模型都使用 `get_embeddings` 方法来获取文本的嵌入向量。此方法接受单个字符串或字符串列表。

```python
from nexent.core.models.embedding_model import JinaEmbedding, OpenAICompatibleEmbedding

# 初始化Jina模型 (同样适用于OpenAICompatibleEmbedding)
embedding = JinaEmbedding(api_key="your_jina_api_key")

# 获取单个文本的嵌入
text_input = "Hello, Nexent!"
embeddings = embedding.get_embeddings(text_input)
print(f"单文本嵌入向量数量: {len(embeddings)}")

# 获取多个文本的嵌入
text_list_input = ["这是第一段文本。", "这是第二段文本。"]
embeddings_list = embedding.get_embeddings(text_list_input)
print(f"多文本嵌入向量数量: {len(embeddings_list)}")
```

#### 获取多模态嵌入 (JinaEmbedding)

对于支持多模态输入的模型（如 `JinaEmbedding`），可以使用 `get_multimodal_embeddings` 方法来处理包含文本和图像的混合输入。

```python
from nexent.core.models.embedding_model import JinaEmbedding

# 初始化Jina模型
embedding = JinaEmbedding(api_key="your_jina_api_key")

# 定义包含文本和图像的多模态输入（image 支持 URL 或原始 bytes）
multimodal_input = [
    {"text": "A beautiful sunset over the beach"},
    {"image": "https://example.com/sunset.jpg"}
]

# 获取多模态嵌入
multimodal_embeddings = embedding.get_multimodal_embeddings(multimodal_input)
print(f"多模态嵌入向量数量: {len(multimodal_embeddings)}")
```


## 🤖 大语言模型

大语言模型提供了文本生成和对话能力，基于OpenAI API实现。

### 功能特点

- **流式输出**: 支持实时流式文本生成
- **温度控制**: 可调节生成文本的随机性
- **上下文管理**: 支持多轮对话和上下文保持
- **工具调用**: 支持函数调用和工具使用

### 使用示例

```python
from nexent.core.models.openai_llm import OpenAIModel
from nexent.core.utils.observer import MessageObserver

# 初始化模型
observer = MessageObserver()
model = OpenAIModel(
    model_id="your-model-id",
    api_key="your-api-key",
    api_base="your-api-base",
    observer=observer,
    temperature=0.2,
    top_p=0.95
)

# 发送消息
messages = [{"role": "user", "content": "Hello"}]
response = model(messages=messages)
```

## 👁️ 视觉语言模型

视觉语言模型结合了图像理解和文本生成能力，支持图像描述和视觉问答。

### 功能特点

- **图像处理**: 支持本地图像文件路径和文件流（BinaryIO），图像自动编码为 base64 传输
- **流式输出**: 支持实时流式文本生成
- **提示词定制**: 可自定义系统提示词
- **多模态理解**: 结合视觉和语言理解能力

### 使用示例

```python
from nexent.core.models.openai_vlm import OpenAIVLModel
from nexent.core.utils.observer import MessageObserver

# 初始化模型（model_id / api_key / api_base 经 kwargs 传给底层 OpenAI 兼容客户端）
observer = MessageObserver()
model = OpenAIVLModel(
    observer=observer,
    model_id="your-vlm-model-id",
    api_key="your-api-key",
    api_base="your-api-base"
)

# 分析图像
image_path = "path/to/image.jpg"
result = model.analyze_image(image_path, system_prompt="请描述这张图片")
```

## 🧭 模型能力与治理

- **模型类型全覆盖**：llm / vlm（vlm2-vlm4 分类，支持图/视频/音频理解）/ embedding / rerank / stt / tts / realtime（DashScope 实时 WebSocket）
- **Provider 扩展**：STT/TTS 继承 `BaseSTTModel` / `BaseTTSModel`（火山引擎、阿里云、ModelEngine、DashScope 等）
- **重试机制**：`core/models/retry.py` 的 `ModelRetryConfig`（max_attempts、backoff_base_seconds、max_backoff_seconds、jitter），对瞬时错误指数退避重试
- **可选 logprobs**：模型配置包含 logprobs 时自动传参
- **元数据参数机制**：支持元数据透传并含 prompt 注入防护
- **并发治理**：租户级模型并发上限与超时配置

## 🔧 通用特性

所有模型都支持以下通用特性：

### 错误处理

- 连接错误捕获和处理
- 服务状态监控和反馈
- 客户端友好的错误消息

### 配置管理

- 环境变量配置
- .env文件支持
- 运行时配置覆盖

### 连接测试

模型类提供了用于测试与远程服务连接状态的方法（均为异步接口）：

```python
import asyncio

# 测试连接
connected = asyncio.run(model.check_connectivity())
if connected:
    print("服务连接正常")
else:
    print("服务连接失败")
``` 