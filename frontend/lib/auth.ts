/**
 * Authentication utilities
 */

import { createAvatar } from '@dicebear/core';
import * as initialsStyle from '@dicebear/initials';

import { fetchWithErrorHandling } from "@/services/api";
import { STORAGE_KEYS } from "@/const/auth";
import { Session } from "@/types/auth";
import log from "@/lib/logger";

// Get color corresponding to user role
export function getRoleColor(role: string): string {
  switch (role) {
    case "admin":
      return "purple"
    case "user":
    default:
      return "geekblue"
  }
}

// Generate avatar based on email
export function generateAvatarUrl(email: string): string {
    // Use local dicebear package to generate avatar
    const avatar = createAvatar(initialsStyle, {
      seed: email,
      backgroundType: ['gradientLinear']
    });

    // Return SVG data URI
    return avatar.toDataUri();
  }

/**
 * Request with authorization headers
 */
export const fetchWithAuth = async (url: string, options: RequestInit = {}) => {
  const session = typeof window !== "undefined" ? localStorage.getItem(STORAGE_KEYS.SESSION) : null;
  const sessionObj = session ? JSON.parse(session) : null;

  const isFormData = options.body instanceof FormData;
  const headers = {
    ...(isFormData ? {} : { "Content-Type": "application/json" }),
    ...(sessionObj?.access_token && { "Authorization": `Bearer ${sessionObj.access_token}` }),
    ...options.headers,
  };

  // Use request interceptor with error handling
  return fetchWithErrorHandling(url, {
    ...options,
    headers,
  });
};

/**
 * Save session to local storage
 */
export const saveSessionToStorage = (session: Session) => {
  if (typeof window !== "undefined") {
    localStorage.setItem(STORAGE_KEYS.SESSION, JSON.stringify(session));
  }
};

/**
 * 从本地存储删除会话
 */
export const removeSessionFromStorage = () => {
  if (typeof window !== "undefined") {
    localStorage.removeItem(STORAGE_KEYS.SESSION);
  }
};

/**
 * 从本地存储获取会话
 */
export const getSessionFromStorage = (): Session | null => {
  try {
    const storedSession = typeof window !== "undefined" ? localStorage.getItem(STORAGE_KEYS.SESSION) : null;
    if (!storedSession) return null;

    return JSON.parse(storedSession);
  } catch (error) {
    log.error("解析会话信息失败:", error);
    return null;
  }
};

/**
 * Get the authorization header information for API requests
 * @returns HTTP headers object containing authentication and content type information
 */
export const getAuthHeaders = () => {
  const session = typeof window !== "undefined" ? localStorage.getItem("session") : null;
  const sessionObj = session ? JSON.parse(session) : null;

  return {
    'Content-Type': 'application/json',
    'User-Agent': 'AgentFrontEnd/1.0',
    ...(sessionObj?.access_token && { "Authorization": `Bearer ${sessionObj.access_token}` }),
  };
};