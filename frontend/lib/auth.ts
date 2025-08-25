/**
 * Authentication utilities
 */

import { createAvatar } from '@dicebear/core';
import * as initialsStyle from '@dicebear/initials';
import { fetchWithErrorHandling } from "@/services/api";
import { Session, STORAGE_KEYS } from "@/types/auth";

// 获取用户角色对应的颜色
export function getRoleColor(role: string): string {
  switch (role) {
    case "admin":
      return "purple"
    case "user":
    default:
      return "geekblue"
  }
}

// 根据邮箱生成头像
export function generateAvatarUrl(email: string): string {
    // 使用本地dicebear包生成头像
    const avatar = createAvatar(initialsStyle, {
      seed: email,
      backgroundType: ['gradientLinear']
    });

    // 返回SVG数据URI
    return avatar.toDataUri();
  }

/**
 * 带有授权头的请求
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

  // 使用带错误处理的请求拦截器
  return fetchWithErrorHandling(url, {
    ...options,
    headers,
  });
};

/**
 * 保存会话到本地存储
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
    console.error("解析会话信息失败:", error);
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