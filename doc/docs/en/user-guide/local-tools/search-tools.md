---
title: Search Tools
---

# Search Tools

Search tools cover internet search plus local, AIDP, DataMate, Dify, RAGFlow, Haotian, and iData knowledge bases, useful for real-time info, industry materials, private docs, and multimodal enterprise KB retrieval.

## 🧭 Tool List

- Local/private knowledge bases:
  - `knowledge_base_search`: Local KB search with multiple modes (system-managed, injected at runtime)
  - `aidp_search`: Search AIDP enterprise KBs via multi-channel FusionSearch (vector / full-text / graph) (system-managed, injected at runtime)
  - `datamate_search`: Search DataMate KB
  - `dify_search`: Search Dify KB
  - `ragflow_search`: Search RAGFlow KB
  - `idata_search`: Search iData KB
  - `haotian_search`: Search Haotian external KB
  - `ind_aidp_search`: Search an independently deployed AIDP KB
- Public web search:
  - `exa_search`: Web and image search via Exa
  - `tavily_search`: Web and image search via Tavily
  - `linkup_search`: Mixed text/image search via Linkup
  - `deepseek_search`: Public web search via DeepSeek with site filters and date ranges

> 💡 `knowledge_base_search` and `aidp_search` are **system-managed tools**: they do not appear in the agent tool pool and cannot be added or configured manually; at runtime the system injects them based on the deployment switch and user permissions, and the search scope is always intersected with the current user's permission whitelist. See [AIDP Integration](../aidp) for details.

## 🧰 Example Use Cases

- Retrieve internal docs, specs, and industry references (local KB, DataMate, Dify, RAGFlow, Haotian, iData)
- Query enterprise AIDP KBs for documents, tables, images, or technical drawings (AIDP)
- Fetch latest news or web evidence (Exa / Tavily / Linkup / DeepSeek)
- Return image references alongside text (with optional filtering)

## 🧾 Parameters & Behavior

Each tool has two kinds of parameters: **search parameters** are provided by the LLM at runtime, and **configuration parameters** are filled in the tool configuration dialog (applying to all calls of the agent once saved).

### knowledge_base_search (system-managed)
- **Search Parameters**:
  - `query`: Required.
  - `index_names`: Optional list of KB names (user-facing or internal).
- **Configuration Parameters**:
  - `top_k`: Number of results to return, default 3 (1–100)
  - `search_mode`: `hybrid` (default), `accurate`, or `semantic`
  - `rerank`: Whether to enable reranking, default False
  - `rerank_model_name`: Name of the rerank model; empty by default (uses the system-configured rerank model)
- Returns title, path/URL, source type, score, and citation info. Warns if no KB is selected.
- This tool cannot be selected manually from the tool pool; connection and KB scope are injected at runtime.

### datamate_search
- **Search Parameters**:
  - `query`: Required.
- **Configuration Parameters**:
  - `server_url`: DataMate server URL (e.g., `http://192.168.1.100:8080` or `https://datamate.example.com:8443`)
  - `verify_ssl`: Whether to verify SSL certificates (default False for HTTPS, True for HTTP)
  - `top_k`: Default 3.
  - `threshold`: Default 0.2.
  - `index_names`: Optional list of KB names to search.
  - `kb_page` / `kb_page_size`: Paginate DataMate KB list.
  - `rerank`: Whether to enable reranking, default False.
  - `rerank_model_name`: Name of the rerank model.
- Returns filename, download URL, and scores.

### dify_search
- **Search Parameters**:
  - `query`: Required.
- **Configuration Parameters**:
  - `server_url`: Dify API base URL
    - If you deploy Dify locally, use `http://host.docker.internal/v1` directly.
    - If you deploy Dify on a server, use `http://x.x.x.x:x/v1` and replace with the appropriate IP and port.
    - If you use Dify's official cloud service, use `https://api.dify.ai/v1` directly.
  - `api_key`: Dify knowledge base API key, starts with `dataset-` (create in Dify knowledge base page → API tab → API Keys button)
  - `dataset_ids`: List of dataset IDs (e.g., `["e912e1f5-29c0-40da-8baf-d35da77c60df"]`, found in Dify knowledge base page URL)
  - `top_k`: Number of results per KB, default 3
  - `search_method`: Search method options: `keyword_search`, `semantic_search`, `full_text_search`, `hybrid_search`, default `semantic_search`
  - `rerank`: Whether to enable reranking, default False
  - `rerank_model_name`: Name of the rerank model
