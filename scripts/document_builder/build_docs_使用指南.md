# Nexent 产品文档生成脚本使用指南

## 1. 脚本用途

`build_docs.py` 用于将 Nexent VitePress 文档聚合为一份完整的 Markdown 或 Word 文档。

脚本会自动完成以下工作：

- 从 `doc/docs/.vitepress/config.mts` 读取中英文文档顺序；
- 合并 `doc/docs/zh` 或 `doc/docs/en` 下的文档内容；
- 复制并重写文档中的图片引用；
- 按产品技术版规则组织章节；
- 自动生成封面、目录、章节编号、页眉和页脚；
- 使用 `reference.docx` 生成统一排版的 Word 文档；
- 将生成结果保存到脚本所在目录，或保存到指定目录。

## 2. 相关文件

| 文件 | 用途 |
|---|---|
| `build_docs.py` | 主生成脚本 |
| `document_profiles.yaml` | 产品技术版的标题、简介、章节划分和内容清理规则 |
| `reference.docx` | Pandoc 使用的 Word 样式模板 |
| `build_reference_docx.py` | 重新生成 `reference.docx` 的模板构建脚本 |
| `doc/docs/.vitepress/config.mts` | 中英文源文档的导航顺序 |
| `doc/docs/zh` | 中文源文档 |
| `doc/docs/en` | 英文源文档 |

这些文件的相对位置不可随意改变。生成脚本通过自身所在位置确定 Nexent 仓库根目录和源文档目录。

## 3. 环境要求

### 3.1 必需软件

- Python 3；
- Pandoc，并确保 `pandoc` 命令已经加入 `PATH`；
- `python-docx` Python 包；
- Windows 中安装宋体和 Times New Roman 字体。

可使用以下命令检查环境：

```powershell
python --version
pandoc --version
python -c "import docx; print(docx.__version__)"
```

如果只生成 Markdown，可以不安装 Pandoc 和 `python-docx`。

### 3.2 推荐运行位置

建议先进入 Nexent 仓库根目录：

```powershell
cd D:\projects\nexent
```

## 4. 快速开始

直接执行以下命令：

```powershell
python scripts\document_builder\build_docs.py
```

默认行为如下：

| 项目 | 默认值 |
|---|---|
| 语言 | 中文 `zh` |
| 格式 | Word `docx` |
| 文档类型 | 产品技术版 `product` |
| 输出目录 | `scripts\document_builder`，即脚本所在目录 |
| 默认文件名 | `nexent-product-technical-guide.docx` |

## 5. 常用命令

### 5.1 生成中文产品技术版 Word 文档

```powershell
python scripts\document_builder\build_docs.py
```

也可以完整写出参数：

```powershell
python scripts\document_builder\build_docs.py --locale zh --format docx
```

### 5.2 同时生成 Markdown 和 Word

```powershell
python scripts\document_builder\build_docs.py --format both
```

默认生成：

- `scripts\document_builder\nexent-product-technical-guide.md`
- `scripts\document_builder\nexent-product-technical-guide.docx`

### 5.3 只生成 Markdown

```powershell
python scripts\document_builder\build_docs.py --format md
```

该方式适合检查合并结果、章节顺序和内容清理效果。

### 5.4 生成英文文档

```powershell
python scripts\document_builder\build_docs.py --locale en
```

### 5.5 同时生成中英文文档

```powershell
python scripts\document_builder\build_docs.py --locale both
```

同时生成两种语言时，脚本会在文件名末尾自动添加语言标识，例如：

- `nexent-product-technical-guide-zh.docx`
- `nexent-product-technical-guide-en.docx`

### 5.6 自定义文件名

```powershell
python scripts\document_builder\build_docs.py `
  --docx-name "nexent-product-guide-v2.5.1.docx"
```

同时生成 Markdown 时，可以分别指定两个文件名：

```powershell
python scripts\document_builder\build_docs.py `
  --format both `
  --md-name "nexent-product-guide.md" `
  --docx-name "nexent-product-guide.docx"
```

### 5.7 自定义输出目录

```powershell
python scripts\document_builder\build_docs.py `
  --output-dir "C:\temp\nexent-docs"
