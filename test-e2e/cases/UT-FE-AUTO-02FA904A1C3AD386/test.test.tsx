// @ts-nocheck
// @vitest-environment jsdom
import { render } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

import { Thread } from '@/app/[locale]/newchat/assistant-ui/thread';
import { TooltipProvider } from '@/components/ui/tooltip';

const composerProps = vi.hoisted(() => ({ props: null as any }));
const modelList = vi.hoisted(() => ({
  models: [] as Array<{
    id: number;
    name: string;
    displayName: string;
    connect_status: string;
  }>,
}));
const auiState = vi.hoisted(() => ({
  thread: { messages: [], isRunning: false },
  threads: { mainThreadId: null, threadItems: [] },
  message: { content: [], metadata: {}, id: undefined, index: 0, status: { type: 'complete' } },
  composer: { text: '', dictation: false },
}));

vi.mock('react-i18next', () => ({
  initReactI18next: { type: '3rdParty', init: () => undefined },
  useTranslation: () => ({
    t: (key: string, opts?: any) =>
      opts && typeof opts.defaultValue === 'string' ? opts.defaultValue : key,
    i18n: { resolvedLanguage: 'zh', language: 'zh' },
  }),
}));

vi.mock('antd', () => ({
  Typography: new Proxy({}, { get: () => (props: any) => props.children }),
  message: {
    error: () => {},
    success: () => {},
    warning: () => {},
    info: () => {},
    loading: () => {},
  },
}));

vi.mock('react-shiki', () => ({
  useShikiHighlighter: () => ({
    isLoading: false,
    error: null,
    html: '',
  }),
}));

vi.mock('@assistant-ui/react', () => {
  const passthrough = (props: any) =>
    typeof props.children === 'function' ? props.children({}) : props.children;
  const primitives = new Proxy({}, { get: () => passthrough });
  return {
    ThreadPrimitive: primitives,
    MessagePrimitive: primitives,
    ActionBarPrimitive: primitives,
    ActionBarMorePrimitive: primitives,
    ErrorPrimitive: primitives,
    AuiIf: passthrough,
    groupPartByType: () => [],
    unstable_defaultDirectiveFormatter: () => null,
    useAui: () => ({
      composer: () => ({ setText: () => {} }),
      modelContext: () => ({ register: () => {} }),
    }),
    useAuiState: (selector: any) => selector(auiState),
  };
});

vi.mock('@/hooks/model/useModelList', () => ({
  useModelList: () => ({ models: modelList.models }),
}));

vi.mock('@/app/[locale]/newchat/assistant-ui/composer', () => ({
  Composer: (props: any) => {
    composerProps.props = props;
    return null;
  },
}));

vi.mock('@/app/[locale]/newchat/ui/sources-panel', () => ({
  SourcesPanel: () => null,
}));

// These cases exercise Thread model selection, not the Markdown runtime.
vi.mock('@/app/[locale]/newchat/ui/markdown-text', () => ({
  MarkdownText: () => null,
}));

vi.mock('@assistant-ui/react-markdown', () => ({
  MarkdownTextPrimitive: () => null,
  unstable_memoizeMarkdownComponents: (components: any) => components,
  useIsMarkdownCodeBlock: () => false,
}));

vi.mock('@/app/[locale]/newchat/ui/shiki-highlighter', () => ({
  SyntaxHighlighter: () => null,
}));

const mAvailable = (id: number, name: string) => ({
  id,
  name,
  displayName: name,
  connect_status: 'available',
});
const mUnavailable = (id: number, name: string) => ({
  id,
  name,
  displayName: name,
  connect_status: 'unavailable',
});

const m1 = mAvailable(1, 'm1');
const m2 = mUnavailable(2, 'm2');
const m3 = mAvailable(3, 'm3');

const baseAgent = (overrides: Record<string, unknown> = {}) => ({
  id: 'agent-1',
  agent_id: 1,
  name: 'agent-1',
  display_name: 'Agent 1',
  description: 'test',
  ...overrides,
});

const noop = () => {};

function renderThread(agent: any, extra: Record<string, unknown> = {}) {
  const result = render(
    <TooltipProvider>
      <Thread agent={agent} chatMode='planning' onChatModeChange={noop} {...extra} />
    </TooltipProvider>
  );
  const rawRerender = result.rerender;
  result.rerender = (ui: React.ReactNode) =>
    rawRerender(<TooltipProvider>{ui}</TooltipProvider>);
  return result;
}

