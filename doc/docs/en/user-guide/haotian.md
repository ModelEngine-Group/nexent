# Haotian Integration

Nexent supports retrieving Haotian external knowledge bases through the `haotian_search` tool: the agent searches the selected knowledge sets/knowledge bases for the query and returns the most relevant results. Retrieval requests are proxied by the Nexent backend; the frontend never calls the external service directly.

## Prerequisites

- A reachable Haotian knowledge-set list URL and retrieval API URL
- A valid Authorization credential (e.g., `Bearer xxx`)
- Knowledge bases created under the target knowledge sets

## Configuration steps

1. Open the Agent Configuration page and select the target agent
2. Add **haotian_search** (local tool) to the agent in tool management
3. Select **Configure** on the tool row and fill in the parameters:

| Parameter | Description |
| --------- | ----------- |
| **list_url** | Haotian knowledge set/knowledge base list URL |
| **retrieve_url** | Haotian retrieval API URL |
| **authorization** | Authorization header (e.g., `Bearer xxx`, shown as a password field) |
| **dataset_ids** | Select from the synced list of knowledge bases (multiple allowed) |
| **top_k** | Maximum number of results, 3 by default (1–100) |
| **reranking_enable** | Whether to enable the retrieval API's built-in reranking, disabled by default; rerank strategy and model can be configured when enabled |
| **keyword_weight / vector_weight** | Keyword and vector similarity weights, 0.1 / 0.3 by default (0–1) |
| **score_threshold_enabled / score_threshold** | Whether to enable the result filter threshold, and its value (0–1) |

4. Select **Save Configuration**. Saving is blocked until at least one knowledge base is selected

Haotian uses a dedicated knowledge base selector with a two-level "knowledge set → knowledge base" structure: each knowledge set is rendered as a card with checkboxes for its knowledge bases; the top search box filters by knowledge set or knowledge base name.

## Runtime parameters

At runtime, the LLM only needs to provide:

- **query**: the search query

## Notes

- **Keyword search only** (keyword_search): the Haotian retrieval API does not support semantic or hybrid search; keep the default search method
- The list URL, retrieval URL, and Authorization are all required
- Retrieval uses Haotian's built-in reranking parameters, not Nexent's local rerank models
