// @vitest-environment jsdom
import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Form } from 'antd';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';

import AgentInfo from '@/app/[locale]/agents/[agentId]/components/agent-info';

const hoisted = vi.hoisted(() => ({
  isReadOnly: false,
  storeState: {
    agentId: 123 as number | null,
    editedAgent: null as any,
    updateDraft: vi.fn(),
    isReadOnly: false,
  },
  tagLibraries: null as any,
  tagDefinitions: null as any,
  refreshTagDefinitions: vi.fn(),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: 'zh', changeLanguage: () => new Promise(() => {}) },
  }),
}));

vi.mock('@/stores/agentStore', () => ({
  useAgentStore: (selector: (state: any) => any) => selector(hoisted.storeState),
}));

vi.mock('@/hooks/agent/useAgentReadOnly', () => ({
  useAgentReadOnly: () => hoisted.isReadOnly,
}));

vi.mock('@/hooks/agent/useSaveGuard', () => ({
  AGENT_NAME_MAX_LENGTH: 60,
  AGENT_DESCRIPTION_MAX_LENGTH: 500,
  isValidAgentName: () => true,
  createAgentNameConflictValidator: () => ({ validator: async () => {} }),
}));

vi.mock('@/services/api', () => ({
  API_ENDPOINTS: { agent: { icon: (id: number) => '/api/agent/' + id + '/icon' } },
}));

vi.mock('@/lib/auth', () => ({
  fetchWithAuth: vi.fn(),
}));

vi.mock('@/lib/chat/agentIconUtils', () => ({
  getAgentIcon: () => () => null,
}));

vi.mock('@/hooks/useTagManagement', () => ({
  useTagLibraries: () => ({
    data: hoisted.tagLibraries,
    loading: false,
    error: null,
    refresh: () => Promise.resolve(),
  }),
  useTagDefinitions: (bucketId: number | null) => ({
    data: bucketId === null ? [] : hoisted.tagDefinitions,
    loading: false,
    error: null,
    refresh: hoisted.refreshTagDefinitions,
  }),
  useTagAssignments: () => ({
    data: null,
    loading: false,
    error: null,
    refresh: () => Promise.resolve(),
    replace: () => Promise.resolve(null),
    replaceBulk: () => Promise.resolve([]),
  }),
}));

vi.mock('@/components/tag/ResourceTagChips', () => ({
  default: function MockResourceTagChips(props: any) {
    return (
      <div
        data-testid='resource-tag-chips'
        data-resource-type={props.resourceType}
        data-resource-id={props.resourceId}
        data-max={String(props.max)}
        data-single-line={String(props.singleLine)}
        data-refresh-key={String(props.refreshKey)}
      >
        {props.emptyText}
      </div>
    );
  },
}));

vi.mock('@/components/tag/ResourceTagAssignmentModal', () => ({
  default: function MockResourceTagAssignmentModal(props: any) {
    if (!props.open) return null;
    return (
      <div
        data-testid='assignment-modal'
        data-resource-type={props.resourceType}
        data-resource-id={props.resourceId}
        data-can-edit={String(props.canEdit)}
        data-definitions-count={String((props.definitions ?? []).length)}
      >
        <button type='button' onClick={props.onClose} data-testid='assignment-confirm'>
          confirm
        </button>
        {props.onManageDefinitions ? (
          <button type='button' onClick={props.onManageDefinitions} data-testid='assignment-manage'>
            manage
          </button>
        ) : null}
      </div>
    );
  },
}));

vi.mock('@/components/tag/TagDefinitionManagementModal', () => ({
  default: function MockTagDefinitionManagementModal(props: any) {
    if (!props.open) return null;
    return (
      <div
        data-testid='management-modal'
        data-bucket-id={String(props.bucketId)}
        data-bucket-name={props.bucketName}
        data-can-manage={String(props.canManage)}
      >
        <button type='button' onClick={props.onClose} data-testid='management-close'>
          close
        </button>
      </div>
    );
  },
}));

beforeAll(() => {
  if (typeof window !== 'undefined' && !window.matchMedia) {
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      value: (query: string) => ({
        matches: false,
        media: query,
        onchange: null,
        addListener: () => {},
        removeListener: () => {},
        addEventListener: () => {},
        removeEventListener: () => {},
        dispatchEvent: () => false,
      }),
    });
  }
});

const DEFAULT_LIBRARY = {
  bucket_id: 10,
  bucket_key: 'default_resource',
  bucket_name: '资源标签',
};

const DEFAULT_DEFINITIONS = [
  {
    definition_id: 1,
    definition_key: 'department',
    definition_name: '部门',
    selection_mode: 'multi_select',
    status: 'active',
    values: [{ value_id: 100, display_value: '研发', status: 'active' }],
    active_value_count: 1,
    value_capacity: 100,
  },
];

function setupEditableAgent() {
  hoisted.isReadOnly = false;
  hoisted.storeState = {
    agentId: 123,
    editedAgent: {
      name: 'my_agent',
      display_name: 'My Agent',
      description: 'desc',
      author: 'me',
      icon_url: null,
    },
    updateDraft: vi.fn(),
    isReadOnly: false,
  };
  hoisted.tagLibraries = [DEFAULT_LIBRARY];
  hoisted.tagDefinitions = DEFAULT_DEFINITIONS;
  hoisted.refreshTagDefinitions = vi.fn();
}

