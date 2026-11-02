-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
--
-- Fixed-value AIDP retrieval policy upgrade.
--
-- Historical AIDP tool definitions (released <= 2.7.0) predate the graph and
-- candidate fields. This migration:
--   1. replaces the nine matching parameter definitions with canonical metadata
--      on every AIDP catalog row, preserving tool_id and unrelated parameters;
--   2. materializes fixed candidate/boolean values on every AIDP tool instance
--      version, including soft-deleted rows, without overwriting explicit
--      values, and normalizes legacy integer representations and hybrid_search.
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
    SELECT t.tool_id,
           COALESCE(
               (
                   SELECT jsonb_agg(elem ORDER BY ord)
                   FROM jsonb_array_elements(COALESCE(t.params::jsonb, '[]'::jsonb))
                        WITH ORDINALITY AS e(elem, ord)
                   WHERE elem->>'name' NOT IN (
                       SELECT value->>'name' FROM jsonb_array_elements(nd.defs)
                   )
               ),
               '[]'::jsonb
           ) || nd.defs AS new_params
    FROM nexent.ag_tool_info_t AS t
    CROSS JOIN new_defs AS nd
    WHERE t.class_name IN ('AidpSearchTool', 'IndependentAidpSearchTool')
       OR t.name IN ('aidp_search', 'ind_aidp_search')
)
UPDATE nexent.ag_tool_info_t AS t
SET params = d.new_params::json
FROM aidp_definitions AS d
WHERE t.tool_id = d.tool_id
  AND t.params::jsonb IS DISTINCT FROM d.new_params;

WITH aidp_instances AS (
    SELECT i.tool_instance_id, i.version_no, i.params::jsonb AS params,
           CASE WHEN jsonb_typeof(i.params::jsonb->'top_k') IN ('number', 'string')
                THEN (i.params::jsonb->>'top_k')::numeric::int END AS normalized_top_k
    FROM nexent.ag_tool_instance_t AS i
    JOIN nexent.ag_tool_info_t AS ti ON ti.tool_id = i.tool_id
    WHERE ti.class_name IN ('AidpSearchTool', 'IndependentAidpSearchTool')
       OR ti.name IN ('aidp_search', 'ind_aidp_search')
),
fixed_instances AS (
    SELECT tool_instance_id, version_no,
           jsonb_build_object(
               'vector_candidates',
                   COALESCE(
                       CASE WHEN jsonb_typeof(params->'vector_candidates') = 'number'
                             THEN (params->>'vector_candidates')::numeric::int END,
                        normalized_top_k,
                       10
                   ),
               'full_text_candidates',
                   COALESCE(
                       CASE WHEN jsonb_typeof(params->'full_text_candidates') = 'number'
                             THEN (params->>'full_text_candidates')::numeric::int END,
                        normalized_top_k,
                       10
                   ),
               'hybrid_top_k',
                   COALESCE(
                       CASE WHEN jsonb_typeof(params->'hybrid_top_k') = 'number'
                             THEN (params->>'hybrid_top_k')::numeric::int END,
                       0
                   ),
               'graph_top_k',
                   COALESCE(
                       CASE WHEN jsonb_typeof(params->'graph_top_k') = 'number'
                             THEN (params->>'graph_top_k')::numeric::int END,
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
            ]) || CASE WHEN normalized_top_k IS NOT NULL
                       THEN jsonb_build_object('top_k', normalized_top_k)
                       ELSE '{}'::jsonb END AS new_params
    FROM aidp_instances
)
UPDATE nexent.ag_tool_instance_t AS i
SET params = f.new_params::json
FROM fixed_instances AS f
WHERE i.tool_instance_id = f.tool_instance_id
  AND i.version_no = f.version_no
  AND i.params::jsonb IS DISTINCT FROM f.new_params;
