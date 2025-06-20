import { GlobalConfig } from '@/types/config';
import { API_ENDPOINTS } from './api';
import { ConfigStore } from '@/lib/config';

// 获取授权头的辅助函数
const getAuthHeaders = () => {
  const session = typeof window !== "undefined" ? localStorage.getItem("session") : null;
  const sessionObj = session ? JSON.parse(session) : null;

  return {
    'Content-Type': 'application/json',
    'User-Agent': 'AgentFrontEnd/1.0',
    ...(sessionObj?.access_token && { "Authorization": `Bearer ${sessionObj.access_token}` }),
  };
};

export class ConfigService {
  // Save global configuration to backend
  async saveConfigToBackend(config: GlobalConfig): Promise<boolean> {
    try {
      const response = await fetch(API_ENDPOINTS.config.save, {
        method: 'POST',
        headers: {
          ...getAuthHeaders(),
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(config),
      });

      if (!response.ok) {
        const errorData = await response.json();
        console.error('保存配置失败:', errorData);
        return false;
      }

      const result = await response.json();
      return true;
    } catch (error) {
      console.error('保存配置请求异常:', error);
      return false;
    }
  }

  // Add: Load configuration from backend and write to localStorage
  async loadConfigToFrontend(): Promise<boolean> {
    try {
      const response = await fetch(API_ENDPOINTS.config.load, {
        method: 'GET',
        headers: {
          ...getAuthHeaders(),
          'Content-Type': 'application/json',
        },
      });
      if (!response.ok) {
        const errorData = await response.json();
        console.error('加载配置失败:', errorData);
        return false;
      }
      const result = await response.json();
      const config = result.config;
      if (config) {
        // Use the conversion function of configStore
        const frontendConfig = ConfigStore.transformBackend2Frontend(config);

        // Write to localStorage separately
        if (frontendConfig.app) localStorage.setItem('app', JSON.stringify(frontendConfig.app));
        if (frontendConfig.models) localStorage.setItem('model', JSON.stringify(frontendConfig.models));
        return true;
      }
      return false;
    } catch (error) {
      console.error('加载配置请求异常:', error);
      return false;
    }
  }
}

// Export singleton instance
export const configService = new ConfigService(); 