import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryManager } from '@/app/[locale]/memory/MemoryManager';
import { LongTermMemoryPanel } from '@/app/[locale]/memory/LongTermMemoryPanel';

const fx = vi.hoisted(() => ({
  t: (key: string) => key, allowed: true,
  message: { error: vi.fn(), success: vi.fn(), warning: vi.fn() },
  modal: { confirm: vi.fn() },
  config: vi.fn(), switch: vi.fn(), active: vi.fn(), versions: vi.fn(),
  version: vi.fn(), save: vi.fn(), activate: vi.fn(), request: vi.fn(), records: vi.fn(), sync: vi.fn(),
}));
vi.mock('react-i18next', async original => ({
  ...await original<typeof import('react-i18next')>(),
  useTranslation: () => ({ t: fx.t, i18n: { resolvedLanguage: 'en' } }),
}));
vi.mock('antd', async original => {
  const actual = await original<typeof import('antd')>();
  return { ...actual, App: { ...actual.App, useApp: () => ({ message: fx.message, modal: fx.modal }) } };
});
vi.mock('@/components/permission/Can', () => ({
  Can: ({ children }: { children: React.ReactNode }) => fx.allowed ? children : null,
}));
vi.mock('@/components/common/markdownRenderer', () => ({
  MarkdownRenderer: ({ content }: { content: string }) => <div data-testid="memory-content">{content}</div>,
}));
vi.mock('@/app/[locale]/memory/DreamingConfigCards', () => ({ DreamingConfigCards: () => null }));
vi.mock('@/app/[locale]/memory/ProviderConfigCard', () => ({ ProviderConfigCard: () => null }));
vi.mock('@/services/api', () => ({
  fetchWithErrorHandling: fx.request,
  API_ENDPOINTS: { memory: { config: { load: '/fixture/memory/config', set: '/fixture/memory/config/set' } } },
}));
vi.mock('@/services/agentConfigService', () => ({ fetchAllAgents: vi.fn() }));
vi.mock('@/lib/auth', () => ({ getAuthHeaders: () => ({ 'Content-Type': 'application/json' }) }));
vi.mock('@/services/memoryService', async original => ({
  ...await original<typeof import('@/services/memoryService')>(),
  loadMemoryConfig: fx.config, setMemorySwitch: fx.switch,
  fetchLongTermActive: fx.active, fetchLongTermVersions: fx.versions,
  fetchLongTermVersion: fx.version, saveLongTermVersion: fx.save,
  activateLongTermVersion: fx.activate,
}));
vi.mock('@/services/memoryRecordService', () => ({
  listMemoryRecords: fx.records,
  synchronizeMemoryRecordStatuses: fx.sync,
  createMemoryRecord: vi.fn(), deleteMemoryRecord: vi.fn(), updateMemoryRecord: vi.fn(),
}));
// IDs belong only to these in-memory service fixtures, never a database.
const active = { version_id: 21, version_no: 2, is_active: true, content: 'Current memory',
  source: 'manual', authored_at: '2026-01-01T00:00:00Z', fallback_details: {} };
const history = { ...active, version_id: 20, version_no: 1, is_active: false, content: 'Historical memory' };
beforeEach(() => {
  const computed = window.getComputedStyle.bind(window);
  vi.spyOn(window, 'getComputedStyle').mockImplementation(element => computed(element));
  fx.records.mockResolvedValue([]);
  fx.sync.mockResolvedValue({ records: [], failedCount: 0 });
  fx.allowed = true;
  fx.config.mockResolvedValue({ memoryEnabled: true, shareOption: 'always',
    disableAgentIds: [], disableUserAgentIds: [], externalProviderTopK: 20 });
  fx.switch.mockResolvedValue(true);
  fx.active.mockResolvedValue({ empty: false, version: active });
  fx.versions.mockResolvedValue({ items: [active, history], count: 2 });
  fx.version.mockResolvedValue(history);
  fx.save.mockResolvedValue(active);
  fx.activate.mockResolvedValue(history);
});
afterEach(async () => {
  cleanup();
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 120)); });
  vi.restoreAllMocks();
});

