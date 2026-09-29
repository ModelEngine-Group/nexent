import * as React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeAll, beforeEach } from 'vitest';

import { AvatarDropdown } from '@/components/auth/avatarDropdown';
import { TopNavbar } from '@/components/navigation/TopNavbar';

const authState = vi.hoisted(() => ({
  user: null as any,
  loading: false,
  logout: vi.fn(),
  openLoginModal: vi.fn(),
  openRegisterModal: vi.fn(),
}));

vi.mock('@/components/providers/AuthorizationProvider', () => ({
  useAuthorizationContext: () => ({
    user: authState.user,
    isLoading: authState.loading,
    isAuthzReady: true,
  }),
}));

vi.mock('@/components/providers/AuthenticationProvider', () => ({
  useAuthenticationContext: () => ({
    isLoading: false,
    logout: authState.logout,
    openLoginModal: authState.openLoginModal,
    openRegisterModal: authState.openRegisterModal,
  }),
}));

vi.mock('@/components/providers/deploymentProvider', () => ({
  useDeployment: () => ({
    isSpeedMode: false,
    isDeploymentReady: true,
    appVersion: 'v1.0.0',
    deploymentVersion: '',
    enableAidpKnowledge: false,
    aidpEnabled: false,
  }),
}));

vi.mock('@/lib/language', () => ({
  useLanguageSwitch: () => ({
    currentLanguage: 'en',
    handleLanguageChange: vi.fn(),
    getOppositeLanguage: () => ({ lang: 'zh', label: '简体中文' }),
  }),
}));

vi.mock('@/stores/global', () => ({
  useGlobalConfigStore: () => ({ config: {}, setConfig: vi.fn() }),
  useGlobalConfigStoreAllLanguage: () => ({ configAll: {}, setAllConfig: vi.fn() }),
}));

vi.mock('@/hooks/useNotifications', () => ({
  useNotifications: () => ({ unreadCount: 0, items: [], isLoading: false }),
  useMarkNotificationRead: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useMarkAllNotificationsRead: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));

vi.mock('@/services/monitoringService', () => ({
  monitoringService: { fetchStatus: vi.fn().mockResolvedValue(null) },
}));

vi.mock('@/hooks/useConfirmModal', () => ({
  useConfirmModal: () => ({ confirm: vi.fn() }),
}));

vi.mock('@/lib/auth', () => ({
  getRoleColor: () => 'geekblue',
}));

vi.mock('@/lib/publicAsset', () => ({
  publicAsset: (path: string) => path,
}));

vi.mock('@/components/navigation/NotificationBell', () => ({
  NotificationBell: () => null,
}));

vi.mock('@/components/navigation/ChatTopNavContent', () => ({
  ChatTopNavContent: () => null,
}));

vi.mock('next/link', () => ({
  default: (props: any) => null,
}));

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn() }),
  useParams: () => ({}),
  usePathname: () => '/',
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: 'en' },
  }),
}));

function makeUser(overrides: any = {}) {
  return {
    id: 'u-1',
    email: 'alice@example.com',
    username: 'alice',
    role: 'USER',
    ...overrides,
  };
}

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

  class ResizeObserverMockClass {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  (global as any).ResizeObserver = ResizeObserverMockClass;
});

beforeEach(() => {
  authState.user = null;
  authState.loading = false;
});

describe('TopNavbar 用户区 username/email/- 展示逻辑', () => {
  it('UT-FE-AUTO-63334E6F5D10C7FD 登录态 username 存在时优先显示 username', () => {
    authState.user = makeUser({ username: 'alice', email: 'alice@example.com' });
    render(<TopNavbar isChatPage={false} />);
    const node = screen.getByText('alice');
    expect(node.textContent).toBe('alice');
  });

  it('username 带首尾空格时显示 trim 后的值', () => {
    authState.user = makeUser({ username: '  bob  ', email: 'bob@example.com' });
    render(<TopNavbar isChatPage={false} />);
    const node = screen.getByText('bob');
    expect(node.textContent).toBe('bob');
  });

  it('username 为空字符串时回退显示 email', () => {
    authState.user = makeUser({ username: '', email: 'carol@example.com' });
    render(<TopNavbar isChatPage={false} />);
    expect(screen.getByText('carol@example.com')).toBeTruthy();
    expect(screen.queryByText('-')).toBeNull();
  });

  it('username 为 null 时回退显示 email', () => {
    authState.user = makeUser({ username: null, email: 'carol@example.com' });
    render(<TopNavbar isChatPage={false} />);
    expect(screen.getByText('carol@example.com')).toBeTruthy();
  });

  it('username 与 email 均为空时显示 -', () => {
    authState.user = makeUser({ username: '', email: '' });
    render(<TopNavbar isChatPage={false} />);
    const node = screen.getByText('-');
    expect(node.textContent).toBe('-');
  });

  it('未登录态不渲染用户信息且不出现 -', () => {
    authState.user = null;
    render(<TopNavbar isChatPage={false} />);
    expect(screen.queryByText('-')).toBeNull();
  });
});

describe('AvatarDropdown 用户区展示与一致性', () => {
  it('点击头像后 user-info 菜单显示 username', async () => {
    authState.user = makeUser({ username: 'alice', email: 'alice@example.com' });
    const { container } = render(<AvatarDropdown />);
    fireEvent.click(container.querySelector('.ant-avatar') as HTMLElement);
    await waitFor(() => {
      expect(screen.getByText('alice')).toBeTruthy();
    });
  });

  it('user-info 菜单显示 trim 后的 username', async () => {
    authState.user = makeUser({ username: '  bob  ', email: 'bob@example.com' });
    const { container } = render(<AvatarDropdown />);
    fireEvent.click(container.querySelector('.ant-avatar') as HTMLElement);
    await waitFor(() => {
      const node = screen.getByText('bob');
      expect(node.textContent).toBe('bob');
    });
  });

  it('username 为空时 user-info 菜单回退显示 email', async () => {
    authState.user = makeUser({ username: '', email: 'carol@example.com' });
    const { container } = render(<AvatarDropdown />);
    fireEvent.click(container.querySelector('.ant-avatar') as HTMLElement);
    await waitFor(() => {
      expect(screen.getByText('carol@example.com')).toBeTruthy();
    });
  });

  it('username 与 email 均为空时 user-info 菜单显示 -', async () => {
    authState.user = makeUser({ username: '', email: '' });
    const { container } = render(<AvatarDropdown />);
    fireEvent.click(container.querySelector('.ant-avatar') as HTMLElement);
    await waitFor(() => {
      expect(screen.getByText('-')).toBeTruthy();
    });
  });

  it('顶栏用户区与头像下拉菜单展示一致', async () => {
    authState.user = makeUser({ username: '  dave  ', email: 'dave@example.com' });
    const { container } = render(<TopNavbar isChatPage={false} />);
    const span = screen.getByText('dave');
    expect(span.textContent).toBe('dave');
    fireEvent.click(container.querySelector('.ant-avatar') as HTMLElement);
    await waitFor(() => {
      const nodes = screen.getAllByText('dave');
      expect(nodes.length).toBe(2);
    });
  });
});

describe('AvatarDropdown 未登录态', () => {
  it('显示登录/注册入口且不出现 -', async () => {
    authState.user = null;
    const { container } = render(<AvatarDropdown />);
    fireEvent.click(container.querySelector('button') as HTMLElement);
    await waitFor(() => {
      expect(screen.getByText('auth.login')).toBeTruthy();
      expect(screen.getByText('auth.register')).toBeTruthy();
    });
    expect(screen.queryByText('-')).toBeNull();
  });
});
