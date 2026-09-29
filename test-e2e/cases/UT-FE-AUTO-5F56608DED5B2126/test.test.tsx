import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach, beforeAll } from 'vitest';
import { render, screen, within, waitFor, act, fireEvent, cleanup } from '@testing-library/react';
import { App } from 'antd';

import DocumentList from '@/app/[locale]/knowledges/components/document/DocumentList';

const mocks = vi.hoisted(() => ({
  tagLibraries: [] as any[],
  definitions: [] as any[],
  refreshDefinitions: vi.fn(),
  getDocumentBatchStatus: vi.fn(),
  logError: vi.fn(),
}));

vi.mock('@/lib/logger', () => ({
  default: { error: mocks.logError, warn: vi.fn(), info: vi.fn(), debug: vi.fn() },
}));

vi.mock('@/hooks/useStorageQuotaBlocked', () => ({
  useStorageQuotaBlocked: () => ({ isBlocked: false, message: null, usagePct: null, totalReadable: null, hardLimitReadable: null }),
}));

vi.mock('@/hooks/useConfig', () => ({
  useConfig: () => ({ config: {}, modelConfig: null }),
}));

vi.mock('@/hooks/model/useInferenceFieldSpecs', () => ({
  useInferenceFieldSpecs: () => ({ data: [], isLoading: false }),
}));

vi.mock('@/components/providers/AuthorizationProvider', () => ({
  useAuthorizationContext: () => ({ user: { tenantId: 'tenant-1' }, getAccessibleGroupIds: () => [] }),
}));

vi.mock('@/hooks/group/useGroupList', () => ({
  useGroupList: () => ({ data: { groups: [] }, allGroupIds: [], isLoading: false }),
  useGroupDetails: () => ({ groups: [] }),
}));

vi.mock('@/app/[locale]/knowledges/contexts/DocumentContext', () => ({
  useDocumentContext: () => ({
    state: { isLoadingDocuments: false, documentsMap: {}, selectedIds: [], uploadFiles: [], isUploading: false, loadingKbIds: new Set<string>(), error: null },
    dispatch: vi.fn(),
    fetchDocuments: vi.fn(),
    uploadDocuments: vi.fn(),
    deleteDocument: vi.fn(),
  }),
}));

vi.mock('@/components/permission/Can', () => ({
  Can: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
}));

vi.mock('@/hooks/useTagManagement', () => ({
  useTagLibraries: () => ({ data: mocks.tagLibraries, loading: false, error: null, refresh: vi.fn() }),
  useTagDefinitions: () => ({ data: mocks.definitions, loading: false, error: null, refresh: mocks.refreshDefinitions }),
  useTagAssignments: () => ({ data: null, loading: false, error: null, refresh: vi.fn(), replace: vi.fn(), replaceBulk: vi.fn() }),
}));

vi.mock('@/services/tagManagementService', () => ({
  tagManagementApi: {
    getDocumentBatchStatus: (...args: any[]) => mocks.getDocumentBatchStatus(...args),
    getAssignments: vi.fn().mockResolvedValue({ assignments: [] }),
  },
}));

vi.mock('@/components/tag/TagFilterControls', () => ({
  default: (props: any) => (
    <button type='button' data-testid='tag-filter-controls' onClick={() => props.onChange([{ definition_id: 1, value_ids: [1] }])}>
      filter-stub
    </button>
  ),
}));

vi.mock('@/components/tag/ResourceTagAssignmentModal', () => ({
  default: (props: any) => (props.open ? (
    <div data-testid='assign-modal' data-resource-type={props.resourceType} data-resource-id={props.resourceId} data-can-edit={String(props.canEdit)} />
  ) : null),
}));

vi.mock('@/components/tag/TagDefinitionManagementModal', () => ({
  default: (props: any) => (props.open ? <div data-testid='tag-management-modal' /> : null),
}));

vi.mock('@/app/[locale]/knowledges/components/document/DocumentStatus', () => ({
  default: (props: any) => <span data-testid='doc-status'>{props.status}</span>,
}));

vi.mock('@/app/[locale]/knowledges/components/document/DocumentChunk', () => ({
  default: () => <div data-testid='document-chunk' />,
}));

