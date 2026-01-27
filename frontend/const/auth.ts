// Status codes for authentication
export enum USER_ROLES {
  SU = "SU",
  ADMIN = "ADMIN",
  DEV = "DEV",
  USER = "USER",
  SPEED = "SPEED",
}

export const STATUS_CODES = {
  SUCCESS: 200,

  UNAUTHORIZED_HTTP: 401,
  REQUEST_ENTITY_TOO_LARGE: 413,

  INVALID_CREDENTIALS: 1002,
  TOKEN_EXPIRED: 1003,
  UNAUTHORIZED: 1004,
  INVALID_INPUT: 1006,
  AUTH_SERVICE_UNAVAILABLE: 1007,

  SERVER_ERROR: 1005,
};

// Local storage keys
export const STORAGE_KEYS = {
  SESSION: "session",
};

// Type-safe authentication events (used with authEvents emitter)
export const AUTH_EVENTS = {
  LOGIN_SUCCESS: "auth:login-success",
  REGISTER_SUCCESS: "auth:register-success",
  LOGOUT: "auth:logout",
  SESSION_EXPIRED: "auth:session-expired",  // Deprecated: this is an authorization event; prefer AUTHZ_EVENTS.PERMISSION_DENIED.
  TOKEN_REFRESHED: "auth:token-refreshed",
  SERVICE_UNAVAILABLE: "auth:service-unavailable",
  BACK_TO_HOME: "nav:back-to-home",
} as const;

// Type-safe authorization events (used with authzEvents emitter)
export const AUTHZ_EVENTS = {
  PERMISSION_DENIED: "authz:permission-denied",
  PERMISSIONS_READY: "authz:permissions-ready",
  PERMISSIONS_UPDATED: "authz:permissions-updated",
} as const;

