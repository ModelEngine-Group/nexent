# Multimodal Module

This module provides a native multimodal data processing bus designed for agents. With the `@load_object` and `@save_object` decorators, it supports real-time transmission and processing of text, images, audio, video, and other data formats, enabling seamless cross-modal data flow.

## 📋 Table of Contents

- [LoadSaveObjectManager Initialization](#loadsaveobjectmanager-initialization)
- [@load_object Decorator](#load_object-decorator)
- [@save_object Decorator](#save_object-decorator)
- [Combined Usage Example](#combined-usage-example)

## LoadSaveObjectManager Initialization

Before using the decorators, you need to initialize a `LoadSaveObjectManager` instance and pass in a storage client (for example, a MinIO client):

```python
from nexent.multi_modal.load_save_object import LoadSaveObjectManager
from database.client import minio_client


# Create manager instance
Multimodal = LoadSaveObjectManager(storage_client=minio_client)
```

You can also implement your own storage client based on the `StorageClient` base class in `sdk.nexent.storage.storage_client_base`.  
The storage client must implement:

- `get_file_stream(object_name, bucket)`: get a file stream from storage (for download)
- `upload_fileobj(file_obj, object_name, bucket)`: upload a file-like object to storage (for save)

## @load_object Decorator

The `@load_object` decorator downloads files from URLs (S3 / HTTP / HTTPS) **before** the wrapped function is executed, and passes the file content (or transformed data) into the wrapped function.

### Features

- **Automatic download**: Automatically detect and download files pointed to by S3, HTTP, or HTTPS URLs.
- **Data transformation**: Use custom transformer functions to convert downloaded bytes into types required by the wrapped function (for example, `PIL.Image`, text, etc.).
- **Batch processing**: Support a single URL or a list of URLs.

### Parameters

- `input_names` (`List[str]`): names of function parameters to transform.
- `input_data_transformer` (`Optional[List[Callable[[bytes], Any]]]`): optional list of transformers; each transformer converts raw `bytes` into the target type for the corresponding parameter.

### Supported URL Formats

The decorator supports:

- **S3 URLs**
  - `s3://bucket-name/object/file.jpg`
  - `/bucket-name/object/file.jpg` (short form)
- **HTTP / HTTPS URLs**
  - `http://example.com/file.jpg`
  - `https://example.com/file.jpg`

URL type detection:

- Starts with `http://` → HTTP URL  
- Starts with `https://` → HTTPS URL  
- Starts with `s3://` or looks like `/bucket/object` → S3 URL

### Examples

#### Basic: download as bytes

```python
@Multimodal.load_object(input_names=["image_url"])
def process_image(image_url: bytes):
    """image_url will be replaced with downloaded bytes."""
    print(f"File size: {len(image_url)} bytes")
    return image_url


# Call process_image
result = process_image(image_url="http://example.com/pic.PNG")
```

#### Advanced: convert bytes to PIL Image

If the function parameter is not `bytes` (for example, it expects `PIL.Image.Image`), define a converter (such as `bytes_to_pil`) and pass it to the decorator.

```python
import io
from PIL import Image


def bytes_to_pil(binary_data: bytes) -> Image.Image:
    image_stream = io.BytesIO(binary_data)
    img = Image.open(image_stream)
    return img


@Multimodal.load_object(
    input_names=["image_url"],
    input_data_transformer=[bytes_to_pil],
)
def process_image(image_url: Image.Image) -> Image.Image:
    """image_url will be converted into a PIL Image object."""
    resized = image_url.resize((800, 600))
    return resized


result = process_image(image_url="http://example.com/pic.PNG")
```

#### Multiple inputs

```python
from PIL import Image


@Multimodal.load_object(
    input_names=["image_url1", "image_url2"],
    input_data_transformer=[bytes_to_pil, bytes_to_pil],
)
def process_two_images(image_url1: Image.Image, image_url2: Image.Image) -> Image.Image:
    """Both image URLs will be downloaded and converted into PIL Images."""
    combined = Image.new("RGB", (1600, 600))
    combined.paste(image_url1, (0, 0))
    combined.paste(image_url2, (800, 0))
    return combined


result = process_two_images(
    image_url1="http://example.com/pic1.PNG",
    image_url2="http://example.com/pic2.PNG",
)
```

#### List of URLs

```python
from typing import List
from PIL import Image


@Multimodal.load_object(
    input_names=["image_urls"],
    input_data_transformer=[bytes_to_pil],
)
def process_image_list(image_urls: List[Image.Image]) -> List[Image.Image]:
    """Support a list of URLs, each will be downloaded and converted."""
    results: List[Image.Image] = []
    for img in image_urls:
        results.append(img.resize((200, 200)))
    return results


result = process_image_list(
    image_urls=[
        "http://example.com/pic1.PNG",
        "http://example.com/pic2.PNG",
    ]
)
```

## @save_object Decorator

The `@save_object` decorator uploads return values to storage (MinIO) **after** the wrapped function finishes, and returns S3 URLs.

### Features

- **Automatic upload**: Automatically upload function return values to MinIO.
- **Data transformation**: Use transformers to convert return values into `bytes` (for example, `PIL.Image` → `bytes`).
- **Batch processing**: Support a single return value or multiple values (tuple).
- **URL return**: Return S3 URLs of the form `s3://bucket/object_name`.

### Parameters

- `output_names` (`List[str]`): logical names for each return value.
- `output_transformers` (`Optional[List[Callable[[Any], bytes]]]`): transformers that convert each return value into `bytes`.
- `bucket` (`str`): target bucket name, default `"nexent"`.

### Examples

#### Basic: save raw bytes

```python
@Multimodal.save_object(
    output_names=["content"],
)
def generate_file() -> bytes:
    """Returned bytes will be uploaded to MinIO automatically."""
    content = b"Hello, World!"
    return content
```

#### Advanced: convert PIL Image to bytes before upload

If the function does not return `bytes` (for example, it returns `PIL.Image.Image`), define a converter such as `pil_to_bytes` and pass it to the decorator.

```python
import io
from typing import Optional
from PIL import Image, ImageFilter


def pil_to_bytes(img: Image.Image, format: Optional[str] = None) -> bytes:
    """
    Convert a PIL Image to binary data (bytes).
    """
    if img is None:
        raise ValueError("Input image cannot be None")

    buffer = io.BytesIO()

    # Decide which format to use
    if format is None:
        # Use original format if available, otherwise default to PNG
        format = img.format if img.format else "PNG"

    # For JPEG, ensure RGB (no alpha channel)
    if format.upper() == "JPEG" and img.mode in ("RGBA", "LA", "P"):
        rgb_img = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode == "P":
            img = img.convert("RGBA")
        rgb_img.paste(
            img,
            mask=img.split()[-1] if img.mode in ("RGBA", "LA") else None,
        )
        rgb_img.save(buffer, format=format)
    else:
        img.save(buffer, format=format)

    data = buffer.getvalue()
    buffer.close()
    return data


@Multimodal.save_object(
    output_names=["processed_image"],
    output_transformers=[pil_to_bytes],
)
def process_image(image: Image.Image) -> Image.Image:
    """Returned PIL Image will be converted to bytes and uploaded."""
    blurred = image.filter(ImageFilter.GaussianBlur(radius=5))
    return blurred
```

#### Multiple files

```python
from typing import Tuple


@Multimodal.save_object(
    output_names=["resized1", "resized2"],
    output_transformers=[pil_to_bytes, pil_to_bytes],
)
def process_two_images(
    img1: Image.Image,
    img2: Image.Image,
) -> Tuple[Image.Image, Image.Image]:
    """Both returned images will be uploaded and return corresponding S3 URLs."""
    resized1 = img1.resize((800, 600))
    resized2 = img2.resize((800, 600))
    return resized1, resized2
```

### Return Format

- **Single return value**: a single S3 URL string, `s3://bucket/object_name`.
- **Multiple return values (tuple)**: a tuple where each element is the corresponding S3 URL.

### Notes

- If you do **not** provide a transformer, the function return value must be `bytes`.
- If you provide a transformer, the transformer **must** return `bytes`.
- The number of return values must match the length of `output_names`.

## Combined Usage Example

In practice, `@load_object` and `@save_object` are often used together to build a full **download → process → upload** pipeline:

```python
from typing import Union, List
from PIL import Image, ImageFilter

from database.client import minio_client
from nexent.multi_modal.load_save_object import LoadSaveObjectManager


Multimodal = LoadSaveObjectManager(storage_client=minio_client)


@Multimodal.load_object(
    input_names=["image_url"],
    input_data_transformer=[bytes_to_pil],
)
@Multimodal.save_object(
    output_names=["blurred_image"],
    output_transformers=[pil_to_bytes],
)
def blur_image_tool(
    image_url: Union[str, List[str]],
    blur_radius: int = 5,
) -> Image.Image:
    """
    Apply a Gaussian blur filter to an image.

    Args:
        image_url: S3 URL or HTTP/HTTPS URL of the image.
        blur_radius: Blur radius (default 5, valid range 1–50).

    Returns:
        Processed PIL Image object (it will be uploaded and returned as an S3 URL).
    """
    # At this point, image_url has already been converted to a PIL Image
    if image_url is None:
        raise ValueError("Failed to load image")

    # Clamp blur radius
    blur_radius = max(1, min(50, blur_radius))

    # Apply blur
    blurred_image = image_url.filter(ImageFilter.GaussianBlur(radius=blur_radius))
    return blurred_image


# Example usage
result_url = blur_image_tool(
    image_url="s3://nexent/images/input.png",
    blur_radius=10,
)
# result_url is something like "s3://nexent/attachments/xxx.png"
```