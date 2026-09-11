import { API_BASE_URL, fetchWithErrorHandling } from "./api";
import { getAuthHeaders } from "@/lib/auth";
import log from "@/lib/logger";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ProviderConfig {
  provider_config_id: number;
  tenant_id: string;
  provider_name: string;
  connection_type: "plugin";
  enabled: boolean;
  timeout_seconds: number;
  last_error_code: string | null;
  params: Record<string, string>;
  create_time: string;
  update_time: string;
}

export interface ProviderConfigCreate {
  provider_name: string;
  connection_type: "plugin";
  enabled?: boolean;
  timeout_seconds?: number;
  params: Record<string, string>;
}

export interface ProviderConfigUpdate {
  provider_name?: string;
  enabled?: boolean;
  timeout_seconds?: number;
  params?: Record<string, string>;
}

export interface ConfigSchemaField {
  key: string;
  label: string;
  type: "string" | "secret" | "number" | "boolean" | "select";
  required?: boolean;
  default?: unknown;
  options?: { label: string; value: string }[];
}

export interface PluginInfo {
  name: string;
  version: string;
  description: string;
  implements: string[];
  config_schema: ConfigSchemaField[];
}

// ---------------------------------------------------------------------------
// Endpoint helpers (kept local to avoid modifying api.ts)
// ---------------------------------------------------------------------------

const PROVIDER_BASE = `${API_BASE_URL}/memory/providers`;
const PLUGIN_BASE = `${API_BASE_URL}/memory/provider-plugins`;

// ---------------------------------------------------------------------------
// Unified JSON request helper
// ---------------------------------------------------------------------------

async function requestJson<T>(url: string, options: RequestInit = {}): Promise<T> {
  const response = await fetchWithErrorHandling(url, {
    ...options,
    headers: {
      ...getAuthHeaders(),
      ...(options.headers ?? {}),
    },
  });
  return response.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// Provider CRUD
// ---------------------------------------------------------------------------

export async function listProviders(): Promise<ProviderConfig[]> {
  try {
    const data = await requestJson<{ items: ProviderConfig[]; count: number }>(PROVIDER_BASE, {
      method: "GET",
    });
    return data.items;
  } catch (e) {
    log.error("listProviders error", e);
    throw e;
  }
}

export async function getProvider(providerId: number): Promise<ProviderConfig> {
  try {
    return await requestJson<ProviderConfig>(`${PROVIDER_BASE}/${providerId}`, {
      method: "GET",
    });
  } catch (e) {
    log.error("getProvider error", e);
    throw e;
  }
}

export async function createProvider(
  data: ProviderConfigCreate
): Promise<ProviderConfig> {
  try {
    return await requestJson<ProviderConfig>(PROVIDER_BASE, {
      method: "POST",
      body: JSON.stringify(data),
    });
  } catch (e) {
    log.error("createProvider error", e);
    throw e;
  }
}

export async function updateProvider(
  providerId: number,
  data: ProviderConfigUpdate
): Promise<ProviderConfig> {
  try {
    return await requestJson<ProviderConfig>(
      `${PROVIDER_BASE}/${providerId}`,
      {
        method: "PUT",
        body: JSON.stringify(data),
      }
    );
  } catch (e) {
    log.error("updateProvider error", e);
    throw e;
  }
}

export async function deleteProvider(providerId: number): Promise<void> {
  try {
    await fetchWithErrorHandling(`${PROVIDER_BASE}/${providerId}`, {
      method: "DELETE",
      headers: getAuthHeaders(),
    });
  } catch (e) {
    log.error("deleteProvider error", e);
    throw e;
  }
}

// ---------------------------------------------------------------------------
// Test endpoints
// ---------------------------------------------------------------------------

export async function testSearch(
  providerId: number,
  query: string,
  topK?: number
): Promise<unknown> {
  try {
    return await requestJson(
      `${PROVIDER_BASE}/${providerId}/test-search`,
      {
        method: "POST",
        body: JSON.stringify({ query, top_k: topK }),
      }
    );
  } catch (e) {
    log.error("testSearch error", e);
    throw e;
  }
}

export async function testIngest(
  providerId: number,
  units: unknown[]
): Promise<unknown> {
  try {
    return await requestJson(
      `${PROVIDER_BASE}/${providerId}/test-ingest`,
      {
        method: "POST",
        body: JSON.stringify({ units }),
      }
    );
  } catch (e) {
    log.error("testIngest error", e);
    throw e;
  }
}

// ---------------------------------------------------------------------------
// Plugin discovery
// ---------------------------------------------------------------------------

export async function listPlugins(): Promise<PluginInfo[]> {
  try {
    const data = await requestJson<{ items: PluginInfo[]; count: number }>(PLUGIN_BASE, {
      method: "GET",
    });
    return data.items;
  } catch (e) {
    log.error("listPlugins error", e);
    throw e;
  }
}
