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

describe('latest selectable-model fallback contract', () => {
  it('UT-FE-AUTO-ED44D96A53903DD0 keeps an available selection and falls back when it becomes unavailable', () => {
    const agent = baseAgent({
      model_ids: [1, 2, 3],
      model_names: ['模型A', '模型B', '模型C'],
    });
    modelList.models = [m1, mAvailable(2, 'm2'), m3];
    const { rerender } = renderThread(agent);
    composerProps.props.onModelChange('2');
    rerender(<Thread agent={agent} chatMode='planning' onChatModeChange={noop} />);
    expect(composerProps.props.selectedModelId).toBe('2');

    modelList.models = [m1, mUnavailable(2, 'm2'), m3];
    rerender(<Thread agent={agent} chatMode='planning' onChatModeChange={noop} />);
    expect(composerProps.props.models.map((model: any) => model.id)).toEqual(['1', '3']);
    expect(composerProps.props.selectedModelId).toBe('1');
  });
});
