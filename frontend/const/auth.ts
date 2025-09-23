// Status codes for authentication
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

// Custom events
export const EVENTS = {
  SESSION_EXPIRED: "session-expired",
  STORAGE_CHANGE: "storage",
};
