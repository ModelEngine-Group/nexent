import React from 'react';
import { render, screen, waitFor, cleanup } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

import AgentConfig from '@/app/[locale]/agents/[agentId]/agent-config';

const h = vi.hoisted(() => {
  const messageError = vi.fn();
  const searchAgentInfo = vi.fn();
  const replaceServerSnapshot = vi.fn();
  const storeState: any = {
    agentId: null,
    editedAgent: null,
    serverSnapshotRevision: 0,
    flushDraft: vi.fn(),
    saveError: null,
    clearSaveError: vi.fn(),
    replaceServerSnapshot,
  };
  return {
    message: { error: messageError },
    searchAgentInfo,
    replaceServerSnapshot,
    storeState,
  };
});

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: 'zh-CN' },
  }),
}));

vi.mock('antd', async (importOriginal) => {
  const actual = (await importOriginal()) as any;
  return {
    ...actual,
    App: { ...actual.App, useApp: () => ({ message: h.message }) },
  };
});

vi.mock('@/stores/agentStore', () => {
  const useAgentStore: any = (selector?: (s: any) => any) =>
    selector ? selector(h.storeState) : h.storeState;
  useAgentStore.getState = () => h.storeState;
  return { useAgentStore };
});

vi.mock('@/services/agentConfigService', () => ({
  searchAgentInfo: h.searchAgentInfo,
}));

vi.mock('@/lib/utils', () => ({
  cn: (...args: any[]) => args.filter(Boolean).join(' '),
}));

vi.mock('@/hooks/agent/useAgentReadOnly', () => ({
  useAgentReadOnly: () => false,
}));

vi.mock('@/hooks/agent/useSaveGuard', () => ({
  useSaveGuard: () => ({ save: vi.fn().mockResolvedValue(true) }),
}));

vi.mock('@/contexts/nl2AgentFlow', () => ({
  useNl2AgentFlow: () => ({
    configFocusRequest: null,
    clearConfigFocusRequest: vi.fn(),
  }),
}));

vi.mock('@/components/ui/collapsible', () => ({
  Collapsible: ({ children }: any) => <>{children}</>,
  CollapsibleContent: ({ children }: any) => <>{children}</>,
  CollapsibleTrigger: ({ children }: any) => <>{children}</>,
}));

vi.mock('@/components/ui/tabs', () => ({
  Tabs: ({ children }: any) => <>{children}</>,
  TabsContent: ({ children }: any) => <>{children}</>,
  TabsList: ({ children }: any) => <>{children}</>,
  TabsTrigger: ({ children }: any) => <>{children}</>,
}));

vi.mock('@/app/[locale]/agents/[agentId]/components/agent-info', () => ({ default: () => null }));
vi.mock('@/app/[locale]/agents/[agentId]/components/agent-prompt', () => ({ default: () => null }));
vi.mock('@/app/[locale]/agents/[agentId]/components/agent-capability', () => ({
  AgentSkillCapability: () => null,
  AgentToolCapability: () => null,
}));
vi.mock('@/app/[locale]/agents/[agentId]/components/agent-run-policy', () => ({ default: () => null }));
vi.mock('@/app/[locale]/agents/[agentId]/components/agent-guide', () => ({ default: () => null }));
vi.mock('@/app/[locale]/agents/[agentId]/components/agent-deployment', () => ({ default: () => null }));
vi.mock('@/app/[locale]/agents/[agentId]/components/collaborative-agent', () => ({
  default: () => null,
  CollaborativeAgentActions: () => null,
}));
vi.mock('@/app/[locale]/agents/[agentId]/components/advanced/GuardrailConfigContent', () => ({
  default: () => null,
  GuardrailConfigActions: () => null,
}));
vi.mock('@/app/[locale]/agents/[agentId]/components/knowledge-base-search', () => ({
  default: () => null,
  KnowledgeBaseConfigActions: () => null,
}));
vi.mock('@/app/[locale]/agents/versions/AgentVersionPubulishModal', () => ({ default: () => null }));

const AGENT_ID = 123;

function makeDraft(overrides: Record<string, unknown> = {}) {
  return {
    name: 'test-agent',
    display_name: 'Test Agent',
    unavailable_reasons: [] as string[],
    ...overrides,
  };
}

function renderComponent() {
  return render(
    <AgentConfig
      canManualUnlock={false}
      onManualUnlock={vi.fn()}
      onToggleDebug={vi.fn()}
    />
  );
}

