// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

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

// useAccountMonitoring wraps a TanStack Query `useQuery`. Mocking the hook keeps
// this component test free of a QueryClientProvider requirement, in line with
// tests/component/accountMenu.test.tsx.
vi.mock('@/hooks/useAccountMonitoring', () => ({
  useAccountMonitoring: () => null,
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

// Issue #4058 moved the account area out of TopNavbar into the SideNavigation
// rail, so TopNavbar no longer renders any user identity. The identity rules are
// therefore verified through AvatarDropdown (the component that both surfaces
// mount), and TopNavbar only has to stay free of identity text.
describe('TopNavbar 不再承载用户区（用户区已迁至 SideNavigation）', () => {
  it.each([
    ['username 存在', { username: 'alice', email: 'alice@example.com' }],
    ['username 带首尾空格', { username: '  bob  ', email: 'bob@example.com' }],
    ['username 为空字符串', { username: '', email: 'carol@example.com' }],
    ['username 为 null', { username: null, email: 'carol@example.com' }],
    ['username 与 email 均为空', { username: '', email: '' }],
  ])('UT-FE-AUTO-63334E6F5D10C7FD 登录态 %s 时顶栏不出现身份文本', (_label, overrides) => {
    authState.user = makeUser(overrides);
    const { container } = render(<TopNavbar />);
    expect(container.textContent).not.toContain('alice');
    expect(container.textContent).not.toContain('carol@example.com');
    expect(container.querySelector('.ant-avatar')).toBeNull();
  });

  it('未登录态不渲染用户信息且不出现 -', () => {
    authState.user = null;
    render(<TopNavbar />);
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

  it('avatar 触发区与下拉 user-info 项展示同一身份', async () => {
    authState.user = makeUser({ username: '  dave  ', email: 'dave@example.com' });
    const { container } = render(<AvatarDropdown />);
    fireEvent.click(container.querySelector('.ant-avatar') as HTMLElement);
    await waitFor(() => {
      const nodes = screen.getAllByText('dave');
      expect(nodes.length).toBeGreaterThanOrEqual(1);
      nodes.forEach((node) => expect(node.textContent).toBe('dave'));
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
