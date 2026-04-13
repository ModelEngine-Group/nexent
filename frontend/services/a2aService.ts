import i18n from 'i18next';
import log from '@/lib/logger';
import { API_ENDPOINTS, fetchWithErrorHandling } from './api';

const t = (key: string, options?: any): string => {
  return i18n.t(key, options) as string;
};

// =============================================================================
// Types
// =============================================================================

export interface A2AExternalAgent {
  id: number;
  name: string;
  description?: string;
  agent_url: string;
  version?: string;
  streaming?: boolean;
  supported_interfaces?: Record<string, any>[];
  source_type: 'url' | 'nacos';
  source_url?: string;
  nacos_config_id?: string;
  nacos_agent_name?: string;
  raw_card?: Record<string, any>;
  is_available: boolean;
  last_check_at?: string;
  last_check_result?: string;
  cached_at?: string;
  cache_expires_at?: string;
  create_time?: string;
}

export interface A2AExternalAgentRelation {
  id: number;
  local_agent_id: number;
  external_agent_id: number;
  is_enabled: boolean;
  external_agent_name?: string;
  external_agent_url?: string;
  create_time?: string;
}

export interface NacosConfig {
  id: number;
  config_id: string;
  name: string;
  nacos_addr: string;
  nacos_username?: string;
  namespace_id: string;
  description?: string;
  is_active: boolean;
  last_scan_at?: string;
}

export interface A2AServerAgent {
  id: number;
  agent_id: number;
  endpoint_id: string;
  user_id: string;
  tenant_id: string;
  name: string;
  description?: string;
  version?: string;
  agent_url?: string;
  streaming?: boolean;
  supported_interfaces?: Record<string, any>[];
  is_enabled: boolean;
  card_overrides?: Record<string, any>;
  raw_card?: Record<string, any>;
  published_at?: string;
  unpublished_at?: string;
}

export interface DiscoverFromUrlRequest {
  url: string;
  name?: string;
}

export interface DiscoverFromNacosRequest {
  nacos_config_id: string;
  agent_names: string[];
  namespace?: string;
}

export interface A2AServerSettings {
  is_enabled?: boolean;
  name?: string;
  description?: string;
  version?: string;
  agent_url?: string;
  streaming?: boolean;
  supported_interfaces?: Record<string, any>[];
  card_overrides?: Record<string, any>;
}

// =============================================================================
// A2A Client Service
// =============================================================================

