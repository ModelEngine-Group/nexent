-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
--
-- AIDP retrieval caps are positive quotas, not "0 means unlimited".
--
-- AIDP rejects hybrid_top_k=0 and treats graph_top_k=0 as its own default 5,
-- which breaks the required hybrid_top_k + graph_top_k <= top_k relation.
-- Replace the full set of AIDP-specific catalog definitions so newly
-- configured tool instances start from 5/5 with a 1-100 range. Explicit
-- values already stored on existing tool instances are intentionally
-- left untouched.
--
-- The migration is idempotent and must not be edited after release.

WITH new_defs AS (
    SELECT '[
      {"type":"integer","name":"vector_candidates","description":"Vector candidates","description_zh":"向量初步检索条数；固定整数，1–500","default":10,"optional":true,"constraints":{"ge":1,"le":500}},
      {"type":"integer","name":"full_text_candidates","description":"Full-text candidates","description_zh":"全文初步检索条数；固定整数，1–500","default":10,"optional":true,"constraints":{"ge":1,"le":500}},
      {"type":"integer","name":"hybrid_top_k","description":"Vector/full-text cap (1-100); the sum with graph_top_k must not exceed top_k","description_zh":"向量／全文返回上限；固定整数，1–100；与图谱返回上限之和不能超过返回条数上限","default":5,"optional":true,"constraints":{"ge":1,"le":100}},
      {"type":"integer","name":"graph_top_k","description":"Graph cap (1-100); the sum with hybrid_top_k must not exceed top_k","description_zh":"图谱返回上限；固定整数，1–100；与向量／全文返回上限之和不能超过返回条数上限","default":5,"optional":true,"constraints":{"ge":1,"le":100}},
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
