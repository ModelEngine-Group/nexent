---
title: Search Tools
---

# Search Tools

Search tools cover internet search plus local and DataMate knowledge bases, useful for real-time info, industry materials, and private docs.

## 🧭 Tool List

- Local/private knowledge bases:
  - `knowledge_base_search`: Local KB search with multiple modes
  - `datamate_search_tool`: Search DataMate KB
- Public web search:
  - `exa_search`: Web and image search via Exa
  - `tavily_search`: Web and image search via Tavily
  - `linkup_search`: Mixed text/image search via Linkup

## 🧰 Example Use Cases

- Retrieve internal docs, specs, and industry references (KB, DataMate)
- Fetch latest news or web evidence (Exa / Tavily / Linkup)
- Return image references alongside text (with optional filtering)

## 🧾 Parameters & Behavior

### knowledge_base_search
- `query`: Required.
- `search_mode`: `hybrid` (default), `accurate`, or `semantic`.
- `index_names`: Optional list of KB names (user-facing or internal).
- Returns title, path/URL, source type, score, and citation info. Warns if no KB is selected.

### datamate_search_tool
- `query`: Required.
- `top_k`: Default 10.
- `threshold`: Default 0.2.
- `kb_page` / `kb_page_size`: Paginate DataMate KB list.
- Requires DataMate host and port. Returns filename, download URL, and scores.

### exa_search / tavily_search / linkup_search
- `query`: Required.
- `max_results`: Configurable count.
- Image filtering: On by default to drop unrelated images; can be disabled to return raw image URLs.
- Requires API keys:
  - Exa: EXA API Key
  - Tavily: Tavily API Key
  - Linkup: Linkup API Key
- Returns title, URL, summary, and optional image URLs (deduped).

## 🛠️ How to Use

1. **Pick the source**: Use `knowledge_base_search` or `datamate_search_tool` for private data; Exa/Tavily/Linkup for public info.
2. **Tune mode/count**: Switch `search_mode` for KB; adjust `max_results` and image filtering for public search.
3. **Scope**: Provide `index_names` for targeted KB search; tune `top_k` and `threshold` for DataMate precision.
4. **Consume results**: JSON output is ready for answers or summarization, with citation indices for referencing.

## 🛡️ Safety & Best Practices

- Store API keys in the platform’s secure config, never in prompts.
- Sync KB content before querying to avoid stale answers.
- If queries are too broad, shorten or split them; if images are over-filtered, disable filtering to review raw URLs.

## 🔑 Getting API Keys (Public Search)

- Exa: Sign up at [exa.ai](https://exa.ai/) and create an EXA API Key in the console.
- Tavily: Register at [tavily.com](https://www.tavily.com/) and get a Tavily API Key from the dashboard.
- Linkup: Sign up at [linkup.so](https://www.linkup.so/) and create a Linkup API Key in your account.

