import React from 'react';
import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { MemoryEmbeddingMonitor } from '@/components/memory/MemoryEmbeddingMonitor';
import {
  loadMemoryConfig,
  loadMemoryEmbeddingStatus,
  setMemorySwitch,
  subscribeMemorySwitch,
} from '@/services/memoryService';
import { useAuthorizationContext } from '@/components/providers/AuthorizationProvider';
import { useDeployment } from '@/components/providers/deploymentProvider';
import { useParams, usePathname, useRouter } from 'next/navigation';
import { canManageModels, getEffectiveRoutePath } from '@/lib/auth';
import log from '@/lib/logger';

vi.mock('@/services/memoryService', () => ({
  loadMemoryConfig: vi.fn(),
  loadMemoryEmbeddingStatus: vi.fn(),
  setMemorySwitch: vi.fn(),
  subscribeMemorySwitch: vi.fn(),
}));

vi.mock('@/components/providers/AuthorizationProvider', () => ({
  useAuthorizationContext: vi.fn(),
}));

vi.mock('@/components/providers/deploymentProvider', () => ({
  useDeployment: vi.fn(),
}));

vi.mock('next/navigation', () => ({
  useParams: vi.fn(),
  usePathname: vi.fn(),
  useRouter: vi.fn(),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock('@/lib/auth', () => ({
  canManageModels: vi.fn(),
  getEffectiveRoutePath: vi.fn(),
}));

vi.mock('@/lib/logger', () => ({
  __esModule: true,
  default: { error: vi.fn() },
}));

const mockMessage = { error: vi.fn() };
vi.mock('antd', () => {
  const React = require('react');
  return {
    App: {
      useApp: () => ({ message: mockMessage }),
    },
    Modal: ({ open, title, children, footer }: any) =>
      open
        ? React.createElement(
            'div',
            { role: 'dialog' },
            React.createElement('div', { className: 'ant-modal-title' }, title),
            React.createElement('div', null, children),
            React.createElement('div', null, footer)
          )
        : null,
    Button: ({ children, onClick, loading, disabled }: any) =>
      React.createElement(
        'button',
        { type: 'button', onClick, disabled: !!loading || !!disabled },
        children
      ),
  };
});

const TITLE = 'embedding.memoryUnavailableWarningModal.title';
const CONTENT = 'embedding.memoryUnavailableWarningModal.content';
const DISABLE = 'embedding.memoryUnavailableWarningModal.disable';
const CONFIGURE = 'embedding.chatMemoryWarningModal.ok_config';
const TIP = 'embedding.chatMemoryWarningModal.tip';

const mockPush = vi.fn();
let mockUnsubscribe: ReturnType<typeof vi.fn>;
let memorySwitchListener: ((enabled: boolean) => void) | undefined;

interface SetupOptions {
  isAuthorized?: boolean;
  role?: string;
  isSpeedMode?: boolean;
  pathname?: string;
  canConfigure?: boolean;
  memoryEnabled?: boolean;
  configured?: boolean;
}

function setup(options: SetupOptions = {}) {
  const {
    isAuthorized = true,
    role = 'ADMIN',
    isSpeedMode = false,
    pathname = '/newchat',
    canConfigure = true,
    memoryEnabled = true,
    configured = false,
  } = options;

  vi.mocked(useAuthorizationContext).mockReturnValue({
    isAuthorized,
    user: { role, id: 'u1', tenantId: 't1' },
  } as never);
  vi.mocked(useDeployment).mockReturnValue({ isSpeedMode } as never);
  vi.mocked(useParams).mockReturnValue({ locale: 'en' } as never);
  vi.mocked(usePathname).mockReturnValue(pathname);
  vi.mocked(useRouter).mockReturnValue({ push: mockPush } as never);
  vi.mocked(getEffectiveRoutePath).mockImplementation((p: string) => p);
  vi.mocked(canManageModels).mockReturnValue(canConfigure);
  vi.mocked(loadMemoryConfig).mockResolvedValue({ memoryEnabled });
  vi.mocked(loadMemoryEmbeddingStatus).mockResolvedValue({ configured });
  vi.mocked(setMemorySwitch).mockResolvedValue(true);
}

beforeEach(() => {
  vi.clearAllMocks();
  mockPush.mockReset();
  mockUnsubscribe = vi.fn();
  memorySwitchListener = undefined;
  vi.mocked(subscribeMemorySwitch).mockImplementation((listener) => {
    memorySwitchListener = listener;
    return mockUnsubscribe;
  });
  setup();
});

describe('MemoryEmbeddingMonitor', () => {
  it('UT-FE-AUTO-0440200269363B14 keeps the modal closed and skips the check when not authorized', async () => {
    setup({ isAuthorized: false });
    render(<MemoryEmbeddingMonitor />);
    expect(screen.queryByText(TITLE)).not.toBeInTheDocument();
    await waitFor(() => {
      expect(loadMemoryConfig).not.toHaveBeenCalled();
      expect(loadMemoryEmbeddingStatus).not.toHaveBeenCalled();
    });
  });

  it('opens the modal on a monitored path when memory is enabled and embedding is not configured', async () => {
    setup({ pathname: '/newchat', memoryEnabled: true, configured: false });
    render(<MemoryEmbeddingMonitor />);
    expect(await screen.findByText(TITLE)).toBeInTheDocument();
    expect(screen.getByText(CONTENT)).toBeInTheDocument();
    expect(loadMemoryConfig).toHaveBeenCalledTimes(1);
    expect(loadMemoryEmbeddingStatus).toHaveBeenCalledTimes(1);
  });

  it('keeps the modal closed when memory is disabled', async () => {
    setup({ memoryEnabled: false });
    render(<MemoryEmbeddingMonitor />);
    await waitFor(() => expect(loadMemoryConfig).toHaveBeenCalled());
    expect(loadMemoryEmbeddingStatus).not.toHaveBeenCalled();
    expect(screen.queryByText(TITLE)).not.toBeInTheDocument();
  });

  it('keeps the modal closed when embedding is already configured', async () => {
    setup({ configured: true });
    render(<MemoryEmbeddingMonitor />);
    await waitFor(() => expect(loadMemoryEmbeddingStatus).toHaveBeenCalled());
    expect(screen.queryByText(TITLE)).not.toBeInTheDocument();
  });

  it('keeps the modal closed on non-monitored paths', async () => {
    setup({ pathname: '/settings' });
    render(<MemoryEmbeddingMonitor />);
    await waitFor(() => expect(loadMemoryConfig).not.toHaveBeenCalled());
    expect(screen.queryByText(TITLE)).not.toBeInTheDocument();
  });

  it('closes the modal when the memory switch turns off', async () => {
    setup();
    render(<MemoryEmbeddingMonitor />);
    await screen.findByText(TITLE);
    vi.mocked(loadMemoryConfig).mockResolvedValue({ memoryEnabled: false });
    act(() => {
      memorySwitchListener?.(false);
    });
    await waitFor(() => expect(loadMemoryConfig).toHaveBeenCalledTimes(2));
    expect(screen.queryByText(TITLE)).not.toBeInTheDocument();
  });

  it('re-checks the configuration when the memory switch turns on', async () => {
    setup();
    render(<MemoryEmbeddingMonitor />);
    await screen.findByText(TITLE);
    vi.mocked(loadMemoryConfig).mockClear();
    vi.mocked(loadMemoryEmbeddingStatus).mockClear();
    act(() => {
      memorySwitchListener?.(true);
    });
    await waitFor(() => expect(loadMemoryConfig).toHaveBeenCalled());
    await waitFor(() => expect(loadMemoryEmbeddingStatus).toHaveBeenCalled());
  });

  it('re-checks the configuration when embeddingModelChanged is dispatched', async () => {
    setup();
    render(<MemoryEmbeddingMonitor />);
    await screen.findByText(TITLE);
    vi.mocked(loadMemoryConfig).mockClear();
    vi.mocked(loadMemoryEmbeddingStatus).mockClear();
    act(() => {
      window.dispatchEvent(new Event('embeddingModelChanged'));
    });
    await waitFor(() => expect(loadMemoryConfig).toHaveBeenCalled());
    await waitFor(() => expect(loadMemoryEmbeddingStatus).toHaveBeenCalled());
  });

  it('disables memory and closes the modal on success', async () => {
    vi.mocked(setMemorySwitch).mockResolvedValue(true);
    render(<MemoryEmbeddingMonitor />);
    await screen.findByText(TITLE);
    await userEvent.click(screen.getByRole('button', { name: DISABLE }));
    expect(setMemorySwitch).toHaveBeenCalledWith(false);
    await waitFor(() =>
      expect(screen.queryByText(TITLE)).not.toBeInTheDocument()
    );
  });

  it('enters loading state while the disable request is pending', async () => {
    let resolveSwitch!: (value: boolean) => void;
    vi.mocked(setMemorySwitch).mockImplementation(
      () =>
        new Promise<boolean>((resolve) => {
          resolveSwitch = resolve;
        })
    );
    render(<MemoryEmbeddingMonitor />);
    await screen.findByText(TITLE);
    const button = screen.getByRole('button', { name: DISABLE });
    await userEvent.click(button);
    expect(setMemorySwitch).toHaveBeenCalledWith(false);
    expect(button).toBeDisabled();
    await act(async () => {
      resolveSwitch(true);
    });
    await waitFor(() =>
      expect(screen.queryByText(TITLE)).not.toBeInTheDocument()
    );
  });

  it('shows an error and keeps the modal open when disabling fails', async () => {
    vi.mocked(setMemorySwitch).mockResolvedValue(false);
    render(<MemoryEmbeddingMonitor />);
    await screen.findByText(TITLE);
    await userEvent.click(screen.getByRole('button', { name: DISABLE }));
    await waitFor(() =>
      expect(mockMessage.error).toHaveBeenCalledWith(
        'useMemory.setMemorySwitchError'
      )
    );
    expect(screen.getByText(TITLE)).toBeInTheDocument();
  });

  it('shows the configure action and routes to the models page when permitted', async () => {
    setup({ canConfigure: true });
    render(<MemoryEmbeddingMonitor />);
    await screen.findByText(TITLE);
    await userEvent.click(screen.getByRole('button', { name: CONFIGURE }));
    expect(mockPush).toHaveBeenCalledWith('/en/models');
    await waitFor(() =>
      expect(screen.queryByText(TITLE)).not.toBeInTheDocument()
    );
  });

  it('hides the configure action and shows the tip when not permitted', async () => {
    setup({ canConfigure: false });
    render(<MemoryEmbeddingMonitor />);
    await screen.findByText(TITLE);
    expect(
      screen.queryByRole('button', { name: CONFIGURE })
    ).not.toBeInTheDocument();
    expect(screen.getByText(TIP)).toBeInTheDocument();
  });

  it('logs and keeps the modal closed when loadMemoryConfig fails', async () => {
    vi.mocked(loadMemoryConfig).mockRejectedValue(
      new Error('config failure')
    );
    render(<MemoryEmbeddingMonitor />);
    await waitFor(() => expect(log.error).toHaveBeenCalled());
    expect(loadMemoryEmbeddingStatus).not.toHaveBeenCalled();
    expect(screen.queryByText(TITLE)).not.toBeInTheDocument();
  });

  it('logs and keeps the modal closed when loadMemoryEmbeddingStatus fails', async () => {
    vi.mocked(loadMemoryEmbeddingStatus).mockRejectedValue(
      new Error('status failure')
    );
    render(<MemoryEmbeddingMonitor />);
    await waitFor(() => expect(log.error).toHaveBeenCalled());
    expect(screen.queryByText(TITLE)).not.toBeInTheDocument();
  });

  it('unsubscribes and removes the embeddingModelChanged listener on unmount', async () => {
    const addSpy = vi.spyOn(window, 'addEventListener');
    const removeSpy = vi.spyOn(window, 'removeEventListener');
    const { unmount } = render(<MemoryEmbeddingMonitor />);
    await screen.findByText(TITLE);
    expect(addSpy).toHaveBeenCalledWith(
      'embeddingModelChanged',
      expect.any(Function)
    );
    unmount();
    expect(mockUnsubscribe).toHaveBeenCalled();
    expect(removeSpy).toHaveBeenCalledWith(
      'embeddingModelChanged',
      expect.any(Function)
    );
    addSpy.mockRestore();
    removeSpy.mockRestore();
  });
});