function renderAgentInfo() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  function Harness() {
    const [form] = Form.useForm();
    return (
      <Form form={form}>
        <AgentInfo />
      </Form>
    );
  }
  return render(<QueryClientProvider client={queryClient}><Harness /></QueryClientProvider>);
}

function editButton() {
  return screen.getByRole('button', { name: 'tagManagement.action.editTags' }) as HTMLButtonElement;
}

describe('AgentInfo 资源标签集成 (F-054 / PW-AGENT-01)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupEditableAgent();
  });

  it('UT-FE-AUTO-3D13A0DB24D58E7C 渲染“分配标签”标签区并按契约渲染 ResourceTagChips', () => {
    renderAgentInfo();
    expect(screen.getByText('tagManagement.title.assignTags')).toBeTruthy();
    const chips = screen.getByTestId('resource-tag-chips');
    expect(chips.getAttribute('data-resource-type')).toBe('agent');
    expect(chips.getAttribute('data-resource-id')).toBe('123');
    expect(chips.getAttribute('data-max')).toBe('4');
    expect(chips.getAttribute('data-single-line')).toBe('true');
    expect(within(chips).getByText('—')).toBeTruthy();
  });

  it('agentId 有效且非只读时编辑入口可用', () => {
    renderAgentInfo();
    expect(editButton().disabled).toBe(false);
  });

  it('agentId=null 时编辑入口禁用且不渲染 chips，展示空态', () => {
    hoisted.storeState = { ...hoisted.storeState, agentId: null };
    renderAgentInfo();
    expect(editButton().disabled).toBe(true);
    expect(screen.queryByTestId('resource-tag-chips')).toBeNull();
    expect(screen.getByText('—')).toBeTruthy();
  });

  it('isReadOnly=true 时编辑入口禁用', () => {
    hoisted.isReadOnly = true;
    renderAgentInfo();
    expect(editButton().disabled).toBe(true);
  });

  it('点击“编辑标签”按契约打开分配弹窗', async () => {
    const user = userEvent.setup();
    renderAgentInfo();
    await user.click(editButton());
    const modal = screen.getByTestId('assignment-modal');
    expect(modal.getAttribute('data-resource-type')).toBe('agent');
    expect(modal.getAttribute('data-resource-id')).toBe('123');
    expect(modal.getAttribute('data-can-edit')).toBe('true');
    expect(modal.getAttribute('data-definitions-count')).toBe('1');
    expect(screen.getByTestId('assignment-manage')).toBeTruthy();
  });

  it('新增/移除后关闭弹窗递增 tagPreviewRefreshKey 并刷新预览', async () => {
    const user = userEvent.setup();
    renderAgentInfo();
    expect(screen.getByTestId('resource-tag-chips').getAttribute('data-refresh-key')).toBe('0');

    await user.click(editButton());
    await user.click(screen.getByTestId('assignment-confirm'));

    expect(screen.queryByTestId('assignment-modal')).toBeNull();
    expect(screen.getByTestId('resource-tag-chips').getAttribute('data-refresh-key')).toBe('1');

    await user.click(editButton());
    await user.click(screen.getByTestId('assignment-confirm'));
    expect(screen.getByTestId('resource-tag-chips').getAttribute('data-refresh-key')).toBe('2');
  });

  it('通过 onManageDefinitions 打开定义管理弹窗并在关闭时刷新定义', async () => {
    const user = userEvent.setup();
    renderAgentInfo();
    await user.click(editButton());
    await user.click(screen.getByTestId('assignment-manage'));

    const mgmt = screen.getByTestId('management-modal');
    expect(mgmt.getAttribute('data-bucket-id')).toBe('10');
    expect(mgmt.getAttribute('data-bucket-name')).toBe('资源标签');
    expect(mgmt.getAttribute('data-can-manage')).toBe('true');

    await user.click(screen.getByTestId('management-close'));
    expect(screen.queryByTestId('management-modal')).toBeNull();
    expect(hoisted.refreshTagDefinitions).toHaveBeenCalledTimes(1);
  });

  it('只读态禁用编辑且无法通过 UI 进入编辑或管理', () => {
    hoisted.isReadOnly = true;
    renderAgentInfo();
    expect(editButton().disabled).toBe(true);
    fireEvent.click(editButton());
    expect(screen.queryByTestId('assignment-modal')).toBeNull();
    expect(screen.queryByTestId('management-modal')).toBeNull();
    expect(hoisted.refreshTagDefinitions).not.toHaveBeenCalled();
  });

  it('标签库/定义为空时展示空态且不产生写请求', async () => {
    hoisted.tagLibraries = [];
    hoisted.tagDefinitions = [];
    const user = userEvent.setup();
    renderAgentInfo();

    expect(within(screen.getByTestId('resource-tag-chips')).getByText('—')).toBeTruthy();

    await user.click(editButton());
    expect(screen.getByTestId('assignment-modal').getAttribute('data-definitions-count')).toBe('0');

    await user.click(screen.getByTestId('assignment-manage'));
    const mgmt = screen.getByTestId('management-modal');
    expect(mgmt.getAttribute('data-bucket-id')).toBe('0');
    expect(mgmt.getAttribute('data-bucket-name')).toBe('');
    expect(hoisted.refreshTagDefinitions).not.toHaveBeenCalled();
  });
});
