import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, renderHook } from '@testing-library/react';
import { useAgentStore } from '@/stores/agentStore';
import { Nl2AgentFlowProvider, useNl2AgentFlow } from '@/contexts/nl2AgentFlow';
import { updateAgentInfo } from '@/services/agentConfigService';
import type { Agent } from '@/types/agentConfig';

vi.mock('@/services/agentConfigService', () => ({
  updateAgentInfo: vi.fn(), searchToolConfig: vi.fn(), updateToolConfig: vi.fn(),
}));
const agent = (id: number, name: string, permission = 'EDIT') => ({
  id: String(id), name, permission, max_step: 8, provide_run_summary: false, tools: [],
} as Agent);
beforeEach(() => {
  useAgentStore.getState().reset();
  vi.mocked(updateAgentInfo).mockResolvedValue({ success: true } as any);
});
afterEach(async () => {
  cleanup();
  await act(async () => {
    useAgentStore.getState().reset();
    await useAgentStore.getState().waitForIdle();
  });
  vi.restoreAllMocks();
});
describe('UT-FE-006 real store and context isolation', () => {
  it('restores saved state after remount and replaces it when changing Agent', async () => {
    useAgentStore.getState().initialize(agent(11, 'Agent A'));
    const first = renderHook(() => useAgentStore(s => s.editedAgent?.name));
    act(() => useAgentStore.getState().updateDraft({ name: 'Saved A' }));
    await act(async () => { expect(await useAgentStore.getState().waitForIdle()).toBe(true); });
    expect(updateAgentInfo).toHaveBeenCalledWith(expect.objectContaining({ agent_id: 11, name: 'Saved A' }));
    first.unmount();
    const remounted = renderHook(() => useAgentStore(s => s.editedAgent?.name));
    expect(remounted.result.current).toBe('Saved A');
    act(() => useAgentStore.getState().initialize(agent(12, 'Agent B')));
    expect(remounted.result.current).toBe('Agent B');
    act(() => expect(useAgentStore.getState().replaceServerSnapshot(12, agent(12, 'Fresh B'))).toBe(true));
    expect(remounted.result.current).toBe('Fresh B');
  });
  it('late Agent A save cannot overwrite Agent B after switching', async () => {
    let finish!: (value: any) => void;
    vi.mocked(updateAgentInfo).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    useAgentStore.getState().initialize(agent(11, 'Agent A'));
    useAgentStore.getState().updateAgentConfig({ name: 'Delayed A' });
    useAgentStore.getState().initialize(agent(12, 'Agent B'));
    finish({ success: true });
    await useAgentStore.getState().waitForIdle();
    expect(useAgentStore.getState().editedAgent?.name).toBe('Agent B');
    expect(useAgentStore.getState().savedAgent?.name).toBe('Agent B');
    expect(useAgentStore.getState().replaceServerSnapshot(11, agent(11, 'Old A'))).toBe(false);
  });
  it('failed save rolls back and session reset clears pending writes and errors', async () => {
    vi.mocked(updateAgentInfo).mockResolvedValueOnce({ success: false, message: 'save rejected' } as any);
    useAgentStore.getState().initialize(agent(11, 'Agent A'));
    useAgentStore.getState().updateAgentConfig({ name: 'Rejected' });
    expect(await useAgentStore.getState().waitForIdle()).toBe(false);
    expect(useAgentStore.getState().editedAgent?.name).toBe('Agent A');
    expect(useAgentStore.getState().saveError).toBeTruthy();
    useAgentStore.getState().updateDraft({ name: 'Never send' });
    useAgentStore.getState().reset();
    expect(await useAgentStore.getState().waitForIdle()).toBe(true);
    expect(useAgentStore.getState()).toMatchObject({ agentId: null, editedAgent: null, savedAgent: null, saveError: null, isReadOnly: true });
    expect(updateAgentInfo).toHaveBeenCalledTimes(1);
  });
  it('readonly store never persists edits', async () => {
    useAgentStore.getState().initialize(agent(11, 'Read only', 'READ_ONLY'));
    useAgentStore.getState().updateAgentConfig({ name: 'Unauthorized' });
    expect(await useAgentStore.getState().waitForIdle()).toBe(true);
    expect(updateAgentInfo).not.toHaveBeenCalled();
    expect(useAgentStore.getState().editedAgent?.name).toBe('Read only');
  });
  it('flow reset rejects late completion from a previous session/Agent', () => {
    const hook = renderHook(() => useNl2AgentFlow(), { wrapper: Nl2AgentFlowProvider });
    act(() => hook.result.current.resetFlow(11));
    act(() => hook.result.current.markRunStarted(11));
    expect(hook.result.current.isFormLocked).toBe(true);
    const generation = hook.result.current.sessionGeneration;
    act(() => hook.result.current.resetFlow(12));
    act(() => hook.result.current.markGenerationCompleted(11));
    expect(hook.result.current).toMatchObject({ agentId: 12, phase: 'idle', isFormLocked: false });
    expect(hook.result.current.sessionGeneration).toBeGreaterThan(generation);
    act(() => hook.result.current.resetFlow(null));
    expect(hook.result.current.agentId).toBeNull();
  });
});
