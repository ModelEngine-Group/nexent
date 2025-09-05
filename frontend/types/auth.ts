/*
 * 认证相关类型与常量定义
 */
export const STATUS_CODES = {
  SUCCESS: 200,
  
  UNAUTHORIZED_HTTP: 401,

  INVALID_CREDENTIALS: 1002,
  TOKEN_EXPIRED: 1003,
  UNAUTHORIZED: 1004,
  INVALID_INPUT: 1006,
  AUTH_SERVICE_UNAVAILABLE: 1007,

  SERVER_ERROR: 1005,
};

// 本地存储键
export const STORAGE_KEYS = {
  SESSION: "session",
};

// 自定义事件
export const EVENTS = {
  SESSION_EXPIRED: "session-expired",
  STORAGE_CHANGE: "storage",
}; 


// 用户类型定义
export interface User {
  id: string;
  email: string;
  role: "user" | "admin";
  avatar_url?: string;
}

// 会话类型定义
export interface Session {
  user: User;
  access_token: string;
  refresh_token: string;
  expires_at: number;
}

// 错误响应接口
export interface ErrorResponse {
  message: string;
  code: number;
  data?: any;
}

// 授权上下文类型
export interface AuthContextType {
  user: User | null;
  isLoading: boolean;
  isLoginModalOpen: boolean;
  isRegisterModalOpen: boolean;
  isFromSessionExpired: boolean;
  authServiceUnavailable: boolean;
  isSpeedMode: boolean;
  isReady: boolean;
  openLoginModal: () => void;
  closeLoginModal: () => void;
  openRegisterModal: () => void;
  closeRegisterModal: () => void;
  setIsFromSessionExpired: (value: boolean) => void;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, isAdmin?: boolean, inviteCode?: string) => Promise<void>;
  logout: () => Promise<void>;
}

// 会话响应类型
export interface SessionResponse {
  data?: {
    session?: Session | null;
    user?: User | null;
  };
  error: ErrorResponse | null;
}