describe('UT-FE-033 actual memory configuration and version controls', () => {
  it('maps disabled scopes and provider settings from the actual service response', async () => {
    const actual = await vi.importActual<typeof import('@/services/memoryService')>('@/services/memoryService');
    fx.request.mockResolvedValueOnce({ json: async () => ({
      MEMORY_SWITCH: 'N', MEMORY_AGENT_SHARE: 'ask',
      DISABLE_AGENT_ID: ['fixture-agent'], DISABLE_USERAGENT_ID: ['fixture-user-agent'],
      EXTERNAL_PROVIDER_TOP_K: '7',
    }) });
    expect(await actual.loadMemoryConfig()).toEqual({ memoryEnabled: false, shareOption: 'ask',
      disableAgentIds: ['fixture-agent'], disableUserAgentIds: ['fixture-user-agent'], externalProviderTopK: 7 });
    expect(fx.request).toHaveBeenCalledWith('/fixture/memory/config', expect.objectContaining({ method: 'GET' }));
  });
  it('switch persists the requested value and subscription is removed on unmount', async () => {
    const removed = vi.spyOn(window, 'removeEventListener');
    const view = render(<MemoryManager />);
    const control = await screen.findByRole('switch');
    await userEvent.click(control);
    await waitFor(() => expect(fx.switch).toHaveBeenCalledWith(false));
    expect(control).toHaveAttribute('aria-checked', 'false');
    view.unmount();
    expect(removed).toHaveBeenCalledWith('memorySwitchChanged', expect.any(Function));
  });
  it('failed switch save rolls the UI back and reports an error', async () => {
    fx.switch.mockResolvedValueOnce(false);
    render(<MemoryManager />);
    await userEvent.click(await screen.findByRole('switch'));
    await waitFor(() => expect(fx.message.error).toHaveBeenCalled());
    expect(screen.getByRole('switch')).toHaveAttribute('aria-checked', 'true');
  });
  it('selects a historical version and activates it only after confirmation', async () => {
    render(<LongTermMemoryPanel scope="user" />);
    await screen.findByText('Current memory');
    fireEvent.mouseDown(screen.getByRole('combobox'));
    await userEvent.click(await screen.findByText(/^V1 ·/, { selector: '.ant-select-item-option-content' }));
    await screen.findByText('Historical memory');
    expect(fx.version).toHaveBeenCalledWith('user', 20);
    await userEvent.click(screen.getByRole('button', { name: 'memory.longTerm.activate' }));
    expect(fx.activate).not.toHaveBeenCalled();
    const dialog = await screen.findByRole('dialog');
    await userEvent.click(within(dialog).getByRole('button', { name: 'common.confirm' }));
    await waitFor(() => expect(fx.activate).toHaveBeenCalledWith('user', 20, 21));
    expect(fx.message.success).toHaveBeenCalledWith('memory.longTerm.activated');
  });
  it('concurrent save preserves the draft and expected active version', async () => {
    fx.save.mockRejectedValueOnce(new Error('version conflict'));
    render(<LongTermMemoryPanel scope="user" />);
    await screen.findByText('Current memory');
    await userEvent.click(screen.getByRole('button', { name: 'memory.longTerm.edit' }));
    fireEvent.change(screen.getByRole('textbox', { name: 'memory.longTerm.editorLabel' }),
      { target: { value: 'Uncommitted draft' } });
    await userEvent.click(screen.getByRole('button', { name: 'memory.longTerm.save' }));
    await waitFor(() => expect(fx.message.error).toHaveBeenCalledWith('memory.longTerm.concurrentError'));
    expect(fx.save).toHaveBeenCalledWith('user', 'Uncommitted draft', 21);
    expect(screen.getByRole('textbox')).toHaveValue('Uncommitted draft');
    expect(fx.message.success).not.toHaveBeenCalled();
  });
  it('failed load exposes retry and successful retry restores the active version', async () => {
    fx.active.mockRejectedValueOnce(new Error('service unavailable'));
    render(<LongTermMemoryPanel scope="user" />);
    await userEvent.click(await screen.findByRole('button', { name: 'memory.longTerm.retry' }));
    await screen.findByText('Current memory');
    expect(fx.active).toHaveBeenCalledTimes(2);
    expect(fx.message.error).toHaveBeenCalledWith('memory.longTerm.loadFailed');
  });
  it('tenant modification is permission guarded and user event listeners are cleaned', async () => {
    fx.allowed = false;
    const view = render(<LongTermMemoryPanel scope="tenant" />);
    await screen.findByText('Current memory');
    expect(screen.queryByRole('button', { name: 'memory.longTerm.edit' })).toBeNull();
    view.unmount();
    const remove = vi.spyOn(window, 'removeEventListener');
    const user = render(<LongTermMemoryPanel scope="user" />);
    await screen.findByText('Current memory');
    expect(screen.getByRole('button', { name: 'memory.longTerm.edit' })).toBeTruthy();
    user.unmount();
    expect(remove).toHaveBeenCalledWith('user-long-term-memory-updated', expect.any(Function));
    expect(remove).toHaveBeenCalledWith('beforeunload', expect.any(Function));
  });
});