describe('AgentConfig 不可用原因告警与手动刷新', () => {
  beforeEach(() => {
    h.message.error.mockReset();
    h.searchAgentInfo.mockReset();
    h.replaceServerSnapshot.mockReset();
    h.storeState.agentId = AGENT_ID;
    h.storeState.editedAgent = makeDraft({
      unavailable_reasons: ['model_unavailable', 'tool_unavailable'],
    });
    h.storeState.serverSnapshotRevision = 1;
    h.storeState.flushDraft = vi.fn();
    h.storeState.saveError = null;
    h.storeState.clearSaveError = vi.fn();
  });

  afterEach(() => {
    cleanup();
  });

  it('UT-FE-AUTO-CC79D2BB8D78E346 unavailable_reasons 非空时渲染 warning 告警与刷新入口，文案包含各不可用原因', () => {
    renderComponent();

    const alert = screen.getByRole('alert');
    expect(alert.className).toContain('ant-alert-warning');
    expect(alert.querySelector('.ant-alert-icon')).not.toBeNull();

    expect(screen.getByText(/agent\.unavailableReasons\.model_unavailable/)).toBeTruthy();
    expect(screen.getByText(/agent\.unavailableReasons\.tool_unavailable/)).toBeTruthy();

    expect(screen.getByRole('button', { name: /refreshAvailability/ })).toBeTruthy();
  });

  it('点击刷新后 searchAgentInfo(agentId) 调用一次，成功时 replaceServerSnapshot(agentId, data) 调用一次', async () => {
    const user = userEvent.setup();
    const data = { id: AGENT_ID, name: 'refreshed-agent', unavailable_reasons: [] };
    h.searchAgentInfo.mockResolvedValue({ success: true, data });

    renderComponent();
    await user.click(screen.getByRole('button', { name: /refreshAvailability/ }));

    await waitFor(() => {
      expect(h.searchAgentInfo).toHaveBeenCalledTimes(1);
      expect(h.searchAgentInfo).toHaveBeenCalledWith(AGENT_ID);
      expect(h.replaceServerSnapshot).toHaveBeenCalledTimes(1);
      expect(h.replaceServerSnapshot).toHaveBeenCalledWith(AGENT_ID, data);
    });
  });

  it('刷新失败（success=false）时 replaceServerSnapshot 不被调用且 message.error 提示错误文案', async () => {
    const user = userEvent.setup();
    h.searchAgentInfo.mockResolvedValue({ success: false, message: '具体错误文案' });

    renderComponent();
    await user.click(screen.getByRole('button', { name: /refreshAvailability/ }));

    await waitFor(() => {
      expect(h.message.error).toHaveBeenCalledWith('具体错误文案');
      expect(h.replaceServerSnapshot).not.toHaveBeenCalled();
    });
  });

  it('刷新抛出异常时 replaceServerSnapshot 不被调用且 message.error 提示刷新失败文案', async () => {
    const user = userEvent.setup();
    h.searchAgentInfo.mockRejectedValue(new Error('boom'));

    renderComponent();
    await user.click(screen.getByRole('button', { name: /refreshAvailability/ }));

    await waitFor(() => {
      expect(h.message.error).toHaveBeenCalledWith('agent.config.refreshAvailabilityFailed');
      expect(h.replaceServerSnapshot).not.toHaveBeenCalled();
    });
  });

  it('刷新进行中按钮进入 loading 且 disabled，请求结束后恢复可点击', async () => {
    const user = userEvent.setup();
    const data = { id: AGENT_ID, name: 'refreshed-agent', unavailable_reasons: [] };
    let resolveSearch!: (v: any) => void;
    h.searchAgentInfo.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveSearch = resolve;
        })
    );

    renderComponent();
    await user.click(screen.getByRole('button', { name: /refreshAvailability/ }));

    await waitFor(() => {
      const loadingButton = screen.getByRole('button', {
        name: /refreshAvailability/,
      }) as HTMLButtonElement;
      expect(loadingButton.disabled).toBe(true);
      expect(loadingButton.className).toContain('ant-btn-loading');
    });

    resolveSearch({ success: true, data });
    await waitFor(() => {
      const readyButton = screen.getByRole('button', {
        name: /refreshAvailability/,
      }) as HTMLButtonElement;
      expect(readyButton.disabled).toBe(false);
    });
  });

  it('unavailable_reasons 置空后告警与刷新入口不渲染', () => {
    const view = renderComponent();

    expect(screen.getByRole('alert')).toBeTruthy();

    h.storeState.editedAgent = makeDraft({ unavailable_reasons: [] });
    view.rerender(
      <AgentConfig
        canManualUnlock={false}
        onManualUnlock={vi.fn()}
        onToggleDebug={vi.fn()}
      />
    );

    expect(screen.queryByRole('alert')).toBeNull();
    expect(screen.queryByRole('button', { name: /refreshAvailability/ })).toBeNull();
  });
});
