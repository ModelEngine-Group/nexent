// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { API_ENDPOINTS, fetchWithErrorHandling } from "@/services/api";
import { getAuthHeaders } from "@/lib/auth";
import type {
  AidpSensitiveWordItem,
  AidpSensitiveWordListResponse,
  AidpSensitiveWordPayload,
  AidpSensitiveWordUpdatePayload,
} from "@/ext_components/aidp/shared/types/sensitiveWord";

function buildUrl(
  base: string,
  params: Record<string, string | number | undefined>
): string {
  const url = new URL(base, globalThis.location.origin);
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") {
      url.searchParams.set(key, String(value));
    }
  }
  return url.toString();
}

/** Parse a response body that may legitimately be empty (200/204). */
async function readOptionalJson<T>(response: Response): Promise<T | null> {
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text) as T;
  } catch {
    return null;
  }
}

/**
 * Proxy client for one knowledge base's AIDP sensitive word dictionary.
 *
 * Every request goes through the Nexent backend; AIDP credentials never reach
 * the browser. The upstream path is scoped by the knowledge base id and keeps
 * AIDP's fixed `aidp` tenant namespace.
 */
class AidpSensitiveWordService {
  async list(
    kdsId: string,
    page: number = 1,
    pageSize: number = 10,
    keyword?: string,
    mode?: "BLACK" | "WHITE"
  ): Promise<AidpSensitiveWordListResponse> {
    const url = buildUrl(API_ENDPOINTS.aidpMgmt.sensitiveWords(kdsId), {
      page,
      page_size: pageSize,
      keyword: keyword?.trim() || undefined,
      mode,
    });
    const response = await fetchWithErrorHandling(url, {
      method: "GET",
      headers: getAuthHeaders(),
    });
    const result = await response.json();
    return {
      value: Array.isArray(result.value) ? result.value : [],
      next_link: typeof result.next_link === "string" ? result.next_link : null,
      total_count:
        typeof result.total_count === "number" ? result.total_count : 0,
    };
  }

  async get(
    kdsId: string,
    id: string,
    signal?: AbortSignal
  ): Promise<AidpSensitiveWordItem> {
    const response = await fetchWithErrorHandling(
      buildUrl(API_ENDPOINTS.aidpMgmt.sensitiveWord(kdsId, id), {}),
      { method: "GET", headers: getAuthHeaders(), signal }
    );
    return (await response.json()) as AidpSensitiveWordItem;
  }

  async create(
    kdsId: string,
    payload: AidpSensitiveWordPayload
  ): Promise<void> {
    await fetchWithErrorHandling(API_ENDPOINTS.aidpMgmt.sensitiveWords(kdsId), {
      method: "POST",
      headers: {
        ...getAuthHeaders(),
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });
  }

  async update(
    kdsId: string,
    id: string,
    payload: AidpSensitiveWordUpdatePayload
  ): Promise<void> {
    await fetchWithErrorHandling(
      buildUrl(API_ENDPOINTS.aidpMgmt.sensitiveWord(kdsId, id), {}),
      {
        method: "PATCH",
        headers: {
          ...getAuthHeaders(),
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      }
    );
  }

  /** AIDP deletes return 204 with no body, so the response is not parsed. */
  async remove(kdsId: string, id: string): Promise<void> {
    const response = await fetchWithErrorHandling(
      buildUrl(API_ENDPOINTS.aidpMgmt.sensitiveWord(kdsId, id), {}),
      { method: "DELETE", headers: getAuthHeaders() }
    );
    await readOptionalJson(response);
  }
}

const aidpSensitiveWordService = new AidpSensitiveWordService();
export default aidpSensitiveWordService;