describe(' 线程模型选择器', () => {
  beforeEach(() => {
    composerProps.props = null;
    modelList.models = [m1, m2, m3];
  });

  it('UT-FE-AUTO-02FA904A1C3AD386 派生模型列表仅保留 connect_status 为 available 的模型', () => {
    const agent = baseAgent({
      model_ids: [1, 2, 3],
      model_names: ['模型A', '模型B', '模型C'],
    });
    renderThread(agent);
    const models = composerProps.props.models;
    expect(models.map((m: any) => m.id)).toEqual(['1', '3']);
    expect(models.map((m: any) => m.name)).toEqual(['模型A', '模型C']);
    expect(models.some((m: any) => m.id === '2')).toBe(false);
  });

  it('agent 配置模型全部不可用时派生列表为空，选中态回退为 undefined', () => {
    modelList.models = [
      mUnavailable(1, 'm1'),
      mUnavailable(2, 'm2'),
      mUnavailable(3, 'm3'),
    ];
    const agent = baseAgent({
      model_ids: [1, 2, 3],
      model_names: ['模型A', '模型B', '模型C'],
    });
    renderThread(agent);
    expect(composerProps.props.models).toEqual([]);
    expect(composerProps.props.selectedModelId).toBeUndefined();
  });

  it('单模型回退：model_name 对应模型可用时返回单选项，不可用时返回空数组', () => {
    modelList.models = [mAvailable(1, 'm1')];
    const agent = baseAgent({ model_name: 'm1' });
    const { rerender } = renderThread(agent);
    // model_name resolves the resource; selection uses its canonical ID.
    expect(composerProps.props.models.map((m: any) => m.id)).toEqual(['1']);
    expect(composerProps.props.selectedModelId).toBe('1');

    modelList.models = [mUnavailable(1, 'm1')];
    rerender(<Thread agent={agent} chatMode='planning' onChatModeChange={noop} />);
    expect(composerProps.props.models).toEqual([]);
  });

  it('不可用模型不可被选中：handleModelChange 不触发回调且不更新本地选中态', () => {
    const agent = baseAgent({
      model_ids: [1, 2, 3],
      model_names: ['模型A', '模型B', '模型C'],
    });

    const onModelChange = vi.fn();
    const { rerender } = renderThread(agent, {
      selectedModelId: '1',
      onModelChange,
    });
    const controlledHandler = composerProps.props.onModelChange;
    controlledHandler('2');
    expect(onModelChange).not.toHaveBeenCalled();

    rerender(<Thread agent={agent} chatMode='planning' onChatModeChange={noop} />);
    const uncontrolledHandler = composerProps.props.onModelChange;
    uncontrolledHandler('2');
    expect(composerProps.props.selectedModelId).toBe('1');

    uncontrolledHandler('3');
    rerender(<Thread agent={agent} chatMode='planning' onChatModeChange={noop} />);
    expect(composerProps.props.selectedModelId).toBe('3');
  });

  it('会话切换后本地选中态在新模型集合外时回退到首个可用模型', () => {
    const agentA = baseAgent({
      id: 'agent-a',
      agent_id: 1,
      model_ids: [1, 2, 3],
      model_names: ['模型A', '模型B', '模型C'],
    });
    const { rerender } = renderThread(agentA);
    composerProps.props.onModelChange('3');
    rerender(<Thread agent={agentA} chatMode='planning' onChatModeChange={noop} />);
    expect(composerProps.props.selectedModelId).toBe('3');

    modelList.models = [mAvailable(10, 'm10'), mAvailable(11, 'm11')];
    const agentB = baseAgent({
      id: 'agent-b',
      agent_id: 2,
      model_ids: [10, 11],
      model_names: ['模型X', '模型Y'],
    });
    rerender(<Thread agent={agentB} chatMode='planning' onChatModeChange={noop} />);
    expect(composerProps.props.selectedModelId).toBe('10');
    expect(composerProps.props.selectedModelId).not.toBe('3');
  });

  it('测试过程无未处理异常，且不输出 API Key/Token/Password/模型密钥', () => {
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const logSpy = vi.spyOn(console, 'log').mockImplementation(() => {});
    const agent = baseAgent({
      model_ids: [1, 2, 3],
      model_names: ['模型A', '模型B', '模型C'],
    });
    expect(() => renderThread(agent)).not.toThrow();
    const output = [
      ...errorSpy.mock.calls,
      ...warnSpy.mock.calls,
      ...logSpy.mock.calls,
    ]
      .flat()
      .map(String)
      .join(' ');
    errorSpy.mockRestore();
    warnSpy.mockRestore();
    logSpy.mockRestore();
    expect(output).not.toMatch(/sk-[A-Za-z0-9]|api[_-]?key|access[_-]?token|password|secret/i);
  });
});
