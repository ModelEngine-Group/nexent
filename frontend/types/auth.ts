// User type definition
export interface User {
  id: string;
  email: string;
  role: "user" | "admin";
  avatar_url?: string;
}

// Session type definition
export interface Session {
  user: User;
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
  register: (
    email: string,
    password: string,
    isAdmin?: boolean,
    inviteCode?: string
  ) => Promise<void>;
  logout: (options?: { silent?: boolean }) => Promise<void>;
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
