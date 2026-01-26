import { API_ENDPOINTS } from './api';
import { UserKnowledgeConfig, UpdateKnowledgeListRequest } from '../types/knowledgeBase';

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
  async updateKnowledgeList(request: UpdateKnowledgeListRequest): Promise<UserKnowledgeConfig | null> {
    try {
      const response = await fetch(
        API_ENDPOINTS.tenantConfig.updateKnowledgeList,
        {
          method: "POST",
          headers: getAuthHeaders(),
          body: JSON.stringify(request),
        }
      );

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
}

// Export singleton instance
export const userConfigService = new UserConfigService(); 