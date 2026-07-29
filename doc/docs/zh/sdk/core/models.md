# Nexent 模型模块

本模块提供了多种AI模型服务，包括语音服务、嵌入模型、大语言模型和视觉语言模型。每个模型都遵循统一的接口设计，支持配置管理和错误处理。

## 📋 目录

- [语音服务 (STT & TTS)](#语音服务-stt--tts)
- [嵌入模型](#嵌入模型)
- [大语言模型](#大语言模型)
- [视觉语言模型](#视觉语言模型)

## 🎤 语音服务 (STT & TTS)

本模块提供了一个统一的语音服务，在单个端口上同时运行语音识别(STT)和语音合成(TTS)服务，使用WebSocket进行实时通信。

### 功能特点

- **语音识别(STT)**: 通过WebSocket连接进行实时音频转写
- **语音合成(TTS)**: 通过WebSocket流式传输将文本转换为音频
- **单一端口**: 两种服务在同一端口上运行，简化部署和使用
- **仅WebSocket**: 两种服务使用一致的WebSocket API模式
- **流式处理**: 支持实时流式音频识别和合成，提供低延迟体验
- **错误处理**: 完善的错误处理和状态反馈机制

### 设置

1. 创建一个包含API凭证的`.env`文件:

```
# STT配置
APPID=your_stt_appid
TOKEN=your_token

# TTS配置
APPID=your_tts_appid
TOKEN=your_tts_token
CLUSTER=your_cluster
VOICE_TYPE=your_voice_type
```

### API端点

#### 语音识别(STT)

- WebSocket: `/stt/ws`
  - **请求格式**: 以二进制块流式传输PCM音频数据
  - **音频要求**: 16kHz采样率, 16位深度, 单声道, PCM原始格式
  - **响应格式**: 实时JSON转写结果
  - **响应字段**:
    - `result` 或 `trans_result.text`: 识别的文本
    - `is_final`: 是否为最终结果
    - `status`: 服务状态信息
    - `error`: 如有错误，包含错误信息

#### 语音合成(TTS)

- WebSocket: `/tts/ws`
  - **请求格式**: 发送JSON格式的文本: `{"text": "要合成的文本"}`
  - **响应格式**: 二进制音频块 (默认为MP3格式)
  - **完成信号**: 最终消息: `{"status": "completed"}`
  - **错误响应**: `{"error": "错误信息"}`

## 🔗 嵌入模型

嵌入模型提供了将文本、图像等多种数据类型转换为向量表示的能力，支持多种后端服务。

### 功能特点

-   **多后端支持**: 支持Jina和OpenAI等多种嵌入服务。
-   **统一文本接口**: 所有模型均提供统一的 `get_embeddings` 方法，接受字符串或字符串列表作为输入，方便处理纯文本数据。
-   **多模态能力**: 像 `JinaMultimodalEmbedding` 这样的多模态模型，额外提供了 `get_multimodal_embeddings` 方法，可以处理包含文本和图像URL的复杂输入。
-   **配置灵活**: 支持通过参数或环境变量进行配置。
-   **连接测试**: 内置 `check_connectivity()` 方法，用于验证与API服务的连接状态。

### 使用示例

#### 获取文本嵌入 (所有模型通用)

所有嵌入模型都使用 `get_embeddings` 方法来获取文本的嵌入向量。此方法接受单个字符串或字符串列表。

```python
from nexent.core.models.embedding_model import JinaMultimodalEmbedding, OpenAICompatibleEmbedding

# 初始化Jina模型 (同样适用于OpenAICompatibleEmbedding)
embedding = JinaMultimodalEmbedding(api_key="your_jina_api_key")

# 获取单个文本的嵌入
text_input = "Hello, Nexent!"
embeddings = embedding.get_embeddings(text_input)
print(f"单文本嵌入向量数量: {len(embeddings)}")

# 获取多个文本的嵌入
text_list_input = ["这是第一段文本。", "这是第二段文本。"]
embeddings_list = embedding.get_embeddings(text_list_input)
print(f"多文本嵌入向量数量: {len(embeddings_list)}")
```

#### 获取多模态嵌入 (JinaMultimodalEmbedding)

对于支持多模态输入的模型（如 `JinaMultimodalEmbedding`），可以使用 `get_multimodal_embeddings` 方法来处理包含文本和图像的混合输入。

```python
from nexent.core.models.embedding_model import JinaMultimodalEmbedding

# 初始化Jina模型
embedding = JinaMultimodalEmbedding(api_key="your_jina_api_key")

# 定义包含文本和图像的多模态输入
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
model = OpenAIModel(observer=observer, temperature=0.2, top_p=0.95)

# 发送消息
messages = [{"role": "user", "content": "Hello"}]
response = model(messages=messages)
```

## 👁️ 视觉语言模型

视觉语言模型结合了图像理解和文本生成能力，支持图像描述和视觉问答。

### 功能特点

- **图像处理**: 支持本地图像文件和URL
- **流式输出**: 支持实时流式文本生成
- **提示词定制**: 可自定义系统提示词
- **多模态理解**: 结合视觉和语言理解能力

### 使用示例

```python
from nexent.core.models.openai_vlm import OpenAIVLModel
from nexent.core.utils.observer import MessageObserver

# 初始化模型
observer = MessageObserver()
model = OpenAIVLModel(observer=observer)

# 分析图像
image_path = "path/to/image.jpg"
result = model.analyze_image(image_path, system_prompt="请描述这张图片")
```

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

所有模型都实现了`check_connectivity()`方法，用于测试与远程服务的连接状态：

```python
# 测试连接
if model.check_connectivity():
    print("服务连接正常")
else:
    print("服务连接失败")
``` 