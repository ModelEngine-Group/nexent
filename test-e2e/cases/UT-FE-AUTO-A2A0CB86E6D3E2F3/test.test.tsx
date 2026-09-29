import * as React from 'react';
import { describe, it, expect, vi, beforeEach, beforeAll, afterEach } from 'vitest';
import { render, screen, act, cleanup } from '@testing-library/react';
import { Form } from 'antd';
import AgentPrompt from '@/app/[locale]/agents/components/agent-prompt';
import { reorderModelIds } from '@/lib/agent/modelPriority';

type ModelFixture = {
  id: number;
  name: string;
  displayName: string;
  type: string;
  connect_status: string;
};

const MODELS: ModelFixture[] = [
  { id: 1, name: 'model-a', displayName: 'Model A', type: 'llm', connect_status: 'available' },
  { id: 2, name: 'model-b', displayName: 'Model B', type: 'llm', connect_status: 'available' },
  { id: 3, name: 'model-c', displayName: 'Model C', type: 'llm', connect_status: 'available' },
];

const nameById = (id: number): string =>
  MODELS.find((m) => m.id === id)?.displayName ?? '';

const store = vi.hoisted(() => ({
  state: {
    agentId: 1 as number | null,
    editedAgent: null as any,
    defaultLlmConfig: null as any,
    updateDraft: vi.fn(),
    flushDraft: vi.fn(),
    updateAgentConfig: vi.fn(),
  },
}));

const modelList = vi.hoisted(() => ({
  availableLlmModels: [] as ModelFixture[],
  isSuccess: true,
}));

const authCtx = vi.hoisted(() => ({
  role: 'ADMIN' as string,
}));

const deploymentCtx = vi.hoisted(() => ({
  isSpeedMode: false,
}));

const dnd = vi.hoisted(() => ({
  onDragEnd: null as null | ((event: any) => void),
}));

vi.mock('@/stores/agentStore', () => ({
  useAgentStore: (selector: (s: any) => any) => selector(store.state),
}));

vi.mock('@/hooks/model/useModelList', () => ({
  useModelList: () => ({
    availableLlmModels: modelList.availableLlmModels,
    isSuccess: modelList.isSuccess,
  }),
}));

vi.mock('@/hooks/model/useInferenceFieldSpecs', () => ({
  useInferenceFieldSpecs: () => ({ data: [], isLoading: false }),
}));

vi.mock('@/components/providers/AuthorizationProvider', () => ({
  useAuthorizationContext: () => ({ user: { role: authCtx.role } }),
  AuthorizationProvider: ({ children }: any) => <>{children}</>,
}));

vi.mock('@/components/providers/deploymentProvider', () => ({
  useDeployment: () => ({ isSpeedMode: deploymentCtx.isSpeedMode }),
  DeploymentProvider: ({ children }: any) => <>{children}</>,
}));

vi.mock('@/contexts/nl2AgentFlow', () => ({
  useNl2AgentFlow: () => ({ configFocusRequest: null }),
}));

vi.mock('@/components/common/ExpandEditModal', () => ({
  default: () => null,
}));

vi.mock('@/components/ui/tabs', () => ({
  Tabs: ({ children }: any) => <div>{children}</div>,
  TabsList: ({ children }: any) => <div>{children}</div>,
  TabsTrigger: ({ children }: any) => <div>{children}</div>,
  TabsContent: ({ children }: any) => <div>{children}</div>,
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: 'en' } }),
}));

vi.mock('@/lib/agent/modelPriority', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/agent/modelPriority')>();
  return {
    ...actual,
    reorderModelIds: vi.fn(actual.reorderModelIds),
    resolveModelSelection: vi.fn(actual.resolveModelSelection),
  };
});

vi.mock('@dnd-kit/core', async (importOriginal) => {
  const actual = await importOriginal<any>();
  return {
    ...actual,
    DndContext: ({ children, onDragEnd }: any) => {
      dnd.onDragEnd = onDragEnd;
      return <>{children}</>;
    },
  };
});

vi.mock('@dnd-kit/sortable', async (importOriginal) => {
  const actual = await importOriginal<any>();
  return {
    ...actual,
    SortableContext: ({ children }: any) => <>{children}</>,
    useSortable: () => ({
      attributes: {},
      isDragging: false,
      listeners: {},
      setNodeRef: () => {},
      transform: null,
      transition: undefined,
    }),
  };
});

vi.mock('antd', async (importOriginal) => {
  const actual = await importOriginal<any>();
  return {
    ...actual,
    Popover: ({ content, children }: any) => (
      <>
        {children}
        {content}
      </>
    ),
    Tooltip: ({ children }: any) => <>{children}</>,
  };
});

function setAgent(opts: { model_ids?: number[]; defaultLlmConfigId?: number | null }) {
  const modelIds = opts.model_ids ?? [1, 2, 3];
  store.state.editedAgent = {
    model_ids: modelIds,
    model: nameById(modelIds[0]),
    model_names: modelIds.map((id) => nameById(id)),
    duty_prompt: '',
    constraint_prompt: '',
    few_shots_prompt: '',
  };
  if (opts.defaultLlmConfigId === null) {
    store.state.defaultLlmConfig = { id: null, name: '', displayName: '' };
  } else {
    const id = opts.defaultLlmConfigId ?? 1;
    store.state.defaultLlmConfig = { id, name: 'model-' + id, displayName: nameById(id) };
  }
}

let capturedForm: any = null;

function renderAgentPrompt(initialModelIds?: number[]) {
  const ids = initialModelIds ?? store.state.editedAgent.model_ids;
  function Wrapper({ children }: { children: React.ReactNode }) {
    const [form] = Form.useForm();
    capturedForm = form;
    return (
      <Form form={form} initialValues={{ model_ids: ids }}>
        {children}
      </Form>
    );
  }
  return render(<AgentPrompt />, { wrapper: Wrapper });
}