export const a2aClientService = {
  // ---------------------------------------------------------------------------
  // External Agent Discovery
  // ---------------------------------------------------------------------------

  /**
   * Discover an external A2A agent from URL
   */
  async discoverFromUrl(request: DiscoverFromUrlRequest): Promise<{
    success: boolean;
    data?: A2AExternalAgent;
    message?: string;
  }> {
    try {
      const response = await fetchWithErrorHandling(API_ENDPOINTS.a2a.discoverUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(request),
      });
      const data = await response.json();

      if (response.ok && data.status === 'success') {
        return { success: true, data: data.data };
      }

      return { success: false, message: data.detail || t('a2a.service.discoverFailed') };
    } catch (error) {
      log.error('Failed to discover from URL:', error);
      return { success: false, message: t('a2a.service.discoverFailed') };
    }
  },

  /**
   * Discover external A2A agents from Nacos
   */
  async discoverFromNacos(request: DiscoverFromNacosRequest): Promise<{
    success: boolean;
    data?: A2AExternalAgent[];
    message?: string;
  }> {
    try {
      const response = await fetchWithErrorHandling(API_ENDPOINTS.a2a.discoverNacos, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(request),
      });
      const data = await response.json();

      if (response.ok && data.status === 'success') {
        return { success: true, data: data.data };
      }

      return { success: false, message: data.detail || t('a2a.service.discoverFailed') };
    } catch (error) {
      log.error('Failed to discover from Nacos:', error);
      return { success: false, message: t('a2a.service.discoverFailed') };
    }
  },

  // ---------------------------------------------------------------------------
  // External Agent Management
  // ---------------------------------------------------------------------------

  /**
   * List all external A2A agents
   */
  async listAgents(params?: {
    source_type?: 'url' | 'nacos';
    is_available?: boolean;
  }): Promise<{
    success: boolean;
    data?: A2AExternalAgent[];
    message?: string;
  }> {
    try {
      const queryParams = new URLSearchParams();
      if (params?.source_type) queryParams.append('source_type', params.source_type);
      if (params?.is_available !== undefined) queryParams.append('is_available', String(params.is_available));

      const url = queryParams.toString()
        ? `${API_ENDPOINTS.a2a.agents}?${queryParams.toString()}`
        : API_ENDPOINTS.a2a.agents;

      const response = await fetchWithErrorHandling(url);
      const data = await response.json();

      if (response.ok && data.status === 'success') {
        return { success: true, data: data.data };
      }

      return { success: false, message: data.detail || t('a2a.service.listFailed') };
    } catch (error) {
      log.error('Failed to list agents:', error);
      return { success: false, message: t('a2a.service.listFailed') };
    }
  },

  /**
   * Get a specific external agent
   */
  async getAgent(agentId: string): Promise<{
    success: boolean;
    data?: A2AExternalAgent;
    message?: string;
  }> {
    try {
      const response = await fetchWithErrorHandling(API_ENDPOINTS.a2a.agent(agentId));
      const data = await response.json();

      if (response.ok && data.status === 'success') {
        return { success: true, data: data.data };
      }

      return { success: false, message: data.detail || t('a2a.service.getFailed') };
    } catch (error) {
      log.error('Failed to get agent:', error);
      return { success: false, message: t('a2a.service.getFailed') };
    }
  },

  /**
   * Refresh an external agent's cached card
   */
  async refreshAgent(agentId: string): Promise<{
    success: boolean;
    data?: A2AExternalAgent;
    message?: string;
  }> {
    try {
      const response = await fetchWithErrorHandling(API_ENDPOINTS.a2a.agentRefresh(agentId), {
        method: 'POST',
      });
      const data = await response.json();

      if (response.ok && data.status === 'success') {
        return { success: true, data: data.data };
      }

      return { success: false, message: data.detail || t('a2a.service.refreshFailed') };
    } catch (error) {
      log.error('Failed to refresh agent:', error);
      return { success: false, message: t('a2a.service.refreshFailed') };
    }
  },

  /**
   * Delete an external agent
   */
  async deleteAgent(agentId: string): Promise<{
    success: boolean;
    message?: string;
  }> {
    try {
      const response = await fetchWithErrorHandling(API_ENDPOINTS.a2a.agent(agentId), {
        method: 'DELETE',
      });

      if (response.ok) {
        return { success: true, message: t('a2a.service.deleteSuccess') };
      }

      const data = await response.json();
      return { success: false, message: data.detail || t('a2a.service.deleteFailed') };
    } catch (error) {
      log.error('Failed to delete agent:', error);
      return { success: false, message: t('a2a.service.deleteFailed') };
    }
  },

  /**
   * Update the protocol type for an external agent
   */
  async updateAgentProtocol(agentId: string, protocolType: string): Promise<{
    success: boolean;
    data?: A2AExternalAgent;
    message?: string;
  }> {
    try {
      const response = await fetchWithErrorHandling(API_ENDPOINTS.a2a.agentProtocol(agentId), {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ protocol_type: protocolType }),
      });
      const data = await response.json();

      if (response.ok && data.status === 'success') {
        return { success: true, data: data.data };
      }

      return { success: false, message: data.detail || t('a2a.service.updateProtocolFailed') };
    } catch (error) {
      log.error('Failed to update agent protocol:', error);
      return { success: false, message: t('a2a.service.updateProtocolFailed') };
    }
  },

  // ---------------------------------------------------------------------------
  // External Agent Relations
  // ---------------------------------------------------------------------------

  /**
   * Add relation between local agent and external A2A agent
   */
  async addRelation(
    localAgentId: number,
    externalAgentId: number
  ): Promise<{
    success: boolean;
    data?: A2AExternalAgentRelation;
    message?: string;
  }> {
    try {
      const response = await fetchWithErrorHandling(API_ENDPOINTS.a2a.relations, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ local_agent_id: localAgentId, external_agent_id: externalAgentId }),
      });
      const data = await response.json();

      if (response.ok && data.status === 'success') {
        return { success: true, data: data.data };
      }

      return { success: false, message: data.detail || t('a2a.service.addRelationFailed') };
    } catch (error) {
      log.error('Failed to add relation:', error);
      return { success: false, message: t('a2a.service.addRelationFailed') };
    }
  },

  /**
   * Remove relation between local agent and external A2A agent
   */
  async removeRelation(
    localAgentId: number,
    externalAgentId: number
  ): Promise<{
    success: boolean;
    message?: string;
  }> {
    try {
      const response = await fetchWithErrorHandling(
        API_ENDPOINTS.a2a.relation(localAgentId, externalAgentId),
        { method: 'DELETE' }
      );

      if (response.ok) {
        return { success: true, message: t('a2a.service.removeRelationSuccess') };
      }

      const data = await response.json();
      return { success: false, message: data.detail || t('a2a.service.removeRelationFailed') };
    } catch (error) {
      log.error('Failed to remove relation:', error);
      return { success: false, message: t('a2a.service.removeRelationFailed') };
    }
  },

  /**
   * Get external sub-agents for a local agent
   */
  async getSubAgents(localAgentId: number): Promise<{
    success: boolean;
    data?: A2AExternalAgent[];
    message?: string;
  }> {
    try {
      const response = await fetchWithErrorHandling(API_ENDPOINTS.a2a.subAgents(localAgentId));
      const data = await response.json();

      if (response.ok && data.status === 'success') {
        return { success: true, data: data.data };
      }

      return { success: false, message: data.detail || t('a2a.service.getSubAgentsFailed') };
    } catch (error) {
      log.error('Failed to get sub-agents:', error);
      return { success: false, message: t('a2a.service.getSubAgentsFailed') };
    }
  },

  // ---------------------------------------------------------------------------
  // Nacos Config Management
  // ---------------------------------------------------------------------------

  /**
   * Create a Nacos config
   */
  async createNacosConfig(config: {
    name: string;
    nacos_addr: string;
    nacos_username?: string;
    nacos_password?: string;
    namespace_id?: string;
    description?: string;
  }): Promise<{
    success: boolean;
    data?: NacosConfig;
    message?: string;
  }> {
    try {
      const response = await fetchWithErrorHandling(API_ENDPOINTS.a2a.nacosConfigs, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config),
      });
      const data = await response.json();

      if (response.ok && data.status === 'success') {
        return { success: true, data: data.data };
      }

      return { success: false, message: data.detail || t('a2a.service.createNacosConfigFailed') };
    } catch (error) {
      log.error('Failed to create Nacos config:', error);
      return { success: false, message: t('a2a.service.createNacosConfigFailed') };
    }
  },

  /**
   * List Nacos configs
   */
  async listNacosConfigs(isActive?: boolean): Promise<{
    success: boolean;
    data?: NacosConfig[];
    message?: string;
  }> {
    try {
      const url = isActive !== undefined
        ? `${API_ENDPOINTS.a2a.nacosConfigs}?is_active=${isActive}`
        : API_ENDPOINTS.a2a.nacosConfigs;

      const response = await fetchWithErrorHandling(url);
      const data = await response.json();

      if (response.ok && data.status === 'success') {
        return { success: true, data: data.data };
      }

      return { success: false, message: data.detail || t('a2a.service.listNacosConfigsFailed') };
    } catch (error) {
      log.error('Failed to list Nacos configs:', error);
      return { success: false, message: t('a2a.service.listNacosConfigsFailed') };
    }
  },

  /**
   * Delete a Nacos config
   */
  async deleteNacosConfig(configId: string): Promise<{
    success: boolean;
    message?: string;
  }> {
    try {
      const response = await fetchWithErrorHandling(API_ENDPOINTS.a2a.nacosConfig(configId), {
        method: 'DELETE',
      });

      if (response.ok) {
        return { success: true, message: t('a2a.service.deleteNacosConfigSuccess') };
      }

      const data = await response.json();
      return { success: false, message: data.detail || t('a2a.service.deleteNacosConfigFailed') };
    } catch (error) {
      log.error('Failed to delete Nacos config:', error);
      return { success: false, message: t('a2a.service.deleteNacosConfigFailed') };
    }
  },

  // ---------------------------------------------------------------------------
  // A2A Server Management
  // ---------------------------------------------------------------------------

  /**
   * Enable A2A Server for an agent
   */
  async enableServer(
    agentId: number,
    settings?: A2AServerSettings
  ): Promise<{
    success: boolean;
    data?: A2AServerAgent;
    message?: string;
  }> {
    try {
      const response = await fetchWithErrorHandling(API_ENDPOINTS.a2a.serverAgentEnable(agentId), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(settings || {}),
      });
      const data = await response.json();

      if (response.ok && data.status === 'success') {
        return { success: true, data: data.data };
      }

      return { success: false, message: data.detail || t('a2a.service.enableServerFailed') };
    } catch (error) {
      log.error('Failed to enable A2A server:', error);
      return { success: false, message: t('a2a.service.enableServerFailed') };
    }
  },

  /**
   * Disable A2A Server for an agent
   */
  async disableServer(agentId: number): Promise<{
    success: boolean;
    message?: string;
  }> {
    try {
      const response = await fetchWithErrorHandling(API_ENDPOINTS.a2a.serverAgentDisable(agentId), {
        method: 'POST',
      });

      if (response.ok) {
        return { success: true, message: t('a2a.service.disableServerSuccess') };
      }

      const data = await response.json();
      return { success: false, message: data.detail || t('a2a.service.disableServerFailed') };
    } catch (error) {
      log.error('Failed to disable A2A server:', error);
      return { success: false, message: t('a2a.service.disableServerFailed') };
    }
  },

  /**
   * Get A2A Server settings for an agent
   */
  async getServerSettings(agentId: number): Promise<{
    success: boolean;
    data?: A2AServerAgent;
    message?: string;
  }> {
    try {
      const response = await fetchWithErrorHandling(API_ENDPOINTS.a2a.serverAgentSettings(agentId));
      const data = await response.json();

      if (response.ok && data.status === 'success') {
        return { success: true, data: data.data };
      }

      return { success: false, message: data.detail || t('a2a.service.getServerSettingsFailed') };
    } catch (error) {
      log.error('Failed to get server settings:', error);
      return { success: false, message: t('a2a.service.getServerSettingsFailed') };
    }
  },

  /**
   * Update A2A Server settings for an agent
   */
  async updateServerSettings(
    agentId: number,
    settings: A2AServerSettings
  ): Promise<{
    success: boolean;
    data?: A2AServerAgent;
    message?: string;
  }> {
    try {
      const response = await fetchWithErrorHandling(API_ENDPOINTS.a2a.serverAgentSettings(agentId), {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(settings),
      });
      const data = await response.json();

      if (response.ok && data.status === 'success') {
        return { success: true, data: data.data };
      }

      return { success: false, message: data.detail || t('a2a.service.updateServerSettingsFailed') };
    } catch (error) {
      log.error('Failed to update server settings:', error);
      return { success: false, message: t('a2a.service.updateServerSettingsFailed') };
    }
  },

  /**
   * List all A2A Server agents
   */
  async listServerAgents(): Promise<{
    success: boolean;
    data?: A2AServerAgent[];
    message?: string;
  }> {
    try {
      const response = await fetchWithErrorHandling(API_ENDPOINTS.a2a.serverAgents);
      const data = await response.json();

      if (response.ok && data.status === 'success') {
        return { success: true, data: data.data };
      }

      return { success: false, message: data.detail || t('a2a.service.listServerAgentsFailed') };
    } catch (error) {
      log.error('Failed to list server agents:', error);
      return { success: false, message: t('a2a.service.listServerAgentsFailed') };
    }
  },
};
