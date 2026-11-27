# Dify Integration

Nexent supports retrieving Dify knowledge bases (Datasets) through the `dify_search` tool: the agent searches the selected Dify knowledge bases for the query and returns the most relevant results with citation sources.

## Prerequisites

- A reachable Dify service (e.g., `https://api.dify.ai/v1` or a self-hosted address)
- An API Key created on the Dify platform (with Datasets access)
- Knowledge bases created on Dify that contain documents

## Configuration steps

1. Open the Agent Configuration page and select the target agent
2. Add **dify_search** (local tool) to the agent in tool management
3. Select **Configure** on the tool row and fill in the parameters:

| Parameter | Description |
| --------- | ----------- |
| **server_url** | Dify API base URL, e.g., `https://api.dify.ai/v1` |
| **api_key** | Dify API key (shown as a password field) |
| **dataset_ids** | Select from the synced list of Dify knowledge bases (multiple allowed) |
| **top_k** | Maximum number of search results per knowledge base, 3 by default (1–100) |
| **search_method** | Keyword search, semantic search (default), full-text search, or hybrid search |
| **rerank** | Whether to rerank search results, disabled by default; a rerank model must be selected when enabled |

4. Select **Save Configuration**. Saving is blocked until at least one knowledge base is selected

Opening the knowledge base selector syncs the Dify knowledge base list automatically; you can also select **Sync** in the list dialog to refresh manually. The list shows each knowledge base's document count, chunk count, and creation time; knowledge bases without documents cannot be selected.

## Runtime parameters

At runtime, the LLM only needs to provide:

- **query**: the search query

## Notes

- Authentication uses the Dify API key (Bearer); auth failures and rate limits are reported during sync and retrieval
- Retrieval runs against each selected knowledge base and attaches source citation links to the results
- The configuration applies to all calls of this agent; other knowledge retrieval tools can be configured on the same agent
