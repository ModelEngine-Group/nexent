import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';

import KnowledgeBaseList from '@/app/[locale]/knowledges/components/knowledge/KnowledgeBaseList';
import { tagManagementApi } from '@/services/tagManagementService';
import type { KnowledgeBase } from '@/types/knowledgeBase';
import type { TagDefinition, TagLibrary } from '@/types/tagManagement';

vi.mock('react-i18next', async (importOriginal) => ({
  ...(await importOriginal<typeof import('react-i18next')>()),
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock('@/lib/logger', () => ({
  default: { debug: () => {}, info: () => {}, warn: () => {}, error: () => {}, log: () => {} },
}));

vi.mock('@/lib/systemTagLabels', () => ({
  getTagDefinitionDisplayName: (_key: string, name: string) => name,
  getTagValueDisplayName: (_key: string, value: string) => value,
  getTagSearchPredicates: () => [],
}));

vi.mock('@/services/knowledgeBaseService', () => ({ default: {} }));

vi.mock('@/services/tagManagementService', () => ({
  tagManagementApi: {
    listLibraries: vi.fn(),
    listDefinitions: vi.fn(),
    filterResourceIds: vi.fn(),
    getAssignments: vi.fn(),
    replaceAssignments: vi.fn(),
    replaceAssignmentsBulk: vi.fn(),
  },
  buildDocumentPredicate: vi.fn(),
  buildResourcePredicate: vi.fn(),
}));

vi.mock('@/hooks/group/useGroupList', () => ({
  useGroupList: () => ({ data: { groups: [] }, allGroupIds: [] }),
  useGroupDetails: () => ({ groups: [] }),
}));

vi.mock('@/components/permission/Can', () => ({
  Can: ({ children }: any) => children,
}));

vi.mock('@/components/providers/AuthorizationProvider', () => ({
  useAuthorizationContext: () => ({
    user: { tenantId: 'tenant-a', role: 'ADMIN' },
    getAccessibleGroupIds: () => [],
  }),
}));

vi.mock('@/components/tag/ResourceTagChips', () => ({
  default: ({ resourceType, resourceId, max }: any) => (
    <span data-testid='resource-tag-chips' data-resource-type={resourceType} data-resource-id={resourceId} data-max={String(max)} />
  ),
}));

vi.mock('@/components/tag/ResourceTagAssignmentModal', () => ({
  default: ({ open, canEdit, resourceId }: any) =>
    open ? (
      <div data-testid='resource-tag-assignment-modal' data-can-edit={String(canEdit)} data-resource-id={resourceId} />
    ) : null,
}));

vi.mock('@/components/tag/TagDefinitionManagementModal', () => ({
  default: ({ open, onClose, bucketId, canManage }: any) =>
    open ? (
      <div>
        <div data-testid='tag-definition-management-modal' data-bucket-id={String(bucketId)} data-can-manage={String(canManage)} />
        <button onClick={onClose}>close-def-modal</button>
      </div>
    ) : null,
}));

vi.mock('@/app/[locale]/knowledges/components/knowledge/KnowledgeBaseEditModal', () => ({
  KnowledgeBaseEditModal: () => null,
}));

vi.mock('@/app/[locale]/knowledges/components/knowledge/PersonalKnowledgeBaseCapacityBar', () => ({
  default: () => null,
}));

const defaultLibrary: TagLibrary = {
  bucket_id: 10,
  bucket_key: 'default_resource',
  bucket_name: 'Default',
  status: 'active',
  resource_types: ['knowledge_base'],
  definition_count: 1,
  definition_capacity: 10,
};

const definitions: TagDefinition[] = [
  {
    definition_id: 100,
    bucket_id: 10,
    definition_key: 'team',
    definition_name: 'Team',
    selection_mode: 'no_value',
    sort_order: 1,
    status: 'active',
    active_value_count: 1,
    value_capacity: 1,
    values: [
      { value_id: 1, display_value: 'assigned', normalized_value: 'assigned', sort_order: 1, status: 'active' },
    ],
  },
];

function makeKb(overrides: Partial<KnowledgeBase> = {}): KnowledgeBase {
  return {
    id: 'kb-1',
    name: 'Alpha KB',
    description: '',
    chunkCount: 0,
    documentCount: 0,
    createdAt: null,
    embeddingModel: 'model-x',
    avatar: '',
    chunkNum: 0,
    language: 'en',
    nickname: '',
    parserId: '',
    permission: 'EDIT',
    tokenNum: 0,
    source: 'nexent',
    ...overrides,
  };
}

const knowledgeBases: KnowledgeBase[] = [
  makeKb({ id: 'kb-1', name: 'Alpha KB', permission: 'EDIT' }),
  makeKb({ id: 'kb-2', name: 'Beta KB', permission: 'READ_ONLY' }),
  makeKb({ id: 'kb-3', name: 'Gamma KB', permission: 'EDIT' }),
];

const baseProps = {
  knowledgeBases,
  activeKnowledgeBase: null,
  onClick: vi.fn(),
  onDelete: vi.fn(),
  onSync: vi.fn(),
  onCreateNew: vi.fn(),
  getModelDisplayName: (modelId: string) => modelId,
};

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(tagManagementApi.listLibraries).mockResolvedValue([defaultLibrary]);
  vi.mocked(tagManagementApi.listDefinitions).mockResolvedValue(definitions);
  vi.mocked(tagManagementApi.filterResourceIds).mockResolvedValue({
    resource_type: 'knowledge_base',
    matched_resource_ids: [],
  });
  vi.mocked(tagManagementApi.getAssignments).mockResolvedValue({
    resource_type: 'knowledge_base',
    resource_id: '',
    assignment_count: 0,
    assignment_capacity: 100,
    assignments: [],
  });
});

async function renderList() {
  render(<KnowledgeBaseList {...baseProps} />);
  await screen.findByText('Alpha KB');
}

describe('KnowledgeBaseList tag filtering and assignment', () => {
  it('UT-FE-AUTO-BECEA5CE0869F353 renders the full list and exposes tag filters in the combined filter popover', async () => {
    await renderList();

    expect(screen.getByText('Alpha KB')).toBeTruthy();
    expect(screen.getByText('Beta KB')).toBeTruthy();
    expect(screen.getByText('Gamma KB')).toBeTruthy();

    const filterButton = screen.getByRole('button', { name: /knowledgeBase\.filter\.button/ });
    expect(filterButton.className).toContain('ant-btn-default');
    fireEvent.click(filterButton);
    expect(await screen.findByText('knowledgeBase.tagFilter.placeholder')).toBeTruthy();
  });

  it('selecting a predicate switches the filter to primary, shows clear, and calls filterResourceIds', async () => {
    await renderList();

    fireEvent.click(screen.getByLabelText('knowledgeBase.tagFilter.placeholder'));
    fireEvent.click(await screen.findByRole('checkbox'));

    await screen.findByRole('button', { name: 'knowledgeBase.tagFilter.clear' });

    expect(screen.getByLabelText('knowledgeBase.tagFilter.placeholder').className).toContain('ant-btn-primary');

    await waitFor(() => {
      expect(tagManagementApi.filterResourceIds).toHaveBeenCalledWith(
        'knowledge_base',
        ['kb-1', 'kb-2', 'kb-3'],
        [{ definition_id: 100, value_ids: [1] }],
      );
    });
  });

  it('matched_resource_ids filters the list and clearing restores the full list', async () => {
    vi.mocked(tagManagementApi.filterResourceIds).mockResolvedValue({
      resource_type: 'knowledge_base',
      matched_resource_ids: ['kb-2'],
    });

    await renderList();

    fireEvent.click(screen.getByLabelText('knowledgeBase.tagFilter.placeholder'));
    fireEvent.click(await screen.findByRole('checkbox'));

    await waitFor(() => {
      expect(screen.queryByText('Alpha KB')).toBeNull();
      expect(screen.queryByText('Gamma KB')).toBeNull();
      expect(screen.getByText('Beta KB')).toBeTruthy();
    });

    fireEvent.click(screen.getByRole('button', { name: 'knowledgeBase.tagFilter.clear' }));

    await waitFor(() => {
      expect(screen.getByText('Alpha KB')).toBeTruthy();
      expect(screen.getByText('Beta KB')).toBeTruthy();
      expect(screen.getByText('Gamma KB')).toBeTruthy();
    });

    expect(screen.getByLabelText('knowledgeBase.tagFilter.placeholder').className).toContain('ant-btn-default');
  });

  it('renders one ResourceTagChips per row with knowledge_base resource type and max 3', async () => {
    await renderList();

    const chips = screen.getAllByTestId('resource-tag-chips');
    expect(chips).toHaveLength(3);
    for (const chip of chips) {
      expect(chip.getAttribute('data-resource-type')).toBe('knowledge_base');
      expect(chip.getAttribute('data-max')).toBe('3');
    }
    const ids = chips.map((chip) => chip.getAttribute('data-resource-id')).sort();
    expect(ids).toEqual(['kb-1', 'kb-2', 'kb-3']);
  });

  it('sets assignTarget canEdit=false for READ_ONLY KB and opens the assignment modal read-only', async () => {
    await renderList();

    const betaRow = screen.getByText('Beta KB').closest('[data-knowledge-base-row]') as HTMLElement;
    expect(betaRow).toBeTruthy();
    const betaButtons = within(betaRow).getAllByRole('button');
    expect(betaButtons).toHaveLength(1);
    fireEvent.click(betaButtons[0]);

    await waitFor(() => {
      const modal = screen.getByTestId('resource-tag-assignment-modal');
      expect(modal.getAttribute('data-can-edit')).toBe('false');
      expect(modal.getAttribute('data-resource-id')).toBe('kb-2');
    });
  });

  it('sets assignTarget canEdit=true for an editable KB', async () => {
    await renderList();

    const alphaRow = screen.getByText('Alpha KB').closest('[data-knowledge-base-row]') as HTMLElement;
    const alphaButtons = within(alphaRow).getAllByRole('button');
    expect(alphaButtons.length).toBeGreaterThan(0);
    fireEvent.click(alphaButtons[0]);

    await waitFor(() => {
      const modal = screen.getByTestId('resource-tag-assignment-modal');
      expect(modal.getAttribute('data-can-edit')).toBe('true');
      expect(modal.getAttribute('data-resource-id')).toBe('kb-1');
    });
  });

  it('opens the tag definition management modal with the default library bucket and refreshes on close', async () => {
    await renderList();
    await waitFor(() => {
      expect(vi.mocked(tagManagementApi.listDefinitions).mock.calls.length).toBe(1);
    });

    fireEvent.click(screen.getByRole('button', { name: 'knowledgeBase.button.tagManagement' }));

    await waitFor(() => {
      const modal = screen.getByTestId('tag-definition-management-modal');
      expect(modal.getAttribute('data-bucket-id')).toBe('10');
      expect(modal.getAttribute('data-can-manage')).toBe('true');
    });

    const callsBefore = vi.mocked(tagManagementApi.listDefinitions).mock.calls.length;
    fireEvent.click(screen.getByRole('button', { name: 'close-def-modal' }));

    await waitFor(() => {
      expect(vi.mocked(tagManagementApi.listDefinitions).mock.calls.length).toBe(callsBefore + 1);
    });
  });
});
