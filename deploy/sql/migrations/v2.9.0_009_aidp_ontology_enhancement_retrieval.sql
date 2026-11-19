-- Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
--
-- ONT-006 AIDP ontology retrieval enhancement parameters.
--
-- The AIDP tool configuration modal renders and persists only parameters that
-- exist in ag_tool_info_t.params. Add the two optional boolean definitions to
-- both AIDP catalog tools so the switches can be saved. Existing definitions
-- keep their order and are never replaced. Tool instances are intentionally not
-- backfilled: a missing key means disabled and the SDK default is false.

WITH new_defs AS (
    SELECT '[
      {"type":"boolean","name":"ontology_enhance_enable","description":"Use the linked ontology entities and relations to enhance retrieval","description_zh":"使用已关联本体库的实体及同义、上位、下位关系增强检索","default":false,"optional":true},
      {"type":"boolean","name":"rule_enable","description":"Use enabled ontology rules to adjust candidate scores","description_zh":"使用本体库中已启用的规则调整候选结果分数","default":false,"optional":true}
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
