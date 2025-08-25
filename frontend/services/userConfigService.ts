import { API_ENDPOINTS } from './api';
import { fetchWithAuth, getAuthHeaders } from '@/lib/auth';
// @ts-ignore
const fetch = fetchWithAuth;

// 用户选中的知识库配置类型
export interface UserKnowledgeConfig {
  selectedKbNames: string[];
  selectedKbModels: string[];
  selectedKbSources: string[];
}

export class UserConfigService {
  // 获取用户选中的知识库列表
  async loadKnowledgeList(): Promise<UserKnowledgeConfig | null> {
    try {
      const response = await fetch(API_ENDPOINTS.tenantConfig.loadKnowledgeList, {
        method: 'GET',
        headers: getAuthHeaders(),
      });

      if (!response.ok) {
        return null;
      }

      const result = await response.json();
      if (result.status === 'success') {
        return result.content;
      }
      return null;
    } catch (error) {
      return null;
    }
  }

  // 更新用户选中的知识库列表
  async updateKnowledgeList(knowledgeList: string[]): Promise<boolean> {
    try {
      const response = await fetch(API_ENDPOINTS.tenantConfig.updateKnowledgeList, {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify({ knowledge_list: knowledgeList }),
      });

      if (!response.ok) {
        return false;
      }

      const result = await response.json();
      return result.status === 'success';
    } catch (error) {
      return false;
    }
  }
}

// 导出单例实例
export const userConfigService = new UserConfigService(); 