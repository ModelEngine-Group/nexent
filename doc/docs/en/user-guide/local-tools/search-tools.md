---
title: Search Tools
---

# Search Tools

Search tools cover internet search plus local, DataMate, and Dify knowledge bases, useful for real-time info, industry materials, and private docs.

## 🧭 Tool List

- Local/private knowledge bases:
  - `knowledge_base_search`: Local KB search with multiple modes
  - `datamate_search`: Search DataMate KB
  - `dify_search`: Search Dify KB
- Public web search:
  - `exa_search`: Web and image search via Exa
  - `tavily_search`: Web and image search via Tavily
  - `linkup_search`: Mixed text/image search via Linkup

## 🧰 Example Use Cases

- Retrieve internal docs, specs, and industry references (KB, DataMate, Dify)
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

1. **Pick the source**: Use `knowledge_base_search`, `datamate_search`, or `dify_search` for private data; Exa/Tavily/Linkup for public info.
2. **Tune mode/count**: Switch `search_mode` for KB; adjust `max_results` and image filtering for public search.
3. **Scope**: Provide `index_names` for targeted KB search; tune `top_k` and `threshold` for DataMate precision.
4. **Consume results**: JSON output is ready for answers or summarization, with citation indices for referencing.

## 🛡️ Safety & Best Practices

- Store API keys in the platform’s secure config, never in prompts.
- Sync KB content before querying to avoid stale answers.
- If queries are too broad, shorten or split them; if images are over-filtered, disable filtering to review raw URLs.