vi.mock('@/app/[locale]/knowledges/components/upload/UploadArea', () => ({
  default: () => <div data-testid='upload-area' />,
}));

vi.mock('@/components/common/markdownRenderer', () => ({
  MarkdownRenderer: ({ content }: any) => <div>{content}</div>,
}));

vi.mock('@/components/common/filePreviewDrawer', () => ({
  FilePreviewDrawer: () => null,
}));

vi.mock('react-i18next', () => ({
  initReactI18next: { type: '3rdParty', init: () => undefined },
  useTranslation: () => ({ t: (key: string) => key }),
}));

const documents = [
  { id: 'doc-beta', name: 'Beta.pdf', type: 'pdf', size: 2048, create_time: '2026-01-02T00:00:00Z', status: 'done', file_id: 'f-beta' },
  { id: 'doc-alpha', name: 'Alpha.pdf', type: 'pdf', size: 1024, create_time: '2026-01-01T00:00:00Z', status: 'done', file_id: 'f-alpha' },
];

const tagLibraries = [
  { bucket_id: 100, bucket_key: 'knowledge_content', bucket_name: 'knowledge_content', status: 'active', resource_types: ['knowledge_document'], definition_count: 1, definition_capacity: 20 },
];

const assignDefinitions = [
  { definition_id: 1, bucket_id: 100, definition_key: 'topic', definition_name: '主题', selection_mode: 'multi_select', sort_order: 0, status: 'active', active_value_count: 2, value_capacity: 20, values: [
    { value_id: 1, display_value: 'AI', normalized_value: 'ai', sort_order: 0, status: 'active' },
    { value_id: 2, display_value: 'Legal', normalized_value: 'legal', sort_order: 1, status: 'active' },
  ] },
];

function renderList(overrides: Record<string, any> = {}) {
  const props = {
    documents,
    knowledgeBaseId: 'kb-1',
    knowledgeBaseSource: '',
    knowledgeBaseName: 'KB1',
    permission: 'EDIT',
    onDelete: vi.fn(),
    onFileSelect: vi.fn(),
    ...overrides,
  };
  return render(<App><DocumentList {...props} /></App>);
}