```

如果未指定 `--output-dir`，生成结果始终保存到 `build_docs.py` 所在的 `scripts\document_builder` 目录，与当前终端所在目录无关。

## 6. 命令行参数

| 参数 | 可选值或格式 | 默认值 | 说明 |
|---|---|---|---|
| `--locale` | `zh`、`en`、`both` | `zh` | 选择中文、英文或双语生成 |
| `--format` | `docx`、`md`、`both` | `docx` | 选择输出格式 |
| `--md-name` | 文件名 | `nexent-product-technical-guide.md` | 自定义 Markdown 文件名 |
| `--docx-name` | 文件名 | `nexent-product-technical-guide.docx` | 自定义 Word 文件名 |
| `--output-dir` | 目录路径 | 脚本所在目录 | 自定义生成位置 |
| `-h`、`--help` | 无 | 无 | 显示参数帮助 |

查看脚本自带帮助：

```powershell
python scripts\document_builder\build_docs.py --help
```

## 7. 文档生成规则

### 7.1 文档顺序

脚本以 `doc/docs/.vitepress/config.mts` 中的侧边栏配置作为文档顺序来源。新增文档后，应先将页面加入 VitePress 侧边栏，否则该页面可能不会出现在合并文档中。

### 7.2 产品技术版

产品技术版由 `document_profiles.yaml` 控制，主要包括：

- 文档标题、副标题和作者；
- 产品简介、用途、适用读者和范围；
- 需要排除的社区或贡献类页面；
- 需要删除的宣传性标题和文案；
- 产品概述、部署、使用、集成、运维、安全和开发者参考等章节顺序。

`document_profiles.yaml` 当前采用 JSON 兼容语法。编辑后应特别检查逗号、双引号和数组括号是否完整。

### 7.3 字体和版式

Word 文档的基础样式由 `reference.docx` 提供，生成后的二次处理会统一应用：

- 中文：宋体；
- 英文和数字：Times New Roman；
- A4 页面；
- 分级标题、目录、表格、图片、页眉和页脚样式；
- 表格跨页重复表头；
- 图片居中并限制在页面版心以内。

如需修改整体字号、颜色、边距或目录样式，应编辑 `build_reference_docx.py` 和 `build_docs.py` 中的样式设置，而不是直接修改最终生成的 Word 文件。

## 8. 修改模板后的操作

修改 `build_reference_docx.py` 后，先重新生成模板：

```powershell
python scripts\document_builder\build_reference_docx.py
```

确认输出了 `scripts\document_builder\reference.docx`，然后重新生成产品文档：

```powershell
python scripts\document_builder\build_docs.py
```

建议不要在 Microsoft Word 中手工长期维护 `reference.docx`。如果模板可以由构建脚本重现，后续字体和排版调整更容易审查与复用。

## 9. 图片与资源目录

生成过程中，脚本会在输出目录创建：

```text
nexent-documentation-assets\
├── zh\
└── en\
```

该目录保存合并过程中复制的图片：

- Word 文件会嵌入图片，分享单个 `.docx` 即可；
- Markdown 文件仍通过相对路径引用该目录，因此发布 Markdown 时必须同时保留对应资源目录；
- 同名但内容不同的图片会使用哈希值避免覆盖。

## 10. 推荐发布流程

1. 更新 `doc/docs/zh` 和 `doc/docs/en` 中的源文档。
2. 确认新增页面已加入 `.vitepress/config.mts`。
3. 如有需要，更新 `document_profiles.yaml` 的章节和过滤规则。
4. 先使用 `--format md` 检查合并内容。
5. 使用正式文件名生成 Word 文档。
6. 打开 Word 文档，检查封面、目录、分页、表格和图片。
7. 确认产品版本、文档版本和发布日期正确。
8. 将最终 Word 文件复制到发布目录。

推荐命令：

```powershell
python scripts\document_builder\build_docs.py `
  --locale zh `
  --format both `
  --docx-name "nexent-product-technical-guide-v2.5.1.docx"
```

## 11. 故障排查

### 11.1 提示找不到 Pandoc

错误信息通常包含：

```text
pandoc not found on PATH
```

处理方法：

1. 安装 Pandoc；
2. 将 Pandoc 安装目录加入系统 `PATH`；
3. 重新打开终端；
4. 执行 `pandoc --version` 确认命令可用。

临时只需要合并内容时，可执行：

```powershell
python scripts\document_builder\build_docs.py --format md
```

### 11.2 提示无法替换 Word 文件

错误信息通常包含：

```text
Cannot replace ...; close the file in Word and retry.
```

这是因为目标文件正在被 Microsoft Word 或预览程序占用。关闭该文件后重新运行，或者通过 `--docx-name` 使用一个新文件名。

### 11.3 提示找不到 VitePress 配置

确认以下文件存在：

```text
doc\docs\.vitepress\config.mts
```

同时确认 `build_docs.py` 仍位于 Nexent 仓库的 `scripts\document_builder` 目录。

### 11.4 配置文件无法读取

如果错误中包含 `Cannot load product/zh` 或 JSON 解析信息，请检查 `document_profiles.yaml`：

- 属性名和字符串是否使用双引号；
- 数组或对象之间是否遗漏逗号；
- 方括号、花括号是否配对；
- 是否保留 `product.zh` 和 `product.en` 节点。

### 11.5 图片缺失

检查源 Markdown 的图片路径是否相对于当前源文件正确，并确认目标图片位于 `doc/docs` 范围内。生成日志中的 `copied N image(s)` 可用于判断脚本是否发现了图片。

### 11.6 字体显示不一致

确认打开文档的计算机已安装宋体和 Times New Roman。若更改过模板，请重新运行 `build_reference_docx.py`，再重新生成 Word 文档。

## 12. 运行结果与退出码

脚本会在终端输出：

- 侧边栏中发现的文档数量；
- 产品技术版实际包含的页面数量；
- 已复制的图片数量和资源目录；
- 生成文件的位置和大小；
- 未匹配章节或转换失败等警告信息。

退出码含义：

| 退出码 | 含义 |
|---|---|
| `0` | 所有请求的文档均生成成功 |
| `1` | 至少一种语言或一种输出格式生成失败 |

在 CI 或自动化脚本中，应检查退出码，不要只根据目标文件是否已经存在判断本次生成是否成功。
