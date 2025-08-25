/**
 * 认证服务
 */
import { generateAvatarUrl, removeSessionFromStorage } from "@/lib/auth"
import { API_ENDPOINTS } from "@/services/api";
import { STATUS_CODES } from "@/types/auth";
import { sessionService } from "@/services/sessionService";
import { Session, User, SessionResponse } from "@/types/auth";
import { fetchWithAuth, getSessionFromStorage, saveSessionToStorage } from "@/lib/auth";


// 认证服务
export const authService = {
  // 获取当前会话
  getSession: async (): Promise<Session | null> => {
    try {
      // 从本地存储获取会话信息
      const sessionObj = getSessionFromStorage();
      if (!sessionObj?.access_token) return null;
      
      // 检查令牌是否即将过期，如果是，尝试刷新
      const isTokenValid = await sessionService.checkAndRefreshToken();
      if (!isTokenValid) {
        console.warn("令牌无效或刷新失败");
        // 我们不立即清除会话，而是等待后续操作失败后清除
      }
      
      try {
        // 验证会话是否有效
        const response = await fetchWithAuth(API_ENDPOINTS.user.session);
        const data = await response.json();
        
        // 更新用户信息 (可能在后端已变更)
        if (data.data?.user) {
          sessionObj.user = {
            ...sessionObj.user,
            ...data.data.user,
            avatar_url: sessionObj.user.avatar_url // 保留头像
          };
          
          // 更新存储的会话
          saveSessionToStorage(sessionObj);
        }
        
        return sessionObj;
      } catch (error) {
        console.error("验证会话时出错:", error);
        
        // 检查是否是TOKEN_EXPIRED错误
        if (error instanceof Error && 'code' in error && (error as any).code === STATUS_CODES.TOKEN_EXPIRED) {
          return null;
        }
        
        // 如果是其他网络错误，不要立即清除会话
        // 可能是后端服务未启动或暂时不可用
        console.warn("后端验证会话失败，但将继续使用本地会话");
        return sessionObj;
      }
    } catch (error) {
      console.error("获取会话失败:", error);
      return null;
    }
  },

  // 检查认证服务是否可用
  checkAuthServiceAvailable: async (): Promise<boolean> => {
    try {
      const response = await fetch(API_ENDPOINTS.user.serviceHealth, {method: 'GET'});
      if (!response.ok) {
        console.warn("认证服务健康检查请求失败");
        return false;
      }

      const data = await response.json();
      
      if (data.code !== STATUS_CODES.SUCCESS) {
        console.warn(data.message);
        return false;
      }

      return data.data === true;
    } catch (error) {
      console.error("检查认证服务可用性时出错:", error);
      return false;
    }
  },

  // 登录
  signIn: async (email: string, password: string): Promise<SessionResponse> => {
    try {
      const response = await fetch(API_ENDPOINTS.user.signin, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ 
          email, 
          password,
        }),
      });
      
      const data = await response.json();
      
      if (data.code !== STATUS_CODES.SUCCESS) {
        return { 
          error: { 
            message: data.message || "登录失败",
            code: data.code,
            data: data.data
          }
        };
      }
      
      // 生成头像URL
      const avatar_url = generateAvatarUrl(email);
      
      // 构建用户对象
      const user = {
        id: data.data.user.id,
        email: data.data.user.email,
        role: data.data.user.role,
        avatar_url,
      };
      
      // 构建会话对象
      const session = {
        user,
        access_token: data.data.session.access_token,
        refresh_token: data.data.session.refresh_token,
        expires_at: data.data.session.expires_at,
      };
      
      // 保存会话到本地存储
      saveSessionToStorage(session);
      
      // 验证会话是否已正确保存，如果没有则重试
      setTimeout(() => {
        const savedSession = getSessionFromStorage();
        if (!savedSession || !savedSession.access_token) {
          console.warn("会话未正确保存，重试...");
          saveSessionToStorage(session);
        } else {
          console.debug("会话已成功保存到本地存储");
        }
      }, 100);
      
      return { data: { session }, error: null };
    } catch (error) {
      console.error("登录失败:", error);
      return { 
        error: { 
          message: error instanceof Error ? error.message : "网络错误，请稍后重试",
          code: (error instanceof Error && 'code' in error) ? (error as any).code : STATUS_CODES.SERVER_ERROR
        }
      };
    }
  },

  // 注册
  signUp: async (email: string, password: string, isAdmin?: boolean, inviteCode?: string): Promise<SessionResponse> => {
    try {
      const response = await fetch(API_ENDPOINTS.user.signup, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ 
          email, 
          password, 
          is_admin: isAdmin || false,
          invite_code: inviteCode || null
        }),
      });
      
      const data = await response.json();
      
      if (data.code !== STATUS_CODES.SUCCESS) {
        return { 
          error: { 
            message: data.message || "注册失败",
            code: data.code,
            data: data.data  // 传递后端返回的完整data字段，包含error_type等信息
          }
        };
      }
      
      // 生成头像URL
      const avatar_url = generateAvatarUrl(email);
      
      // 构建用户对象
      const user: User = {
        id: data.data.user.id,
        email: data.data.user.email,
        role: data.data.user.role || "user", // 使用后端返回的角色信息
        avatar_url,
      };
      
      // 如果注册时没有返回会话信息，则尝试登录
      if (!data.data.session || !data.data.session.access_token) {
        // 获取登录令牌
        const loginResponse = await fetch(API_ENDPOINTS.user.signin, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ email, password }),
        });
        
        const loginData = await loginResponse.json();
        
        if (loginData.code !== STATUS_CODES.SUCCESS) {
          // 返回只有用户没有会话的结果
          return { data: { user, session: null }, error: null };
        }
        
        // 构建完整会话
        const session: Session = {
          user,
          access_token: loginData.data.session.access_token,
          refresh_token: loginData.data.session.refresh_token,
          expires_at: loginData.data.session.expires_at,
        };
        
        // 保存会话到本地存储
        saveSessionToStorage(session);
        
        return { data: { user, session }, error: null };
      } else {
        // 使用注册接口返回的会话信息
        const session: Session = {
          user,
          access_token: data.data.session.access_token,
          refresh_token: data.data.session.refresh_token,
          expires_at: data.data.session.expires_at,
        };
        
        // 保存会话到本地存储
        saveSessionToStorage(session);
        
        return { data: { user, session }, error: null };
      }
    } catch (error) {
      console.error("注册失败:", error);
      return { 
        error: { 
          message: "网络错误，请稍后重试",
          code: STATUS_CODES.SERVER_ERROR
        }
      };
    }
  },

  // 登出
  signOut: async (): Promise<{ error: null }> => {
    try {
      // 调用后端登出API
      await fetchWithAuth(API_ENDPOINTS.user.logout, {
        method: "POST",
      });
      
      // 无论成功与否，都清除本地会话
      removeSessionFromStorage();
      
      return { error: null };
    } catch (error) {
      console.error("登出失败:", error);
      
      // 即使API调用失败，也要清除本地会话
      removeSessionFromStorage();
      
      return { error: null };
    }
  },
  
  // 获取当前用户ID
  getCurrentUserId: async (): Promise<string | null> => {
    try {
      const response = await fetchWithAuth(API_ENDPOINTS.user.currentUserId);
      const data = await response.json();
      
      if (data.code !== STATUS_CODES.SUCCESS || !data.data) {
        return null;
      }
      
      return data.data.user_id;
    } catch (error) {
      console.error("获取用户ID失败:", error);
      return null;
    }
  },

  // 刷新令牌
  refreshToken: async (): Promise<boolean> => {
    return await sessionService.checkAndRefreshToken();
  }
}; 