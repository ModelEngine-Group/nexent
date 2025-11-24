# Knowledge Base

Create and manage knowledge bases, upload documents, and generate summaries. Knowledge bases are critical information sources that let agents securely use your private data.

## 🔧 Create a Knowledge Base

1. Click **Create Knowledge Base**
2. Enter a descriptive, unique name

## 📁 Upload Files

### Upload Files

1. Select a knowledge base from the list
2. Click the upload area to pick files (multi-select supported) or drag them in directly
3. Nexent automatically parses files, extracts text, and vectorizes the content
4. Track the processing status in the list (Parsing/Ingesting/Ready)

![File Upload](./assets/knowledge/create-knowledge-base.png)

### Supported File Formats

Nexent supports multiple file formats, including:
- **Text:** .txt, .md
- **PDF:** .pdf
- **Word:** .docx
- **PowerPoint:** .pptx
- **Excel:** .xlsx
- **Data files:** .csv

## 📊 Knowledge Base Summary

Give every knowledge base a clear summary so agents can pick the right source during retrieval.

1. Click **Details** to open the detailed view
2. Choose a model and click **Auto Summary** to generate a description
3. Edit the generated text to improve accuracy
4. Click **Save** to store your changes

![Content Summary](./assets/knowledge/summary-knowledge-base.png)

## 🔍 Knowledge Base Management

### View Knowledge Bases

1. **Knowledge Base List**
   - The left column lists every created knowledge base
   - Shows the name, file count, creation time, and more
2. **Knowledge Base Details**
   - Click a knowledge base to see all documents
   - Click **Details** to view or edit the summary

<div style="display: flex; gap: 8px;">
  <img src="./assets/knowledge/knowledge-base-file-list.png" style="width: 50%; height: 100%;" />
  <img src="./assets/knowledge/knowledge-base-summary.png" style="width: 50%; height: 100%;" />
</div>

### Edit Knowledge Bases

1. **Delete Knowledge Base**
   - Click **Delete** to the right of the knowledge base row
   - Confirm the deletion (irreversible)

![Delete Knowledge Base](./assets/knowledge/delete-knowledge-base.png)

2. **Delete/Add Files**
   - Inside the file list, click **Delete** to remove a document
   - Use the upload area under the list to add new files

## 🚀 Next Steps

After completing knowledge base configuration, we recommend you continue with:

1. **[Agent Development](./agent-development)** – Create and configure agents
2. **[Start Chat](./start-chat)** – Interact with your agent

Need help? Check the **[FAQ](../getting-started/faq)** or open a thread in [GitHub Discussions](https://github.com/ModelEngine-Group/nexent/discussions).