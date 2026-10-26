-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
--
-- Fixed-value AIDP retrieval policy upgrade.
--
-- Historical AIDP tool definitions (released <= 2.7.0) predate the graph and
-- candidate fields. This migration:
--   1. appends the canonical missing parameter definitions to every AIDP tool
--      catalog row, preserving tool_id and all unrelated parameters;
--   2. materializes fixed candidate/boolean values on every AIDP tool instance
--      version, including soft-deleted rows, without overwriting explicit
--      values, and normalizes the legacy hybrid_search alias on instances.
-- Conversation and Workbench scopes no longer contain retrieval parameters.
--
-- The migration is idempotent and must not be edited after release.

WITH new_defs AS (
    SELECT '[
      {"type":"integer","name":"vector_candidates","description":"Vector candidates","description_zh":"向量初步检索条数；固定整数，1–500","default":10,"optional":true,"constraints":{"ge":1,"le":500}},
      {"type":"integer","name":"full_text_candidates","description":"Full-text candidates","description_zh":"全文初步检索条数；固定整数，1–500","default":10,"optional":true,"constraints":{"ge":1,"le":500}},
      {"type":"integer","name":"hybrid_top_k","description":"Vector/full-text cap; zero means no separate cap, still bounded by top_k","description_zh":"向量／全文部分返回上限；0 表示不单独限制，最终仍受总返回上限约束","default":0,"optional":true,"constraints":{"ge":0,"le":100}},
      {"type":"integer","name":"graph_top_k","description":"Graph cap; zero means no separate cap, still bounded by top_k","description_zh":"图谱返回上限；0 表示不单独限制，最终仍受总返回上限约束","default":0,"optional":true,"constraints":{"ge":0,"le":100}},
      {"type":"float","name":"vector_score_threshold","description":"Vector threshold","description_zh":"向量检索分数阈值，范围 0–1","default":0.0,"optional":true,"constraints":{"ge":0.0,"le":1.0}},
      {"type":"float","name":"full_text_score_threshold","description":"Full-text threshold","description_zh":"全文检索分数阈值，范围 0–1","default":0.0,"optional":true,"constraints":{"ge":0.0,"le":1.0}},
      {"type":"float","name":"graph_score_threshold","description":"Graph threshold","description_zh":"图谱检索分数阈值，范围 0–1","default":0.0,"optional":true,"constraints":{"ge":0.0,"le":1.0}},
      {"type":"boolean","name":"graph_reranking_enable","description":"Include graph results in unified reranking","description_zh":"图谱是否参与统一重排；固定布尔值","default":true,"optional":true},
      {"type":"boolean","name":"query_expansion_enable","description":"Enable query expansion","description_zh":"是否启用查询扩展","default":false,"optional":true}
    ]'::jsonb AS defs
),
aidp_definitions AS (
    SELECT t.tool_id, t.params::jsonb AS params
    FROM nexent.ag_tool_info_t AS t
    WHERE t.class_name IN ('AidpSearchTool', 'IndependentAidpSearchTool')
       OR t.name IN ('aidp_search', 'ind_aidp_search')
)
UPDATE nexent.ag_tool_info_t AS t
SET params = (
    SELECT COALESCE(
        (
            SELECT jsonb_agg(elem ORDER BY ord)
            FROM jsonb_array_elements(COALESCE(d.params, '[]'::jsonb))
                 WITH ORDINALITY AS e(elem, ord)
            WHERE elem->>'name' NOT IN (
                SELECT value->>'name'
                FROM jsonb_array_elements(nd.defs)
            )
        ),
        '[]'::jsonb
    ) || nd.defs
    FROM new_defs AS nd
)::json
FROM aidp_definitions AS d
WHERE t.tool_id = d.tool_id;

WITH aidp_instances AS (
    SELECT i.ctid, i.params::jsonb AS params
    FROM nexent.ag_tool_instance_t AS i
    JOIN nexent.ag_tool_info_t AS ti ON ti.tool_id = i.tool_id
    WHERE ti.class_name IN ('AidpSearchTool', 'IndependentAidpSearchTool')
       OR ti.name IN ('aidp_search', 'ind_aidp_search')
),
fixed_instances AS (
    SELECT ctid,
           jsonb_build_object(
               'vector_candidates',
                   COALESCE(
                       CASE WHEN jsonb_typeof(params->'vector_candidates') = 'number'
                            THEN (params->>'vector_candidates')::int END,
                       CASE WHEN jsonb_typeof(params->'top_k') = 'number'
                            THEN (params->>'top_k')::int END,
                       10
                   ),
               'full_text_candidates',
                   COALESCE(
                       CASE WHEN jsonb_typeof(params->'full_text_candidates') = 'number'
                            THEN (params->>'full_text_candidates')::int END,
                       CASE WHEN jsonb_typeof(params->'top_k') = 'number'
                            THEN (params->>'top_k')::int END,
                       10
                   ),
               'hybrid_top_k',
                   COALESCE(
                       CASE WHEN jsonb_typeof(params->'hybrid_top_k') = 'number'
                            THEN (params->>'hybrid_top_k')::int END,
                       0
                   ),
               'graph_top_k',
                   COALESCE(
                       CASE WHEN jsonb_typeof(params->'graph_top_k') = 'number'
                            THEN (params->>'graph_top_k')::int END,
                       0
                   ),
               'vector_score_threshold',
                   COALESCE(
                       CASE WHEN jsonb_typeof(params->'vector_score_threshold') = 'number'
                            THEN (params->>'vector_score_threshold')::numeric END,
                       0.0
                   ),
               'full_text_score_threshold',
                   COALESCE(
                       CASE WHEN jsonb_typeof(params->'full_text_score_threshold') = 'number'
                            THEN (params->>'full_text_score_threshold')::numeric END,
                       0.0
                   ),
               'graph_score_threshold',
                   COALESCE(
                       CASE WHEN jsonb_typeof(params->'graph_score_threshold') = 'number'
                            THEN (params->>'graph_score_threshold')::numeric END,
                       0.0
                   ),
               'graph_reranking_enable',
                   COALESCE(
                       CASE WHEN jsonb_typeof(params->'graph_reranking_enable') = 'boolean'
                            THEN (params->>'graph_reranking_enable')::boolean END,
                       CASE WHEN jsonb_typeof(params->'reranking_enable') = 'boolean'
                            THEN (params->>'reranking_enable')::boolean END,
                       true
                   ),
               'query_expansion_enable',
                   COALESCE(
                       CASE WHEN jsonb_typeof(params->'query_expansion_enable') = 'boolean'
                            THEN (params->>'query_expansion_enable')::boolean END,
                       false
                   ),
               'search_method',
                   CASE WHEN params->>'search_method' = 'hybrid_search'
                        THEN 'vector_search|full_text_search|graph_search'
                        ELSE COALESCE(params->>'search_method',
                                      'vector_search|full_text_search|graph_search')
                   END
           ) || (params - ARRAY[
               'vector_candidates', 'full_text_candidates', 'hybrid_top_k',
               'graph_top_k', 'vector_score_threshold', 'full_text_score_threshold',
               'graph_score_threshold', 'graph_reranking_enable',
               'query_expansion_enable', 'search_method'
           ]) AS new_params
    FROM aidp_instances
)
UPDATE nexent.ag_tool_instance_t AS i
SET params = f.new_params::json
FROM fixed_instances AS f
WHERE i.ctid = f.ctid;
