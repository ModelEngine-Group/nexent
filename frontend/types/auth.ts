// User type definition - contains only basic user information
import type { USER_ROLES } from "@/const/auth";

export type UserRole = USER_ROLES;

export interface User {
  id: string;
  email: string;
  role: UserRole;
  avatarUrl?: string;
  tenantId?: string;
}

// Session type definition - contains only authentication tokens
export interface Session {
  access_token: string;
  refresh_token: string;
  expires_at: number;
}

// Error response interface
export interface ErrorResponse {
  message: string;
  code: number;
  data?: any;
}

// Authorization context type
// Auth form values interface
export interface AuthFormValues {
  email: string;
  password: string;
  confirmPassword: string;
  inviteCode?: string;
}

// Authorization context type
export interface AuthContextType {
  user: User | null;
  permissions: string[];
  accessibleRoutes: string[];
  isLoading: boolean;
  isLoginModalOpen: boolean;
  isRegisterModalOpen: boolean;
  authServiceUnavailable: boolean;
  isAuthReady: boolean;
  openLoginModal: () => void;
  closeLoginModal: () => void;
  openRegisterModal: () => void;
  closeRegisterModal: () => void;
  login: (email: string, password: string) => Promise<void>;
  register: (
    email: string,
    password: string,
    inviteCode?: string,
    withNewInvitation?: boolean
  ) => Promise<void>;
  logout: (options?: { silent?: boolean }) => Promise<void>;
  clearLocalSession: () => void;
  revoke: () => Promise<void>;
}

// Session response type
export interface SessionResponse {
  data?: {
    session?: Session | null;
    user?: User | null;
  };
  error: ErrorResponse | null;
}

// Current user info response type (includes permissions and accessible routes)
// Backend returns user data directly, not nested under "user" property
export interface AuthInfoResponse {
  user: User & {
    groupIds: number[];
    permissions: string[];
    accessibleRoutes: string[];
  };
}

import type { AUTH_EVENTS, AUTHZ_EVENTS } from "@/const/auth";

export type AuthEventKey = (typeof AUTH_EVENTS)[keyof typeof AUTH_EVENTS];
export type AuthzEventKey = (typeof AUTHZ_EVENTS)[keyof typeof AUTHZ_EVENTS];

// Authentication Events
export interface AuthEvents {
  [AUTH_EVENTS.LOGIN_SUCCESS]: User | null;
  [AUTH_EVENTS.REGISTER_SUCCESS]: void;
  [AUTH_EVENTS.LOGOUT]: void;
  [AUTH_EVENTS.SESSION_EXPIRED]: void;
  [AUTH_EVENTS.TOKEN_REFRESHED]: void;
  [AUTH_EVENTS.SERVICE_UNAVAILABLE]: void;
  [AUTH_EVENTS.BACK_TO_HOME]: void;
}

// Authorization Events
export interface AuthzEvents {
  [AUTHZ_EVENTS.PERMISSION_DENIED]: { pathname: string } | void;
  [AUTHZ_EVENTS.PERMISSIONS_READY]: User & {
    permissions: string[];
    accessibleRoutes: string[];
  };
  [AUTHZ_EVENTS.PERMISSIONS_UPDATED]: void;
}

// Authentication Context Type
export interface AuthenticationContextType {
  // Authentication state
  isAuthenticated: boolean;
  isAuthChecking: boolean;
  isLoading: boolean;
  session: Session | null;

  // UI state
  isLoginModalOpen: boolean;
  isRegisterModalOpen: boolean;
  authServiceUnavailable: boolean;

  // Methods
  login: (
    email: string,
    password: string,
    options?: { showSuccessMessage?: boolean }
  ) => Promise<void>;
  register: (
    email: string,
    password: string,
    inviteCode?: string,
    withNewInvitation?: boolean
  ) => Promise<void>;
  logout: (options?: { silent?: boolean }) => Promise<void>;
  clearLocalSession: () => void;
  revoke: () => Promise<void>;

  // UI methods
  openLoginModal: () => void;
  closeLoginModal: () => void;
  openRegisterModal: () => void;
  closeRegisterModal: () => void;

  // Auth prompt modal (for side navigation pre-check)
  isAuthPromptModalOpen: boolean;
  openAuthPromptModal: () => void;
  closeAuthPromptModal: () => void;

  // Session expired modal
  isSessionExpiredModalOpen: boolean;
  openSessionExpiredModal: () => void;
  closeSessionExpiredModal: () => void;
}

// Authentication State Return Type - for useAuthenticationState hook
export interface AuthenticationStateReturn {
  // Authentication state
  isAuthenticated: boolean;
  isAuthChecking: boolean;
  isLoading: boolean;
  session: Session | null;
  authServiceUnavailable: boolean;

  // Methods
  login: (
    email: string,
    password: string,
    options?: { showSuccessMessage?: boolean }
  ) => Promise<void>;
  register: (
    email: string,
    password: string,
    inviteCode?: string,
    withNewInvitation?: boolean
  ) => Promise<void>;
  logout: (options?: { silent?: boolean }) => Promise<void>;
  clearLocalSession: () => void;
  revoke: () => Promise<void>;
}

// Authentication UI Return Type - for useAuthenticationUI hook
export interface AuthenticationUIReturn {
  // Login/Register Modal
  isLoginModalOpen: boolean;
  openLoginModal: () => void;
  closeLoginModal: () => void;
  isRegisterModalOpen: boolean;
  openRegisterModal: () => void;
  closeRegisterModal: () => void;

  // Auth prompt modal (for side navigation pre-check)
  isAuthPromptModalOpen: boolean;
  openAuthPromptModal: () => void;
  closeAuthPromptModal: () => void;

  // Session expired modal
  isSessionExpiredModalOpen: boolean;
  openSessionExpiredModal: () => void;
  closeSessionExpiredModal: () => void;
}

// Authorization Context Type
export interface AuthorizationContextType {
  // Authorization data
  user: User | null;
  groupIds: number[];
  permissions: string[];
  accessibleRoutes: string[];

  // State
  isLoading: boolean;
  error: Error | null;

  // Authorization status
  // True when authorization is complete and user has permission to access current route
  isAuthorized: boolean;

  // True when authorization data is ready (permissions loaded)
  // Does not indicate whether user has permission, only that the process is complete
  isAuthzReady: boolean;

  // Methods
  refetch: () => Promise<any>;
  hasPermission: (permission: string) => boolean;
  hasAnyPermission: (permissions: string[]) => boolean;
  canAccessRoute: (route: string) => boolean;

  // Authz prompt modal (permission denied)
  isAuthzPromptModalOpen: boolean;
  openAuthzPromptModal: () => void;
  closeAuthzPromptModal: () => void;
}
