# Local Tools

The Nexent platform provides a rich set of local tools that help agents complete various system-level tasks and local operations. These tools offer powerful execution capabilities through direct interaction with local systems or remote servers.

## 🛠️ Available Tools

Nexent preloads a set of reusable local tools grouped by capability: email, file, and search. The Terminal tool is offered separately to provide remote shell capabilities. The following sections list each tool alongside its core features so agents can quickly pick the right capability.

### 📧 Email Tools

- **get_email**: Fetches mailbox content through IMAP. Supports restricting by time range (days), filtering by sender, and limiting the number of returned messages. The tool automatically decodes multilingual subjects and bodies, and returns subject, timestamp, sender, and body summary to simplify downstream analysis.
- **send_email**: Sends HTML emails via SMTP. Supports multiple recipients, CC, and BCC, as well as custom sender display names. All connections use SSL/TLS. The result reports delivery status and subject for easy tracking.

### 📂 File Tools

- **create_directory**: Creates nested directories at the specified relative path, skipping existing levels and returning the result together with the final absolute path.
- **create_file**: Creates a file and writes content. Automatically creates parent directories if needed, supports custom encoding (default UTF-8), and allows empty files.
- **read_file**: Reads a text file and returns metadata such as size, line count, and encoding. Warns when the file is large (10 MB safety threshold).
- **list_directory**: Lists directory contents in a tree view. Supports maximum recursion depth, hidden file display, and file sizes. Output includes both visual text and structured JSON to clearly present project structure.
- **move_item**: Moves files or folders within the workspace. Automatically creates destination directories, avoids overwriting existing targets, and reports how many items were moved and their total size.
- **delete_file**: Deletes a single file with permission and existence checks. Provides clear error messages on failure.
- **delete_directory**: Recursively deletes a directory and its contents with existence, permission, and safety checks. Returns the deleted relative path.

> All file paths must be relative to the workspace (default `/mnt/nexent`). The system automatically validates paths to prevent escaping the workspace boundary.

### 🔍 Search Tools

- **knowledge_base_search**: Queries the local knowledge-base index with `hybrid`, `accurate`, or `semantic` modes. Can filter by index name and returns sources, scores, and citation indices, ideal for answering questions from internal documents or industry references.
- **exa_search**: Calls the EXA API for real-time web search. Supports configuring the number of results and optionally returns image links (with additional filtering performed server-side). Requires an EXA API key in the tool configuration, which you can obtain for free at [exa.ai](https://exa.ai/).
- **tavily_search**: Uses the Tavily API to retrieve webpages, particularly strong for news and current events. Returns both text results and related image URLs, with optional image filtering. Request a free API key from [tavily.com](https://www.tavily.com/).
- **linkup_search**: Uses the Linkup API to fetch text and images. In addition to regular webpages, it can return image-only results, making it useful when mixed media references are required. Register at [linkup.so](https://www.linkup.so/) to obtain a free API key.

### 🖼️ Multimodal Tools

- **analyze_text_file**: Based on user queries and the S3 URL, HTTP URL, and HTTPS URL of a text file, parse the file and use a large language model to understand it, answering user questions. An available large language model needs to be configured on the model management page.
- **analyze_image**: Based on user queries and the S3 URL, HTTP URL, and HTTPS URL of an image, use a visual language model to analyze and understand the image, answering user questions. An available visual language model needs to be configured on the model management page.

### 🖥️ Terminal Tool

The **Terminal Tool** is one of Nexent's core local capabilities that provides a persistent SSH session. Agents can execute remote commands, perform system inspections, read logs, or deploy services. Refer to the dedicated [Terminal Tool guide](./terminal-tool) for detailed setup, parameters, and security guidance.

## 🔧 Tool Configuration

All local tools need to be configured inside Agent Development:

1. Navigate to the **[Agent Development](../agent-development)** page
2. Select the agent you want to configure
3. In the "Select Agent Tools" tab, locate the desired local tool
4. Click the configuration button and fill in the required connection parameters
5. Test the connection to ensure the configuration is correct
6. Save the configuration and enable the tool

## ⚠️ Security Considerations

When using local tools, keep the following security practices in mind:

- **Permission Control**: Create dedicated users for each tool and follow least privilege
- **Network Security**: Use VPN or IP allowlists to restrict access
- **Authentication Security**: Favor key-based authentication and rotate keys regularly
- **Command Restrictions**: Configure command whitelists in production environments
- **Audit Logging**: Enable detailed logging for all operations

Need help? Please open a thread in [GitHub Discussions](https://github.com/ModelEngine-Group/nexent/discussions).
