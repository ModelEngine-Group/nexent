# iData Integration

Nexent supports retrieving iData knowledge bases through the `idata_search` tool: the agent searches knowledge bases within a selected knowledge space for the query and returns the most relevant results, which is especially useful for accessing knowledge that is not publicly available.

## Prerequisites

- A reachable iData service address
- An iData API key and user ID
- Knowledge bases created under the target knowledge space, and an available Rerank model ID

## Configuration steps

1. Open the Agent Configuration page and select the target agent
2. Add **idata_search** (local tool) to the agent in tool management
3. Select **Configure** on the tool row and fill in the parameters:

| Parameter | Description |
| --------- | ----------- |
| **server_url** | iData API base URL |
| **api_key** | iData API key (shown as a password field) |
| **user_id** | iData user ID |
| **knowledge_space_id** | iData knowledge space ID: once the first three fields are filled, the space list is fetched automatically; choose from a searchable dropdown |
| **dataset_ids** | Select knowledge bases synced from the current space (multiple allowed) |
| **rerank_model_id** | Rerank model ID (required) |
| **top_k** | Maximum number of results, 10 by default (1–100) |
| **similarity_threshold** | Rerank similarity threshold, -10.0 by default (≤1.0) |
| **keyword_similarity_weight / vector_similarity_weight** | Keyword and vector similarity weights, 0.10 / 0.3 by default (0–1) |

4. Select **Save Configuration**. Saving is blocked until at least one knowledge base is selected

iData uses a two-level "knowledge space → knowledge base" selection: choose the knowledge space in the configuration parameters first — switching spaces clears selected knowledge bases and refetches — then open the **dataset_ids** selector to pick knowledge bases from that space. Opening the selector syncs the list automatically.

## Runtime parameters

At runtime, the LLM only needs to provide:

- **question**: the search query

## Notes

- server_url, api_key, user_id, knowledge_space_id, and rerank_model_id are all required
- iData supports self-signed certificate environments; retrieval results include document download links as citation sources
- Other knowledge retrieval tools can be configured on the same agent
