# 多模态模块

本模块提供专为智能体设计的原生多模态数据处理总线，通过 `@load_object`、 `@save_object` 装饰器，支持文本、图像、音频、视频等多种数据格式的实时传输和处理，实现跨模态的无缝数据流转。

## 📋 目录

- [LoadSaveObjectManager 初始化](#loadsaveobjectmanager-初始化)
- [@load_object装饰器](#@load_object装饰器)
- [@save_object装饰器](#@save_object装饰器)
- [组合使用示例](#组合使用示例)


## LoadSaveObjectManager 初始化

在使用装饰器之前，需要先初始化 `LoadSaveObjectManager` 实例，并传入存储客户端（如 MinIO 客户端）：

```python
from nexent.multi_modal.load_save_object import LoadSaveObjectManager
from database.client import minio_client


# 创建管理器实例
Multimodal = LoadSaveObjectManager(storage_client=minio_client)
```

此外还可以传入可选参数 `validate_url_access`：一个接收 URL 列表的回调函数，用于校验 URL 访问权限，校验不通过时应抛出 `PermissionError`。

存储客户端也可以通过`sdk.nexent.storage.storage_client_base`中的`StorageClient`基类，实现自己的存储客户端。存储客户端需要实现以下方法：
- `get_file_stream(object_name, bucket)`: 从存储中获取文件流（用于下载）
- `upload_fileobj(file_obj, object_name, bucket)`: 上传文件对象到存储（用于保存）


## @load_object装饰器

`@load_object` 装饰器用于在被装饰函数执行前自动从 URL（S3、HTTP、HTTPS）下载文件，并将文件内容（或转换后的数据）传递给被装饰函数。

### 功能特性 

- **自动下载**: 自动识别并下载 S3、HTTP、HTTPS URL 指向的文件
- **数据转换**: 支持通过自定义转换器将下载的字节数据转换为被装饰函数所需格式（如 PIL Image、文本等）
- **批量处理**: 支持处理单个 URL 或 URL 列表


### 参数说明

- `input_names` (List[str]): 需要处理的函数参数名称列表
- `input_data_transformer` (Optional[List[Callable[[bytes], Any]]]): 可选的数据转换器列表，用于将下载的字节数据转换为所需格式

### 支持的URL格式

装饰器支持以下 URL 格式：

- S3 URL
  - `s3://bucket-name/object/file.jpg`
  - `/bucket-name/object/file.jpg`（简化格式）
- HTTP/HTTPS URL
  - `http://example.com/file.jpg`
  - `https://example.com/file.jpg`


系统会自动检测 URL 类型：
- 以 `http://` 开头 → HTTP URL
- 以 `https://` 开头 → HTTPS URL
- 以 `s3://` 开头或符合 `/bucket/object` 格式 → S3 URL

### 使用示例

#### 基础用法：下载为字节数据

```python
@Multimodal.load_object(input_names=["image_url"])
def process_image(image_url: bytes):
    """file_url 参数会被自动替换为从 URL 下载的字节数据"""
    print(f"文件大小: {len(image_url)} bytes")
    return image_url

# 调用process_image方法
result = process_image(image_url=f"http://example/pic.PNG")
```

#### 进阶用法：使用转换器将字节数据转换为所需格式

若被装饰函数的入参不是字节数据，而是其他数据类型的数据（如PIL Image）。可以定义一个数据转换的函数（如bytes_to_pil）并将函数名作为入参传给装饰器。

```python
import io
import PIL
from PIL import Image

def bytes_to_pil(binary_data):
    image_stream = io.BytesIO(binary_data)
    img = Image.open(image_stream)
    return img

@Multimodal.load_object(
    input_names=["image_url"],
    input_data_transformer=[bytes_to_pil]
)
def process_image(image_url: Image.Image):
    """image_url 参数会被自动转换为 PIL Image 对象"""
    resized = image_url.resize((800, 600))
    return resized

# 调用process_image方法
result = process_image(image_url=f"http://example/pic.PNG")
```

#### 处理多个输入

```python
@Multimodal.load_object(
    input_names=["image_url1", "image_url2"],
    input_data_transformer=[bytes_to_pil, bytes_to_pil]
)
def process_two_images(image_url1: Image.Image, image_url2: Image.Image):
    """两个图片 URL 都会被下载并转换为 PIL Image"""
    combined = Image.new('RGB', (1600, 600))
    combined.paste(image_url1, (0, 0))
    combined.paste(image_url2, (800, 0))
    return combined

# 调用process_two_images方法
result = process_two_images(image_url1=f"http://example/pic1.PNG", image_url2=f"http://example/pic2.PNG")
```

#### 处理 URL 列表

```python
@Multimodal.load_object(
    input_names=["image_urls"],
    input_data_transformer=[bytes_to_pil]
)
def process_image_list(image_urls: List[Image.Image]):
    """支持传入 URL 列表，每个 URL 都会被下载并转换"""
    results = []
    for img in image_urls:
        results.append(img.resize((200, 200)))
    return results

# 调用process_image_list方法
result = process_image_list(image_urls=["http://example/pic1.PNG", "http://example/pic2.PNG"])
```


## @save_object装饰器

`@save_object` 装饰器用于在被装饰函数执行后自动将返回值上传到存储（MinIO），并返回 S3 URL。

### 功能特性

- **自动上传**: 自动将被装饰函数返回值上传到 MinIO 存储
- **数据转换**: 支持通过转换器将返回值转换为字节数据（如 PIL Image 转 bytes）
- **批量处理**: 支持处理单个返回值或多个返回值（tuple）
- **URL 返回**: 返回 S3 URL 格式（`s3://bucket/object_name`）

### 参数说明

- `output_names` (List[str]): 被装饰器函数的输出参数的名称列表
- `output_transformers` (Optional[List[Callable[[Any], bytes]]]): 可选的数据转换器列表，用于将返回值转换为字节数据
- `bucket` (str): 存储桶名称，默认为 `"nexent"`

### 使用示例

#### 基础用法：直接保存字节数据

```python
@Multimodal.save_object(
    output_names=["content"]
)
def generate_file() -> bytes:
    """返回的字节数据会被自动上传到 MinIO"""
    content = b"Hello, World!"
    return content
```

#### 进阶用法: 使用转换器将函数返回值转换为字节数据

若被装饰函数的出参不是字节数据，而是其他数据类型的数据（如PIL Image）。可以定义一个数据转换的函数（如pil_to_bytes）并将函数名作为入参传给装饰器。


```python
# 定义将PIL对象转换为Bytes的转换器函数
def pil_to_bytes(img, format=None):
    """
    Convert PIL Image to binary data (bytes)

    Args:
        img: PIL.Image object
        format: Output format ('JPEG', 'PNG', 'BMP', 'WEBP', etc.).
               If None, uses the image's original format or defaults to PNG.

    Returns:
        bytes: Binary data of the image
    """
    if img is None:
        raise ValueError("Input image cannot be None")

    # Create memory buffer
    buffer = io.BytesIO()

    # Determine format to use
    if format is None:
        # Use image's original format if available, otherwise default to PNG
        format = img.format if img.format else 'PNG'

    # Save image to buffer with specified format
    # For JPEG, ensure RGB mode (no transparency)
    if format.upper() == 'JPEG' and img.mode in ('RGBA', 'LA', 'P'):
        # Convert to RGB for JPEG compatibility
        rgb_img = Image.new('RGB', img.size, (255, 255, 255))
        if img.mode == 'P':
            img = img.convert('RGBA')
        rgb_img.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
        rgb_img.save(buffer, format=format)
    else:
        img.save(buffer, format=format)

    # Get binary data
    binary_data = buffer.getvalue()
    buffer.close()

    return binary_data


@Multimodal.save_object(
    output_names=["processed_image"],
    output_transformers=[pil_to_bytes]
)
def process_image(image: Image.Image) -> Image.Image:
    """返回的 PIL Image 会被转换为字节并上传"""
    blurred = image.filter(ImageFilter.GaussianBlur(radius=5))
    return blurred
```

#### 返回多个文件

```python
@Multimodal.save_object(
    output_names=["resized1", "resized2"],
    output_transformers=[pil_to_bytes, pil_to_bytes]
)
def process_two_images(img1: Image.Image, img2: Image.Image) -> Tuple[Image.Image, Image.Image]:
    """返回两个图片，都会被上传并返回对应的 S3 URL"""
    resized1 = img1.resize((800, 600))
    resized2 = img2.resize((800, 600))
    return resized1, resized2
```

### 返回值格式

- 单个返回值：返回单个 S3 URL 字符串，格式为 `s3://bucket/object_name`
- 多个返回值（tuple）：返回 tuple，每个元素是对应的 S3 URL

### 注意事项

- 如果没有提供转换器，被装饰函数的返回值必须是 `bytes` 类型
- 如果提供了转换器，转换器必须返回 `bytes` 类型
- 返回值的数量必须与 `output_names` 的长度一致


## 组合使用示例

在实际应用中，通常会将 `@load_object` 和 `@save_object` 组合使用，实现完整的"下载-处理-上传"流程：

```python
from PIL import Image, ImageFilter
from typing import Union, List
from database.client import minio_client
from nexent.multi_modal.load_save_object import LoadSaveObjectManager

Multimodal = LoadSaveObjectManager(storage_client=minio_client)

@Multimodal.load_object(
    input_names=["image_url"],
    input_data_transformer=[bytes_to_pil]
)
@Multimodal.save_object(
    output_names=["blurred_image"],
    output_transformers=[pil_to_bytes]
)
def blur_image_tool(
    image_url: Union[str, List[str]],
    blur_radius: int = 5
) -> Image.Image:
    """
    对图片应用高斯模糊滤镜
    
    Args:
        image_url: 图片的 S3 URL 或 HTTP/HTTPS URL
        blur_radius: 模糊半径（默认 5，范围 1-50）
    
    Returns:
        处理后的 PIL Image 对象（会被自动上传并返回 S3 URL）
    """
    # 此时 image_url 已经是 PIL Image 对象
    if image_url is None:
        raise ValueError("Failed to load image")
    
    # 验证并限制模糊半径
    blur_radius = max(1, min(50, blur_radius))
    
    # 应用模糊滤镜
    blurred_image = image_url.filter(ImageFilter.GaussianBlur(radius=blur_radius))
    
    # 返回 PIL Image（会被 @save_object 自动上传）
    return blurred_image

# 使用示例
result_url = blur_image_tool(
    image_url="s3://nexent/images/input.png",
    blur_radius=10
)
# result_url 是 "s3://nexent/attachments/xxx.png"
```

> VLM 的图片/视频/音频理解统一经 Gateway 适配器接入（core/gateway/），支持 OpenAI VLM、ModelEngine（vlm4 槽位音频）、DashScope VLM 音频适配等；多模态分析工具（AnalyzeImageTool/AnalyzeAudioTool/AnalyzeVideoTool）支持用户选择模型。