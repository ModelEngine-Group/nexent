---
title: Search Tools
---

# Search Tools

Search tools cover internet search plus local, AIDP, DataMate, and Dify knowledge bases, useful for real-time info, industry materials, private docs, and multimodal enterprise KB retrieval.

## 🧭 Tool List

- Local/private knowledge bases:
  - `knowledge_base_search`: Local KB search with multiple modes
  - `aidp_search`: Search AIDP enterprise KBs via multimodal FusionSearch
  - `datamate_search`: Search DataMate KB
  - `dify_search`: Search Dify KB
- Public web search:
  - `exa_search`: Web and image search via Exa
  - `tavily_search`: Web and image search via Tavily
  - `linkup_search`: Mixed text/image search via Linkup

## 🧰 Example Use Cases

- Retrieve internal docs, specs, and industry references (KB, DataMate, Dify)
- Query enterprise AIDP KBs for documents, tables, images, or technical drawings (AIDP)
- Fetch latest news or web evidence (Exa / Tavily / Linkup)
- Return image references alongside text (with optional filtering)

## 🧾 Parameters & Behavior

### knowledge_base_search
- **Configuration Parameters**: `top_k` (number of results to return, default 3)
- **Search Parameters**:
  - `query`: Required.
  - `search_mode`: `hybrid` (default), `accurate`, or `semantic`.
  - `index_names`: Optional list of KB names (user-facing or internal).
- Returns title, path/URL, source type, score, and citation info. Warns if no KB is selected.

### datamate_search
- **Configuration Parameters**:
  - `server_url`: DataMate server URL (e.g., `http://192.168.1.100:8080` or `https://datamate.example.com:8443`)
  - `verify_ssl`: Whether to verify SSL certificates (default False for HTTPS, True for HTTP)
- **Search Parameters**:
  - `query`: Required.
  - `top_k`: Default 10.
  - `threshold`: Default 0.2.
  - `index_names`: Optional list of KB names to search.
  - `kb_page` / `kb_page_size`: Paginate DataMate KB list.
- Returns filename, download URL, and scores.

### dify_search
- **Configuration Parameters**:
  - `dify_api_base`: Dify API base URL
    - If you deploy Dify locally, use `http://host.docker.internal/v1` directly.
    - If you deploy Dify on a server, use `http://x.x.x.x:x/v1`and replace with the appropriate IP and port.
    - If you use Dify's official cloud service, use `https://api.dify.ai/v1`  directly.
  - `api_key`: Dify knowledge base API key, start with `dataset-` (create in Dify knowledge base page → API tab → API Keys button)
  - `dataset_ids`: List of dataset IDs (e.g., `["e912e1f5-29c0-40da-8baf-d35da77c60df"]`, found in Dify knowledge base page URL)
  - `top_k`: Number of results to return, default 3
- **Search Parameters**:
  - `query`: Required.
  - `search_method`: Search method options: `keyword_search`, `semantic_search`, `full_text_search`, `hybrid_search`, default `semantic_search`.
- Returns title, content, score, etc.

### aidp_search
- **Configuration Parameters**:
  - `server_url`: AIDP API base URL, e.g. `https://141.111.61.70:30080`.
  - `api_key`: AIDP API key, typically prefixed with `ak_`, issued by the AIDP platform admin.
  - `tenant_id`: Tenant identifier used in AIDP API paths, e.g. `aidp`.
  - `kds_list`: JSON string array of knowledge base IDs (`kds_id`) to search (e.g. `["aidp-kb-01", "aidp-kb-02"]`). Determines which AIDP KBs the tool accesses by default.
  - `search_method`: Search method options: `hybrid_search` (default, fusion), `vector_search` (vector), `full_text_search` (full text).
  - `reranking_enable`: Whether to enable reranking, default True.
  - `reranking_mode`: Reranking mode options: `performance` (default) / `high_accuracy`.
  - `rewrite_enable`: Whether to enable query rewrite, default False.
  - `related_search_enable`: Whether to enable related-chunk retrieval, default False.
  - `score_threshold`: Similarity threshold (0–1), default 0.0.
  - `top_k`: Number of results to return (1–100), default 10.
  - `multi_modal`: Whether to return multimodal chunks (image/table), default True.
- **Search Parameters**:
  - `query`: Required.
  - `kds_list`: Optional. Knowledge base IDs to search this time; falls back to the configured `kds_list` when omitted.
- Returns text, table, and image chunks via dual-channel output: all chunks as `SEARCH_CONTENT`, with image `file_url`s also delivered as `PICTURE_WEB`.
- The search scope is filtered by the current chat user's AIDP permission whitelist. Whether the default `kds_list` or an LLM-supplied one is used, it is intersected with KBs the user is allowed to access — unauthorized KBs are silently dropped.
- If no KB is accessible after filtering, the tool returns a clear no-permission message instead of silent empty results.

### exa_search / tavily_search / linkup_search
- **Configuration Parameters**:
  - `exa/tavily/linkup_api_key`: API key for the respective service
  - `max_results`: Number of results to return, default 5
  - `image_filter`: Whether to enable image filtering, default True
- **Search Parameters**:
  - `query`: Required.
- Image filtering: On by default to drop unrelated images; can be disabled to return raw image URLs.
- Getting API Keys:
  - Exa: Sign up at [exa.ai](https://exa.ai/) and create an EXA API Key in the console
  - Tavily: Register at [tavily.com](https://www.tavily.com/) and get a Tavily API Key from the dashboard
  - Linkup: Sign up at [linkup.so](https://www.linkup.so/) and create a Linkup API Key in your account
- Returns title, URL, summary, and optional image URLs (deduped).

## 🛠️ How to Use

1. **Pick the source**: Use `knowledge_base_search`, `aidp_search`, `datamate_search`, or `dify_search` for private data; Exa/Tavily/Linkup for public info.
2. **Tune mode/count**: Switch `search_mode`/`search_method` for KB; adjust `max_results` and image filtering for public search.
3. **Fill connection and auth parameters**: AIDP requires `server_url`, `api_key`, and `tenant_id` — run a test connection in the platform's secure config first.
4. **Scope the searchable KBs**: For AIDP, use `kds_list` in the tool configuration to pick the default KBs; the actual search is also filtered by the current chat user's AIDP permission whitelist.
5. **Narrow the query**: Provide `index_names` (local KB) or an explicit `kds_list` (AIDP) to scope results; tune `top_k` and `threshold` for DataMate precision.
6. **Rerank (optional)**: Set `enable_rerank: true` or `reranking_enable: true`, and tune the model/mode parameters for better relevance.
7. **Consume results**: JSON output is ready for answers or summarization, with citation indices for referencing.

## 🛡️ Safety & Best Practices

- Store credentials (`api_key`, etc.) for public search and AIDP in the platform's secure config — never expose them in prompts.
- AIDP searches respect the current chat user's permissions. If a user cannot access a KB, it will not be returned even if the KB is in the tool's `kds_list` — contact the AIDP admin to grant the right permissions.
- Sync KB content before querying to avoid stale answers.
- If queries are too broad, shorten or split them; if images are over-filtered, disable filtering to review raw URLs.
