# Data Processing Core

## 📋 Overview

`DataProcessCore` is a unified file processing core class that supports automatic detection and processing of multiple file formats, providing flexible chunking strategies and multiple input source support.

## ⭐ Key Features

### 1. Core Processing Method: `file_process()`

**Function Signature:**
```python
def file_process(self, 
                file_path_or_url: Optional[str] = None, 
                file_data: Optional[bytes] = None, 
                chunking_strategy: str = "basic", 
                destination: str = "local", 
                filename: Optional[str] = None, 
                **params) -> List[Dict]
```

**Parameters:**

| Parameter | Type | Required | Description | Options |
|-----------|------|----------|-------------|---------|
| `file_path_or_url` | `str` | No* | Local file path or remote URL | Any valid file path or URL |
| `file_data` | `bytes` | No* | File byte data (for memory processing) | Any valid byte data |
| `chunking_strategy` | `str` | No | Chunking strategy | `"basic"`, `"by_title"`, `"none"` |
| `destination` | `str` | No | Destination type, indicating file source | `"local"`, `"minio"`, `"url"` |
| `filename` | `str` | No** | Filename | Any valid filename |
| `**params` | `dict` | No | Additional processing parameters | See parameter details below |

*Note: Either `file_path_or_url` or `file_data` must be provided
**Note: When using `file_data`, `filename` is required

**Chunking Strategy (`chunking_strategy`) Details:**

| Strategy | Description | Use Case | Output Characteristics |
|----------|-------------|----------|----------------------|
| `"basic"` | Basic chunking strategy | Most document processing scenarios | Automatic chunking based on content length |
| `"by_title"` | Title-based chunking | Structured documents with clear headings | Chunks divided by document structure |
| `"none"` | No chunking | Small files or when full content is needed | Returns complete content without chunking |

## 📁 Supported File Formats

- **Text files**: .txt, .md, .csv, .json
- **Documents**: .pdf, .docx, .pptx, .epub
- **Images**: .jpg, .png, .gif (with OCR)
- **Web content**: HTML, URLs, XML
- **Archives**: .zip, .tar

## 💡 Usage Examples

```python
from nexent.data_process import DataProcessCore

# Initialize processor
processor = DataProcessCore()

# Process local file
results = processor.file_process(
    file_path_or_url="/path/to/document.pdf",
    chunking_strategy="by_title"
)

# Process from URL
results = processor.file_process(
    file_path_or_url="https://example.com/document.pdf",
    destination="url"
)

# Process from memory
with open("document.pdf", "rb") as f:
    file_data = f.read()
    
results = processor.file_process(
    file_data=file_data,
    filename="document.pdf",
    chunking_strategy="basic"
)
```

For detailed configuration and advanced usage, see the complete SDK documentation.