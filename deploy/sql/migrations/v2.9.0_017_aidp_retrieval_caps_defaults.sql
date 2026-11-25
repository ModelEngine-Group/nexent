-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
--
-- AIDP retrieval caps are positive quotas, not "0 means unlimited".
--
-- AIDP rejects hybrid_top_k=0 and treats graph_top_k=0 as its own default 5,
-- which breaks the required hybrid_top_k + graph_top_k <= top_k relation.
-- Update the catalog definitions so newly configured tool instances start
-- from 5/5 with a 1-100 range. Explicit values already stored on existing
-- tool instances are intentionally left untouched.
--
-- The migration is idempotent and must not be edited after release.

WITH replacement AS (
    SELECT '{
      "type": "integer",
      "name": "hybrid_top_k",
      "description": "Vector/full-text cap (1-100); the sum with graph_top_k must not exceed top_k",
      "description_zh": "向量／全文返回上限；固定整数，1–100；与图谱返回上限之和不能超过返回条数上限",
      "default": 5,
      "optional": true,
      "constraints": {"ge": 1, "le": 100}
    }'::jsonb AS hybrid_def,
    '{
      "type": "integer",
      "name": "graph_top_k",
      "description": "Graph cap (1-100); the sum with hybrid_top_k must not exceed top_k",
      "description_zh": "图谱返回上限；固定整数，1–100；与向量／全文返回上限之和不能超过返回条数上限",
      "default": 5,
      "optional": true,
      "constraints": {"ge": 1, "le": 100}
    }'::jsonb AS graph_def
),
aidp_definitions AS (
    SELECT t.tool_id,
           (
               SELECT jsonb_agg(
                          CASE elem->>'name'
                               WHEN 'hybrid_top_k' THEN r.hybrid_def
                               WHEN 'graph_top_k' THEN r.graph_def
                               ELSE elem
                          END
                          ORDER BY ord
                      )
               FROM jsonb_array_elements(COALESCE(t.params::jsonb, '[]'::jsonb))
                    WITH ORDINALITY AS e(elem, ord)
           ) AS new_params
    FROM nexent.ag_tool_info_t AS t
    CROSS JOIN replacement AS r
    WHERE t.class_name IN ('AidpSearchTool', 'IndependentAidpSearchTool')
       OR t.name IN ('aidp_search', 'ind_aidp_search')
)
UPDATE nexent.ag_tool_info_t AS t
SET params = d.new_params::json
FROM aidp_definitions AS d
WHERE t.tool_id = d.tool_id
  AND d.new_params IS NOT NULL
  AND t.params::jsonb IS DISTINCT FROM d.new_params;