describe(' 文档列表标签筛选、投影状态徽标、标签分配及 datamate/只读隐藏', () => {
  beforeAll(() => {
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      value: vi.fn().mockImplementation((query: string) => ({
        matches: false,
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        dispatchEvent: vi.fn(),
      })),
    });
    global.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} } as any;
  });

  beforeEach(() => {
    mocks.tagLibraries = tagLibraries;
    mocks.definitions = assignDefinitions;
    mocks.getDocumentBatchStatus.mockReset();
    mocks.getDocumentBatchStatus.mockResolvedValue([]);
    mocks.logError.mockReset();
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it('UT-FE-AUTO-5F56608DED5B2126  用例1：knowledge_content 库存在时渲染标签筛选与标签管理入口，列表按 create_time 降序', async () => {
    renderList();
    expect(await screen.findByText('document.tagFilter.placeholder')).toBeTruthy();
    expect(screen.getByText('knowledgeBase.button.tagManagement')).toBeTruthy();
    await waitFor(() => expect(mocks.getDocumentBatchStatus).toHaveBeenCalled());
    const rows = Array.from(document.querySelectorAll('tbody tr'));
    const names = rows.map((row) => {
      const span = row.querySelector('td:first-child span[title]');
      return span ? span.getAttribute('title') : null;
    });
    expect(names).toEqual(['Beta.pdf', 'Alpha.pdf']);
  });

  it(' 用例2：批状态 pending/failed 分别渲染 amber/red 徽标', async () => {
    mocks.getDocumentBatchStatus.mockResolvedValue([
      { document_id: 'doc-beta', assignment_count: 0, projection_status: { status: 'pending', version: 0, tag_count: 0, retry_count: 0 } },
      { document_id: 'doc-alpha', assignment_count: 0, projection_status: { status: 'failed', version: 0, tag_count: 0, retry_count: 0 } },
    ]);
    renderList();
    expect(await screen.findByText('pending')).toBeTruthy();
    expect(screen.getByText('failed')).toBeTruthy();
  });

  it(' 用例3：getDocumentBatchStatus 经 250ms 防抖仅调用一次', async () => {
    vi.useFakeTimers();
    renderList();
    await act(async () => { vi.advanceTimersByTime(250); });
    expect(mocks.getDocumentBatchStatus).toHaveBeenCalledTimes(1);
  });

  it(' 用例4：documentIds 截断至 200', async () => {
    const many = Array.from({ length: 250 }, (_, i) => ({ id: `doc-${i}`, name: `Doc${i}.pdf`, type: 'pdf', size: 1, create_time: new Date(2026, 0, 1, 0, 0, i).toISOString(), status: 'done', file_id: `f-${i}` }));
    renderList({ documents: many });
    await waitFor(() => expect(mocks.getDocumentBatchStatus).toHaveBeenCalled());
    const call = mocks.getDocumentBatchStatus.mock.calls[0];
    expect(call[0].documentIds.length).toBe(200);
  });

  it(' 用例5：卸载后旧请求不覆盖状态且无未捕获异常', async () => {
    let resolveBatch: (v: any[]) => void = () => {};
    mocks.getDocumentBatchStatus.mockReturnValue(new Promise((resolve) => { resolveBatch = resolve; }));
    const { unmount } = renderList();
    await waitFor(() => expect(mocks.getDocumentBatchStatus).toHaveBeenCalled());
    unmount();
    await act(async () => { resolveBatch([]); });
    expect(mocks.logError).not.toHaveBeenCalled();
  });

  it(' 用例6：点击分配标签打开 ResourceTagAssignmentModal 且契约正确', async () => {
    renderList();
    const assignBtns = screen.getAllByText('document.action.assignTags');
    fireEvent.click(assignBtns[0]);
    const modal = await screen.findByTestId('assign-modal');
    expect(modal.getAttribute('data-resource-type')).toBe('knowledge_document');
    expect(modal.getAttribute('data-resource-id')).toBe('doc-beta');
    expect(modal.getAttribute('data-can-edit')).toBe('true');
  });

  it(' 用例7：标签筛选谓词更新后列表过滤并可清除恢复', async () => {
    mocks.getDocumentBatchStatus.mockImplementation((_opts: any, predicates: any[]) => {
      if (predicates && predicates.length) {
        return Promise.resolve([{ document_id: 'doc-alpha', assignment_count: 0, projection_status: null }]);
      }
      return Promise.resolve([]);
    });
    renderList();
    fireEvent.click(screen.getByLabelText('filter').closest('button') as HTMLElement);
    const filterBtn = await screen.findByTestId('tag-filter-controls');
    fireEvent.click(filterBtn);
    await waitFor(() => expect(mocks.getDocumentBatchStatus).toHaveBeenCalled());
    expect(await screen.findByText('document.tagFilter.clear')).toBeTruthy();
    await waitFor(() => {
      expect(screen.queryByText('Beta.pdf')).toBeNull();
      expect(screen.getByText('Alpha.pdf')).toBeTruthy();
    });
  });

  it(' 用例8：datamate 模式隐藏标签入口、操作列与大小列', () => {
    renderList({ knowledgeBaseSource: 'datamate' });
    expect(screen.queryByText('document.tagFilter.placeholder')).toBeNull();
    expect(screen.queryByText('knowledgeBase.button.tagManagement')).toBeNull();
    expect(screen.queryByTestId('upload-area')).toBeNull();
    expect(screen.queryByText('document.action.assignTags')).toBeNull();
    expect(screen.queryByText('common.delete')).toBeNull();
  });

  it(' 用例9：READ_ONLY 隐藏标签管理与删除，分配 canEdit=false，批状态 reject 不阻塞渲染', async () => {
    mocks.getDocumentBatchStatus.mockRejectedValue(new Error('boom'));
    renderList({ permission: 'READ_ONLY' });
    expect(screen.queryByText('knowledgeBase.button.tagManagement')).toBeNull();
    expect(screen.queryByText('common.delete')).toBeNull();
    expect(await screen.findByText('Beta.pdf')).toBeTruthy();
    expect(screen.getByText('Alpha.pdf')).toBeTruthy();
    const assignBtns = screen.getAllByText('document.action.assignTags');
    fireEvent.click(assignBtns[0]);
    const modal = await screen.findByTestId('assign-modal');
    expect(modal.getAttribute('data-can-edit')).toBe('false');
  });
});
