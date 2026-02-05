# 知识库

在知识库模块，您可以创建和管理知识库，上传各种格式的文件，并生成内容总结。知识库是智能体的重要信息来源，让智能体能够访问您的私有数据和文档。

## 🔧 创建知识库

1. 点击"创建知识库"按钮
2. 为知识库设置一个易于识别的名称

## 📁 上传文件

### 上传文件

1. 在知识库列表中选择要上传文件的知识库
2. 点击文件上传区域，选择要上传的文件（支持多选），或直接拖拽文件到上传区域
3. 系统会自动处理上传的文件，提取文本内容并进行向量化
4. 可在列表中查看文件的处理状态（解析中/入库中/已就绪）

![文件上传](./assets/knowledge-base/create-knowledge-base.png)

💡 光标移动至状态，以了解进度及报错原因

![文件上传](./assets/knowledge-base/tip.png)

### 支持的文件格式

Nexent支持多种文件格式，包括：

- **文本**: .txt, .md, .json文件
- **PDF**: .pdf文件
- **Word**: .docx文件
- **PowerPoint**: .pptx文件
- **EPUB** .epub文件
- **Excel**: .xlsx文件
- **数据文件**: .csv文件
- **Web content**: .html, .xml文件

## 📊 知识库总结

建议您为每个知识库配置准确且完整的总结描述，这有助于后续智能体在进行检索时，准确选择合适的知识库。

1. 点击“详细内容”按钮进入知识库详细内容查看界面
2. 选择合适的模型，点击“自动总结”按钮为知识库自动生成内容总结
3. 您可对生成的内容总结进行编辑修改，使其更准确
4. 最后记得点击“保存”将您的修改保存

![内容总结](./assets/knowledge-base/summary-knowledge-base.png)

## 🔍 知识库管理

### 查看知识库

1. **知识库列表**
   - 知识库页面左侧展示了所有已创建的知识库
   - 显示知识库名称、文件数量、创建时间等信息

2. **知识库详情**
   - 点击知识库名称，可查看知识库中全部文档信息
   - 点击“详细内容”，可查看知识库的内容总结

<div style="display: flex; gap: 8px;">
  <img src="./assets/knowledge-base/knowledge-base-file-list.png" style="width: 50%; height: 100%;" />
  <img src="./assets/knowledge-base/knowledge-base-summary.png" style="width: 50%; height: 100%;" />
</div>

### 编辑知识库

1. **删除知识库**
   - 点击知识库名称右侧“删除”按钮
   - 确认删除操作（此操作不可恢复）
![删除知识库](./assets/knowledge-base/delete-knowledge-base.png)

2. **删除或新增文件**
   - 点击知识库名称，在文件列表中点击“删除”按钮，可从知识库中删除文件
   - 点击知识库名称，在文件列表下方文件上传区域，可新增文件到知识库中

## 🚀 下一步

完成知识库配置后，建议您继续配置：

1. **[智能体开发](./agent-development)** - 创建和配置智能体
2. **[开始问答](./start-chat)** - 与智能体进行交互

如果您在使用过程中遇到任何问题，请参考我们的 **[常见问题](../quick-start/faq)** 或在[GitHub Discussions](https://github.com/ModelEngine-Group/nexent/discussions)中进行提问获取支持。