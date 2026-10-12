-- Keep knowledge_base_search hidden and independent AIDP search selectable.
UPDATE nexent.ag_tool_info_t
SET is_user_selectable = FALSE
WHERE name = 'knowledge_base_search'
  AND is_user_selectable IS DISTINCT FROM FALSE;

UPDATE nexent.ag_tool_info_t
SET is_user_selectable = TRUE
WHERE name = 'ind_aidp_search'
  AND is_user_selectable IS DISTINCT FROM TRUE;
