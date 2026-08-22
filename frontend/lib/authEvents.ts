/**
 * Authentication and Authorization Event System
 * Provides type-safe event communication between authentication and authorization modules
 */

import log from "@/lib/logger";
import { AUTH_EVENTS, AUTHZ_EVENTS } from "@/const/auth";

// Event emitter for authentication events
class AuthEventEmitter {
  emit<K extends keyof import("@/types/auth").AuthEvents>(
    event: K,
    data?: import("@/types/auth").AuthEvents[K]
  ) {
    log.debug(`Auth event emitted: ${event}`, data);
    window.dispatchEvent(new CustomEvent(event, { detail: data }));
  }

  on<K extends keyof import("@/types/auth").AuthEvents>(
    event: K,
    handler: (data?: import("@/types/auth").AuthEvents[K]) => void
  ) {
    const listener = (e: CustomEvent) => handler(e.detail);
    window.addEventListener(event, listener as EventListener);

    // Return cleanup function
    return () => {
      window.removeEventListener(event, listener as EventListener);
    };
  }
}

// Event emitter for authorization events
class AuthzEventEmitter {
  emit<K extends keyof import("@/types/auth").AuthzEvents>(
    event: K,
    data?: import("@/types/auth").AuthzEvents[K]
  ) {
    log.debug(`Authz event emitted: ${event}`, data);
    window.dispatchEvent(new CustomEvent(event, { detail: data }));
  }

  on<K extends keyof import("@/types/auth").AuthzEvents>(
    event: K,
    handler: (data?: import("@/types/auth").AuthzEvents[K]) => void
  ) {
    const listener = (e: CustomEvent) => handler(e.detail);
    window.addEventListener(event, listener as EventListener);

    // Return cleanup function
    return () => {
      window.removeEventListener(event, listener as EventListener);
    };
  }
}

// Global instances
export const authEvents = new AuthEventEmitter();
export const authzEvents = new AuthzEventEmitter();

// Utility functions for common auth events
export const authEventUtils = {
  emitLoginSuccess: () => authEvents.emit(AUTH_EVENTS.LOGIN_SUCCESS),
  emitRegisterSuccess: () => authEvents.emit(AUTH_EVENTS.REGISTER_SUCCESS),
  emitLogout: () => authEvents.emit(AUTH_EVENTS.LOGOUT),
  emitSessionExpired: () => authEvents.emit(AUTH_EVENTS.SESSION_EXPIRED),
  emitTokenRefreshed: () => authEvents.emit(AUTH_EVENTS.TOKEN_REFRESHED),
  emitServiceUnavailable: () =>
    authEvents.emit(AUTH_EVENTS.SERVICE_UNAVAILABLE),
  emitBackToHome: () =>
    authEvents.emit(AUTH_EVENTS.BACK_TO_HOME),
};

export const authzEventUtils = {
  emitPermissionsReady: (
    userData: import("@/types/auth").User & {
      permissions: string[];
      accessibleRoutes: string[];
    }
  ) => authzEvents.emit(AUTHZ_EVENTS.PERMISSIONS_READY, userData),
  emitPermissionsUpdated: () =>
    authzEvents.emit(AUTHZ_EVENTS.PERMISSIONS_UPDATED),
};
