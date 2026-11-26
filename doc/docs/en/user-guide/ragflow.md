# RAGFlow Integration

Nexent supports retrieving RAGFlow knowledge bases (Datasets) through the `ragflow_search` tool: the agent searches the selected RAGFlow knowledge bases for the query and returns the most relevant results.

## Prerequisites

- A reachable RAGFlow service (e.g., `http://<host>:9380`)
- An API Key created on the RAGFlow platform
- Knowledge bases created on RAGFlow that contain documents

## Configuration steps

1. Open the Agent Configuration page and select the target agent
2. Add **ragflow_search** (local tool) to the agent in tool management
3. Select **Configure** on the tool row and fill in the parameters:

| Parameter | Description |
| --------- | ----------- |
| **server_url** | RAGFlow API base URL, e.g., `http://<host>:9380` |
| **api_key** | RAGFlow API key (shown as a password field) |
| **dataset_ids** | Select from the synced list of RAGFlow knowledge bases (multiple allowed) |
| **top_k** | Maximum number of results returned to the LLM, 3 by default (1–100) |
| **similarity_threshold** | Minimum similarity threshold for results, 0.2 by default (0–1) |
| **vector_similarity_weight** | Vector similarity weight in hybrid search, 0.3 by default (0.0–1.0) |
| **keyword** | Whether to enable keyword search in hybrid search, disabled by default |
| **highlight** | Whether to highlight search results, enabled by default |

4. Select **Save Configuration**. Saving is blocked until at least one knowledge base is selected

Opening the knowledge base selector syncs the RAGFlow knowledge base list automatically; you can also select **Sync** in the list dialog to refresh manually. The list shows each knowledge base's description, document count, and chunk count; knowledge bases without documents cannot be selected.

## Runtime parameters

At runtime, the LLM can provide:

- **query**: the search query
- **doc_id** (optional): restrict the search to specific documents; a single document ID or a JSON array
- **dataset_ids** (optional): temporarily override the knowledge base scope for this search

## Notes

- Authentication uses the RAGFlow API key (Bearer); auth failures are reported during sync and retrieval
- A single retrieval performs one combined search across all selected knowledge bases, returned by similarity in descending order
- When nothing matches, the tool suggests relaxing or shortening the query