- Returns title, content, score, etc.

### ragflow_search
- **Search Parameters**:
  - `query`: Required.
  - `doc_id`: Optional, restrict the search to specific documents (a single ID or a JSON array).
  - `dataset_ids`: Optional, temporarily override the KB scope for this search.
- **Configuration Parameters**:
  - `server_url`: RAGFlow API base URL (e.g., `http://<host>:9380`)
  - `api_key`: RAGFlow API key
  - `dataset_ids`: List of RAGFlow KB IDs to search
  - `top_k`: Number of results, default 3
  - `similarity_threshold`: Minimum similarity threshold, default 0.2
  - `vector_similarity_weight`: Vector similarity weight in hybrid search, default 0.3
  - `keyword`: Whether to enable keyword search in hybrid search, default False
  - `highlight`: Whether to highlight results, default True
- Results are returned by similarity in descending order; when nothing matches, the tool suggests relaxing or shortening the query.

### idata_search
- **Search Parameters**:
  - `question`: Required.
- **Configuration Parameters**:
  - `server_url`: iData API base URL
  - `api_key`: iData API key
  - `user_id`: iData user ID
  - `knowledge_space_id`: Knowledge space ID (the space list is fetched automatically once the first three fields are filled; choose from a searchable dropdown)
  - `dataset_ids`: KB IDs to search within the current space
  - `rerank_model_id`: Rerank model ID (required)
  - `top_k`: Maximum number of results, default 10
  - `similarity_threshold`: Rerank similarity threshold, default -10.0
  - `keyword_similarity_weight` / `vector_similarity_weight`: Keyword and vector similarity weights, default 0.10 / 0.3
- Two-level selection (knowledge space → KB); results include document download links as citation sources.

### haotian_search
- **Search Parameters**:
  - `query`: Required.
- **Configuration Parameters**:
  - `list_url`: Haotian knowledge set/KB list URL
  - `retrieve_url`: Haotian retrieval API URL
  - `authorization`: Authorization header (e.g., `Bearer xxx`)
  - `dataset_ids`: KB IDs to search (selected in the dedicated dialog by knowledge set → KB)
  - `top_k`: Number of results, default 3
  - `reranking_enable`: Whether to enable the retrieval API's built-in reranking, default False
  - `keyword_weight` / `vector_weight`: Keyword and vector similarity weights, default 0.1 / 0.3
  - `score_threshold_enabled` / `score_threshold`: Whether to enable the result filter threshold, and its value
- **Keyword search only**: the Haotian retrieval API does not support semantic or hybrid search; keep the default search method.

### aidp_search (system-managed)
- **Search Parameters**:
  - `query`: Required.
  - `kds_list`: Optional. KB IDs to search this time (up to 10); falls back to the system-injected default scope when omitted.
- **Configuration Parameters** (injected by the system from the deployment configuration; cannot be modified manually):
  - `search_method`: Retrieval channels — `vector_search`, `full_text_search`, `graph_search`, or pipe-separated combinations; all three enabled by default
  - `reranking_enable`: Whether to enable reranking, default True.
  - `reranking_mode`: Reranking strategy — `performance` (default) / `high_accuracy` / `jargon_coverage`
  - `rewrite_enable`: Whether to enable query rewrite, default False.
  - `query_expansion_enable`: Whether to enable query expansion, default False.
  - `related_search_enable`: Whether to enable related-chunk retrieval, default False.
  - `score_threshold`: Similarity threshold (0–1), default 0.0.
  - `top_k`: Number of results to return (1–100), default 10.
  - `multi_modal`: Whether to return multimodal chunks (image/table), default True.
  - Channel details: `vector_candidates` / `full_text_candidates` (candidates, default 10), `hybrid_top_k` / `graph_top_k` (per-channel result limits, 0 = no separate limit), `vector_score_threshold` / `full_text_score_threshold` / `graph_score_threshold` (per-channel thresholds), `graph_reranking_enable` (graph reranking)