beforeAll(() => {
  if (typeof window !== 'undefined' && !window.matchMedia) {
    window.matchMedia = ((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    })) as any;
  }
  if (typeof window !== 'undefined' && !(window as any).ResizeObserver) {
    (window as any).ResizeObserver = class {
      observe() {}
      unobserve() {}
      disconnect() {}
    };
  }
});

beforeEach(() => {
  vi.clearAllMocks();
  modelList.availableLlmModels = [...MODELS];
  modelList.isSuccess = true;
  authCtx.role = 'ADMIN';
  deploymentCtx.isSpeedMode = false;
  dnd.onDragEnd = null;
  store.state.agentId = 1;
  store.state.updateDraft = vi.fn();
  store.state.flushDraft = vi.fn();
  store.state.updateAgentConfig = vi.fn((patch: any) => {
    store.state.editedAgent = { ...store.state.editedAgent, ...patch };
  });
  setAgent({ model_ids: [1, 2, 3] });
});

afterEach(() => cleanup());

describe('AgentPrompt 多模型优先级（）', () => {
  it('UT-FE-AUTO-A2A0CB86E6D3E2F3 首次渲染回显 model_ids 顺序，首位为主模型，排序入口启用', () => {
    const { container } = renderAgentPrompt([1, 2, 3]);

    const items = screen.getAllByRole('listitem');
    expect(items).toHaveLength(3);
    expect(items[0].textContent).toContain('Model A');
    expect(items[0].textContent).toContain('agent.field.primaryModel');
    expect(items[1].textContent).toContain('Model B');
    expect(items[1].textContent).not.toContain('agent.field.primaryModel');
    expect(items[2].textContent).toContain('Model C');

    const selectionItems = Array.from(
      container.querySelectorAll('.ant-select-selection-item')
    );
    expect(selectionItems.map((el) => el.textContent?.trim())).toEqual([
      'Model A',
      'Model B',
      'Model C',
    ]);

    const sortButton = screen.getByRole('button', {
      name: 'agent.field.adjustModelPriority',
    }) as HTMLButtonElement;
    expect(sortButton.disabled).toBe(false);
  });

  it('model_ids 为空时回退 defaultLlmConfig.id，且排序入口 disabled', () => {
    setAgent({ model_ids: [], defaultLlmConfigId: 2 });
    const { container } = renderAgentPrompt([2]);

    const selectionItems = Array.from(
      container.querySelectorAll('.ant-select-selection-item')
    );
    expect(selectionItems.map((el) => el.textContent?.trim())).toEqual(['Model B']);
    expect(screen.queryAllByRole('listitem')).toHaveLength(0);

    const sortButton = screen.getByRole('button', {
      name: 'agent.field.adjustModelPriority',
    }) as HTMLButtonElement;
    expect(sortButton.disabled).toBe(true);
  });

  it('拖拽/键盘重排调用 reorderModelIds 并提交新优先级与主模型语义', () => {
    renderAgentPrompt([1, 2, 3]);
    expect(dnd.onDragEnd).toBeTruthy();

    act(() => {
      dnd.onDragEnd!({ active: { id: 1 }, over: { id: 3 } });
    });

    expect(reorderModelIds).toHaveBeenCalledWith([1, 2, 3], 1, 3);
    expect(capturedForm.getFieldValue('model_ids')).toEqual([2, 3, 1]);
    expect(store.state.updateAgentConfig).toHaveBeenCalledWith({
      model_ids: [2, 3, 1],
      model: 'Model B',
      model_names: ['Model B', 'Model C', 'Model A'],
    });
    expect(store.state.editedAgent.model_ids).toEqual([2, 3, 1]);
    expect(store.state.editedAgent.model).toEqual('Model B');
    expect(store.state.editedAgent.model_names).toEqual(['Model B', 'Model C', 'Model A']);
  });

  it('只读/无权限时多选与排序均禁用且无拖拽手柄', () => {
    authCtx.role = 'USER';
    deploymentCtx.isSpeedMode = false;
    const { container } = renderAgentPrompt([1, 2, 3]);

    expect(container.querySelector('.ant-select-disabled')).toBeTruthy();

    const sortButton = screen.getByRole('button', {
      name: 'agent.field.adjustModelPriority',
    }) as HTMLButtonElement;
    expect(sortButton.disabled).toBe(true);

    expect(screen.queryAllByRole('listitem')).toHaveLength(0);
    expect(screen.queryByRole('button', { name: 'agent.field.reorderModel' })).toBeNull();
  });

  it('模型数少于 2 时排序入口 disabled', () => {
    setAgent({ model_ids: [1] });
    renderAgentPrompt([1]);

    const sortButton = screen.getByRole('button', {
      name: 'agent.field.adjustModelPriority',
    }) as HTMLButtonElement;
    expect(sortButton.disabled).toBe(true);
    expect(screen.queryAllByRole('listitem')).toHaveLength(0);
  });

  it('刷新后按可用模型过滤 model_ids 并同步 model/model_names', () => {
    modelList.availableLlmModels = [MODELS[0], MODELS[1]];
    setAgent({ model_ids: [1, 2, 99] });
    renderAgentPrompt([1, 2, 99]);

    expect(store.state.editedAgent.model_ids).toEqual([1, 2]);
    expect(store.state.editedAgent.model).toEqual('Model A');
    expect(store.state.editedAgent.model_names).toEqual(['Model A', 'Model B']);
    expect(store.state.updateAgentConfig).toHaveBeenCalledWith({
      model_ids: [1, 2],
      model: 'Model A',
      model_names: ['Model A', 'Model B'],
    });
  });
});
