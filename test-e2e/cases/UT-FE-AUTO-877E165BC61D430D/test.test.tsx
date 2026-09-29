// @vitest-environment jsdom
import React from 'react';
import { readFileSync } from 'node:fs';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import TagChips from '@/components/tag/TagChips';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

describe('unified tag definition and assignment component contract', () => {
  it('UT-FE-AUTO-877E165BC61D430D renders single/multi/no-value assignments and keeps management guards', () => {
    render(
      <TagChips
        max={2}
        assignments={[
          { definition_id: 1, value_id: 11, definition_key: 'category', definition_name: '分类', display_value: 'AI', selection_mode: 'single_select' },
          { definition_id: 2, value_id: 21, definition_key: 'topic', definition_name: '主题', display_value: '测试', selection_mode: 'multi_select' },
          { definition_id: 3, value_id: 0, definition_key: 'featured', definition_name: '精选', display_value: '', selection_mode: 'no_value' },
        ] as any}
      />,
    );
    expect(screen.getByLabelText('分类: AI')).toBeTruthy();
    expect(screen.getByLabelText('主题: 测试')).toBeTruthy();
    expect(screen.getByText('+1')).toBeTruthy();

    const repoRoot = process.env.NEXENT_REPO || process.env.NEXENT_REPO_ROOT;
    if (!repoRoot) {
      throw new Error('NEXENT_REPO must point to the local Nexent checkout');
    }
    const definitions = readFileSync(`${repoRoot}/frontend/components/tag/TagDefinitionManagementModal.tsx`, 'utf8');
    const assignments = readFileSync(`${repoRoot}/frontend/components/tag/ResourceTagAssignmentModal.tsx`, 'utf8');
    expect(definitions).toContain('createDefinition');
    expect(definitions).toContain('updateDefinitionStatus');
    expect(definitions).toContain('moveDefinitionToTop');
    expect(assignments).toContain('selection_mode === ("single_select" as TagSelectionMode)');
    expect(assignments).toContain('selection_mode === "no_value"');
    expect(assignments).toContain('assignmentCapacity');
    expect(assignments).toContain('replaceAssignments');
  });
});
