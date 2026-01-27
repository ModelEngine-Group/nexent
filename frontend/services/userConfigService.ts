import { API_ENDPOINTS } from './api';
import { UserKnowledgeConfig } from '../types/knowledgeBase';

import { fetchWithAuth, getAuthHeaders } from '@/lib/auth';
// @ts-ignore
const fetch = fetchWithAuth;

export class UserConfigService {
  // Get user selected knowledge base list
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

  // Update user selected knowledge base list
  async updateKnowledgeList(knowledgeList: string[]): Promise<boolean> {
    try {
      const response = await fetch(
        API_ENDPOINTS.tenantConfig.updateKnowledgeList,
        {
          method: "POST",
          headers: getAuthHeaders(),
          body: JSON.stringify(knowledgeList),
        }
      );

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

// Export singleton instance
export const userConfigService = new UserConfigService(); 