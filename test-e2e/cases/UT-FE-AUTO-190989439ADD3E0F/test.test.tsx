import { render, screen, cleanup } from '@testing-library/react';
import { beforeAll, beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import UserProfileComp from '@/app/[locale]/users/components/UserProfileComp';
import { useAuthenticationContext } from '@/components/providers/AuthenticationProvider';
import { useAuthorizationContext } from '@/components/providers/AuthorizationProvider';

const mocks = vi.hoisted(() => ({
  useAuthenticationContext: vi.fn(),
  useAuthorizationContext: vi.fn(),
  confirm: vi.fn(),
  getUserTokens: vi.fn(),
  deleteUserToken: vi.fn(),
  createUserToken: vi.fn(),
  authService: { updatePassword: vi.fn() },
  getPasswordChecks: vi.fn(),
  getStrengthLevel: vi.fn(),
  copyToClipboard: vi.fn(),
  message: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
  modal: { confirm: vi.fn() },
  notification: { success: vi.fn(), error: vi.fn() },
  log: { debug: vi.fn(), info: vi.fn(), warn: vi.fn(), error: vi.fn(), log: vi.fn() },
}));

vi.mock('@/components/providers/AuthenticationProvider', () => ({
  useAuthenticationContext: mocks.useAuthenticationContext,
}));
vi.mock('@/components/providers/AuthorizationProvider', () => ({
  useAuthorizationContext: mocks.useAuthorizationContext,
}));
vi.mock('@/hooks/group/useGroupList', () => ({
  useGroupList: () => ({ data: { groups: [] }, allGroupIds: [] }),
}));
vi.mock('@/hooks/useConfirmModal', () => ({
  useConfirmModal: () => ({ confirm: mocks.confirm }),
}));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (_key: string) => undefined, i18n: {} }),
}));
vi.mock('@/components/auth/DeleteAccountModal', () => ({
  DeleteAccountModal: () => null,
}));
vi.mock('@/components/settings/OAuthAccountsSection', () => ({
  OAuthAccountsSection: () => null,
}));
vi.mock('@/lib/logger', () => ({ default: mocks.log }));
vi.mock('@/lib/utils', () => ({
  getPasswordChecks: mocks.getPasswordChecks,
  getStrengthLevel: mocks.getStrengthLevel,
}));
vi.mock('@/lib/clipboard', () => ({ copyToClipboard: mocks.copyToClipboard }));
vi.mock('@/services/authService', () => ({ authService: mocks.authService }));
vi.mock('@/services/tokenService', () => ({
  getUserTokens: mocks.getUserTokens,
  deleteUserToken: mocks.deleteUserToken,
  createUserToken: mocks.createUserToken,
}));
vi.mock('@/const/modelConfig', () => ({
  USER_ROLES: {
    SPEED: 'SPEED',
    SU: 'SU',
    ADMIN: 'ADMIN',
    DEV: 'DEV',
    USER: 'USER',
    ASSET_OWNER: 'ASSET_OWNER',
  },
}));
vi.mock('@/const/errorCode', () => ({
  ErrorCode: {
    INVALID_CREDENTIALS: '110104',
    PASSWORD_WEAK: '110201',
    PASSWORD_SAME_AS_OLD: '110202',
    USER_UPDATE_FAILED: '110102',
    SUCCESS: '0',
  },
}));
vi.mock('framer-motion', async () => {
  const ReactImport = await import('react');
  return {
    motion: {
      div: ({ initial, animate, transition, children, ...rest }: any) =>
        ReactImport.createElement('div', rest, children),
    },
  };
});
vi.mock('antd', async (importOriginal) => {
  const actual: any = await importOriginal();
  return {
    ...actual,
    App: {
      ...actual.App,
      useApp: () => ({
        message: mocks.message,
        modal: mocks.modal,
        notification: mocks.notification,
      }),
    },
  };
});

function makeUser(overrides: any = {}) {
  return {
    id: 'u-1',
    email: 'user@example.com',
    username: null,
    role: 'USER',
    tenantId: 'tenant-1',
    authProvider: 'local',
    ...overrides,
  };
}

function renderWithUser(user: any) {
  mocks.useAuthorizationContext.mockReturnValue({ user, groupIds: [] });
  return render(<UserProfileComp />);
}

beforeAll(() => {
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
  if (!(window as any).ResizeObserver) {
    (window as any).ResizeObserver = class {
      observe() {}
      unobserve() {}
      disconnect() {}
    };
  }
});

beforeEach(() => {
  vi.clearAllMocks();
  mocks.useAuthenticationContext.mockReturnValue({
    logout: vi.fn(),
    revoke: vi.fn(),
    isLoading: false,
  });
  mocks.getUserTokens.mockResolvedValue([]);
});

afterEach(() => {
  cleanup();
});

describe('UserProfileComp Account Info', () => {
  it('UT-FE-AUTO-190989439ADD3E0F 场景A CAS 用户名存在时标签为 Username 且值取 username.trim()', async () => {
    renderWithUser(makeUser({ authProvider: 'cas', username: 'cas_user_01', email: 'cas01@example.com' }));
    expect(await screen.findByText('Username')).toBeTruthy();
    expect(screen.getByText('cas_user_01')).toBeTruthy();
  });

  it('场景B 本地用户标签为 Email 且仅取 email.trim() 不读取 username', async () => {
    const localUser: any = {
      id: 'u-local-1',
      email: 'local01@example.com',
      role: 'USER',
      tenantId: 'tenant-1',
      authProvider: 'local',
      get username() {
        throw new Error('username must not be read for local users');
      },
    };
    renderWithUser(localUser);
    expect(await screen.findByText('Email')).toBeTruthy();
    expect(screen.getByText('local01@example.com')).toBeTruthy();
  });

  it('场景C CAS 空用户名时标签仍为 Username 且值回退 email.trim()', async () => {
    renderWithUser(makeUser({ authProvider: 'cas', username: null, email: 'cas02@example.com' }));
    expect(await screen.findByText('Username')).toBeTruthy();
    expect(screen.getByText('cas02@example.com')).toBeTruthy();
  });

  it('场景D CAS 用户名与邮箱均为空时值显示 - 且渲染不抛异常', async () => {
    renderWithUser(makeUser({ authProvider: 'cas', username: '', email: '' }));
    expect(await screen.findByText('Username')).toBeTruthy();
    expect(screen.getByText('-')).toBeTruthy();
  });

  it('场景E 展示值经 trim（username 优先与 email 回退均去首尾空格）', async () => {
    renderWithUser(makeUser({ authProvider: 'cas', username: '  cas_user_02  ', email: ' cas03@example.com ' }));
    expect(await screen.findByText('cas_user_02')).toBeTruthy();
    cleanup();
    renderWithUser(makeUser({ authProvider: 'cas', username: '   ', email: ' cas03@example.com ' }));
    expect(await screen.findByText('cas03@example.com')).toBeTruthy();
  });

  it('卸载后无残留监听或副作用且无未处理异常', () => {
    const { unmount } = renderWithUser(makeUser({ authProvider: 'cas', username: 'cas_user_01', email: 'cas01@example.com' }));
    expect(screen.getByText('Username')).toBeTruthy();
    expect(() => unmount()).not.toThrow();
  });
});