- Returns text, table, and image chunks; images are also delivered through a dedicated channel.
- The search scope is filtered by the current chat user's AIDP permission whitelist. Whether the default scope or an LLM-supplied `kds_list` is used, it is intersected with KBs the user is allowed to access — unauthorized KBs are dropped.
- If no KB is accessible after filtering, the tool returns a clear no-permission message instead of silent empty results.

### ind_aidp_search
- **Search Parameters**:
  - `query`: Required.
  - `kds_list`: Optional. KB IDs for this call (up to 10); falls back to the tool-configured KBs when omitted.
- **Configuration Parameters**:
  - `server_url`: AIDP service address (must be an http/https URL without embedded credentials)
  - `api_key`: AIDP API key
  - `tenant_id`: AIDP tenant ID, default `aidp`
  - `kds_list`: KBs to search (selected in the picker dialog, up to 10)
  - Retrieval settings match `aidp_search` (channels, reranking strategy, candidates, query enhancements, multimodal), customized in the "Retrieval settings" section of the tool configuration dialog with a reset-to-default option
- Holds its own connection settings and does not participate in the managed permission system; multimodal images are proxied through Nexent and the key never reaches the browser.

### exa_search / tavily_search / linkup_search
- **Search Parameters**:
  - `query`: Required.
- **Configuration Parameters**:
  - `exa/tavily/linkup_api_key`: API key for the respective service
  - `max_results`: Number of results to return, default 3
  - `image_filter`: Whether to enable image filtering, default True
- Image filtering: On by default to drop unrelated images; can be disabled to return raw image URLs.
- Getting API Keys:
  - Exa: Sign up at [exa.ai](https://exa.ai/) and create an Exa API Key in the console
  - Tavily: Register at [tavily.com](https://www.tavily.com/) and get a Tavily API Key from the dashboard
  - Linkup: Sign up at [linkup.so](https://www.linkup.so/) and create a Linkup API Key in your account
- Returns title, URL, summary, and optional image URLs (deduped).

### deepseek_search
- **Search Parameters**:
  - `query`: Required. Supports `site:domain` (multiple sites joined by OR), `-site:domain`, `-keyword` and `-"phrase"` exclusions, `"exact phrase"`, and `after:` / `before:` date or year filters; keep the query within 120 characters.
- **Configuration Parameters**:
  - `deepseek_api_key`: DeepSeek API key (required)
  - `max_results`: Requested result count before quality filtering, default 10 (1–50)
  - `only_high_quality`: When enabled, return only results with a rerank score of at least 1.5
  - `need_content`: Return webpage content, falling back to summaries
  - `timeout_seconds`: Network timeout per attempt, default 30 (1–120)
  - `max_retries`: Maximum additional HTTP attempts, default 2 (0–2)

## 🛠️ How to Use

1. **Pick the source**: The local KB and AIDP are injected automatically (system-managed); choose DataMate, Dify, RAGFlow, Haotian, or iData by platform; use `ind_aidp_search` for an independently deployed AIDP; Exa/Tavily/Linkup/DeepSeek for public info.
2. **Tune mode/count**: Switch `search_mode`/`search_method` for KBs; adjust `max_results` and image filtering for public search.
3. **Fill connection and auth parameters**: DataMate, Dify, RAGFlow, Haotian, iData, and standalone AIDP all require the service URL and key in the tool configuration; managed AIDP credentials come from the deployment configuration and need no manual entry.
4. **Scope the searchable KBs**: Pick the retrieval scope in the KB selector of each external KB tool; the actual AIDP search is also filtered by the current chat user's permission whitelist.
5. **Narrow the query**: Provide `index_names` (local KB) or an explicit `kds_list` (AIDP) to scope results; tune `top_k` and `threshold` for DataMate precision.
6. **Rerank (optional)**: Enable each tool's `rerank` / `reranking_enable` and tune the model name or reranking strategy for better relevance.
7. **Consume results**: JSON output is ready for answers or summarization, with citation indices for referencing.

## 🛡️ Safety & Best Practices

- Store credentials (`api_key`, etc.) for public search and external KB services in the platform's secure config — never expose them in prompts.
- AIDP searches respect the current chat user's permissions. If a user cannot access a KB, it will not be returned even if the KB is in the configured scope — contact the AIDP admin to grant the right permissions.
- Sync KB content before querying to avoid stale answers.
- If queries are too broad, shorten or split them; if images are over-filtered, disable filtering to review raw URLs.
