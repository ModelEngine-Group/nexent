import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

import {
  reorderModelIds,
  resolveModelSelection,
  type ModelPriorityOption,
} from '@/lib/agent/modelPriority';

const MODEL_OPTIONS: ModelPriorityOption[] = [
  { value: 1, displayName: 'Primary' },
  { value: 2, displayName: 'Fallback A' },
  { value: 3, displayName: 'Fallback B' },
];

function readAgentPromptSource(): string {
  const repo = process.env.NEXENT_REPO;
  if (!repo) {
    throw new Error('NEXENT_REPO must point to the local Nexent checkout');
  }
  return readFileSync(
    resolve(repo, 'frontend/app/[locale]/agents/components/agent-prompt.tsx'),
    'utf-8',
  );
}

describe('model priority reorder & name resolution', () => {
  it('UT-FE-AUTO-4971F03331327F7A exports reorderModelIds and resolveModelSelection as pure functions', () => {
    expect(typeof reorderModelIds).toBe('function');
    expect(typeof resolveModelSelection).toBe('function');
  });

  it('reorders [1,2,3] with active=3 over=1 to [3,1,2] and does not mutate the input', () => {
    const modelIds = [1, 2, 3];
    const result = reorderModelIds(modelIds, 3, 1);
    expect(result).toEqual([3, 1, 2]);
    expect(modelIds).toEqual([1, 2, 3]);
    expect(result).not.toBe(modelIds);
  });

  it('returns the original array reference when activeId or overId is missing', () => {
    const modelIds = [1, 2, 3];
    expect(reorderModelIds(modelIds, 99, 1)).toBe(modelIds);
    expect(reorderModelIds(modelIds, 1, 99)).toBe(modelIds);
    expect(modelIds).toEqual([1, 2, 3]);
  });

  it('returns the original array reference when activeId and overId share the same index', () => {
    const modelIds = [1, 2, 3];
    expect(reorderModelIds(modelIds, 2, 2)).toBe(modelIds);
    expect(modelIds).toEqual([1, 2, 3]);
  });

  it('resolves model, model_ids and model_names for the reordered order', () => {
    const reordered = reorderModelIds([1, 2, 3], 3, 1);
    const selection = resolveModelSelection(reordered, MODEL_OPTIONS);
    expect(selection.model_ids).toEqual([3, 1, 2]);
    expect(selection.model).toBe('Fallback B');
    expect(selection.model_names).toEqual(['Fallback B', 'Primary', 'Fallback A']);
  });

  it('resolves the first model as primary and maps names one-to-one with modelIds order', () => {
    const modelIds = [2, 3, 1];
    const selection = resolveModelSelection(modelIds, MODEL_OPTIONS);
    expect(selection.model_names).toHaveLength(modelIds.length);
    modelIds.forEach((id, index) => {
      const option = MODEL_OPTIONS.find((o) => o.value === id);
      expect(option).toBeDefined();
      expect(selection.model_names[index]).toBe(option!.displayName);
    });
    expect(selection.model).toBe(selection.model_names[0]);
  });

  it('maps unknown ids to an empty name and empty model when the first id is unknown', () => {
    const selection = resolveModelSelection([999, 1], MODEL_OPTIONS);
    expect(selection.model_ids).toEqual([999, 1]);
    expect(selection.model).toBe('');
    expect(selection.model_names).toEqual(['', 'Primary']);
  });

  it('agent-prompt.tsx shows the priority popover via ListOrdered and syncs the reorder with form.setFieldValue', () => {
    const source = readAgentPromptSource();
    expect(source).toContain('Popover');
    expect(source).toContain('ListOrdered');
    expect(source).toContain('Form.useFormInstance()');
    expect(source).toContain('setFieldValue("model_ids", modelIds)');
    expect(source).toContain('reorderModelIds');
    expect(source).toContain('resolveModelSelection');
  });
});
