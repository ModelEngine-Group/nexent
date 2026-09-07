-- Support no-value tag definitions while preserving existing value-backed tags.
-- Legacy flat tags continue to use the existing keywords definition.

ALTER TABLE nexent.tag_definition
    DROP CONSTRAINT IF EXISTS tag_definition_selection_mode_check;

ALTER TABLE nexent.tag_definition
    ADD CONSTRAINT tag_definition_selection_mode_check
    CHECK (selection_mode IN ('single_select', 'multi_select', 'no_value'));
