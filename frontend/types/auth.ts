/*
 * 认证相关类型与常量定义
 */

export const STATUS_CODES = {
  // 成功状态码
  SUCCESS: 200,               // 成功
  
  // 客户端错误状态码
  USER_EXISTS: 1001,          // 用户已存在
  INVALID_CREDENTIALS: 1002,  // 无效的登录凭证
  TOKEN_EXPIRED: 1003,        // Token已过期
  UNAUTHORIZED: 1004,         // 未授权操作
  INVALID_INPUT: 1006,        // 无效的输入参数
  AUTH_SERVICE_UNAVAILABLE: 1007, // 认证服务不可用
  
  // 服务器错误状态码
  SERVER_ERROR: 1005,         // 服务器内部错误
};


// 默认的会话有效期（天）
export const DEFAULT_SESSION_EXPIRY_DAYS = 1;

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

// 登录/注册表单值类型
export interface AuthFormValues {
  email: string;
  password: string;
  confirmPassword?: string;
} 