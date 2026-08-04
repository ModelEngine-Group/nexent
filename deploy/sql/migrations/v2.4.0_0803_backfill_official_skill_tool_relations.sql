-- Backfill tool dependencies for official skills installed before allowed-tools
-- metadata was added to the bundled skill archives.
SET search_path TO nexent;

WITH skill_tool_mapping(skill_name, tool_name) AS (
    VALUES
        ('analyze-image', 'analyze_image'),
        ('analyze-text-file', 'analyze_text_file'),
        ('create-file-directory', 'create_file'),
        ('create-file-directory', 'create_directory'),
        ('delete-file-directory', 'delete_file'),
        ('delete-file-directory', 'delete_directory'),
        ('email-utils', 'get_email'),
        ('email-utils', 'send_email'),
        ('list-directory', 'list_directory'),
        ('move-file-directory', 'move_item'),
        ('read-file', 'read_file'),
        ('run-shell-ssh', 'terminal'),
        ('search-datamate', 'datamate_search'),
        ('search-dify', 'dify_search'),
        ('search-idata', 'idata_search'),
        ('search-knowledge-base', 'knowledge_base_search'),
        ('search-web-exa', 'exa_search'),
        ('search-web-linkup', 'linkup_search'),
        ('search-web-tavily', 'tavily_search')
),
updated_relations AS (
    UPDATE nexent.ag_skill_tools_rel_t AS relation
    SET
        created_by = COALESCE(
            relation.created_by,
            skill.created_by,
            skill.updated_by,
            tool.created_by,
            tool.updated_by
        ),
        updated_by = COALESCE(
            relation.updated_by,
            skill.updated_by,
            skill.created_by,
            tool.updated_by,
            tool.created_by
        ),
        update_time = CURRENT_TIMESTAMP
    FROM skill_tool_mapping mapping
    JOIN nexent.ag_skill_info_t skill
        ON skill.skill_name = mapping.skill_name
        AND skill.delete_flag != 'Y'
        AND skill.source IN ('official', '官方')
    JOIN nexent.ag_tool_info_t tool
        ON tool.name = mapping.tool_name
        AND tool.delete_flag != 'Y'
        AND tool.author = skill.tenant_id
    WHERE relation.skill_id = skill.skill_id
      AND relation.tool_id = tool.tool_id
      AND relation.delete_flag != 'Y'
      AND (relation.created_by IS NULL OR relation.updated_by IS NULL)
    RETURNING relation.skill_id, relation.tool_id
)
INSERT INTO nexent.ag_skill_tools_rel_t (
    skill_id,
    tool_id,
    created_by,
    updated_by,
    delete_flag
)
SELECT
    skill.skill_id,
    tool.tool_id,
    COALESCE(skill.created_by, skill.updated_by, tool.created_by, tool.updated_by),
    COALESCE(skill.updated_by, skill.created_by, tool.updated_by, tool.created_by),
    'N'
FROM skill_tool_mapping mapping
JOIN nexent.ag_skill_info_t skill
    ON skill.skill_name = mapping.skill_name
    AND skill.delete_flag != 'Y'
    AND skill.source IN ('official', '官方')
JOIN nexent.ag_tool_info_t tool
    ON tool.name = mapping.tool_name
    AND tool.delete_flag != 'Y'
    AND tool.author = skill.tenant_id
WHERE NOT EXISTS (
    SELECT 1
    FROM nexent.ag_skill_tools_rel_t relation
    WHERE relation.skill_id = skill.skill_id
      AND relation.tool_id = tool.tool_id
      AND relation.delete_flag != 'Y'
);
