// @vitest-environment jsdom
import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import TagChips from '@/components/tag/TagChips';

import { existsSync, readFileSync } from 'node:fs';

/**
 * Concatenate the sources of a candidate list of components. Returns the first
 * existing file content, joined with any additional existing ones, so the
 * assertion follows the behaviour rather than one hard-coded path.
 */
function readComponentSource(repoRoot: string, relativePaths: string[]): string {
  const parts = relativePaths
    .map((relative) => `${repoRoot}/${relative}`)
    .filter((absolute) => existsSync(absolute))
    .map((absolute) => readFileSync(absolute, 'utf8'));
  if (parts.length === 0) {
    throw new Error(
      `none of the expected tag components exist under ${repoRoot}: ${relativePaths.join(', ')}`,
    );
  }
  return parts.join('\n');
}

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
    // The definition-management implementation lives in the *Panel* component;
    // the *Modal* is a thin shell around it since the tag-management
    // consolidation refactor. Assert against the components that actually own
    // the behaviour instead of pinning a single file name, so a future split of
    // the shell/panel pair does not break this contract test.
    const definitions = readComponentSource(repoRoot, [
      'frontend/components/tag/TagDefinitionManagementPanel.tsx',
      'frontend/components/tag/TagDefinitionManagementModal.tsx',
    ]);
    const assignments = readComponentSource(repoRoot, [
      'frontend/components/tag/ResourceTagAssignmentModal.tsx',
    ]);
    expect(definitions).toContain('createDefinition');
    expect(definitions).toContain('updateDefinitionStatus');
    expect(definitions).toContain('moveDefinitionToTop');
    expect(assignments).toContain('selection_mode === ("single_select" as TagSelectionMode)');
    expect(assignments).toContain('selection_mode === "no_value"');
    expect(assignments).toContain('assignmentCapacity');
    expect(assignments).toContain('replaceAssignments');
  });
});
