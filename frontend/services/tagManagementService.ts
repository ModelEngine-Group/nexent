/**
 * Typed API client for the unified tag management service.
 *
 * Library management endpoints require the tenant admin TAG_LIBRARY MANAGE
 * permission; assignment endpoints use the caller's authenticated context.
 */

import { getAuthHeaders } from "@/lib/auth";
import { API_BASE_URL, fetchWithErrorHandling } from "@/services/api";
import {
  clearCachedAssignmentsByResource,
  getCachedAssignmentPromise,
  mergeAssignmentCacheKey,
} from "@/services/tagAssignmentCache";
import type {
  TagAssignment,
  TagAssignmentBulkOutcome,
  TagAssignmentBulkReplacePayload,
  TagAssignmentReplacePayload,
  TagDefinition,
  TagDefinitionCreatePayload,
  TagDefinitionUpdatePayload,
  TagDefinitionUsage,
  TagDeleteResult,
  TagDocumentPredicate,
  TagDocumentBatchStatusEntry,
  TagDocumentProvider,
  TagLegacyFlatTagsProjection,
  TagLibrary,
  TagOrderUpdatePayload,
  TagProjectionStatusInfo,
  TagResourceFilterResult,
  TagResourcePredicate,
  TagStatusUpdatePayload,
  TagValue,
  TagValueCreatePayload,
  TagValueUpdatePayload,
  TagValueUsage,
} from "@/types/tagManagement";

const TAG_ENDPOINT = `${API_BASE_URL}/tag-libraries`;

async function requestJson<T>(
  url: string,
  options: RequestInit = {}
): Promise<T> {
  const response = await fetchWithErrorHandling(url, {
    headers: getAuthHeaders(),
    ...options,
  });
  return (await response.json()) as T;
}

function jsonBody(body: unknown): { body: string } {
  return { body: JSON.stringify(body) };
}

export const tagManagementApi = {
  listLibraries: () => requestJson<TagLibrary[]>(TAG_ENDPOINT),

  listDefinitions: (bucketId: number) =>
    requestJson<TagDefinition[]>(`${TAG_ENDPOINT}/${bucketId}/definitions`),

  createDefinition: (bucketId: number, payload: TagDefinitionCreatePayload) =>
    requestJson<TagDefinition>(`${TAG_ENDPOINT}/${bucketId}/definitions`, {
      method: "POST",
      ...jsonBody(payload),
    }),

  updateDefinition: (
    bucketId: number,
    definitionId: number,
    payload: TagDefinitionUpdatePayload
  ) =>
    requestJson<TagDefinition>(
      `${TAG_ENDPOINT}/${bucketId}/definitions/${definitionId}`,
      { method: "PATCH", ...jsonBody(payload) }
    ),

  updateDefinitionStatus: (
    bucketId: number,
    definitionId: number,
    payload: TagStatusUpdatePayload
  ) =>
    requestJson<TagDefinition>(
      `${TAG_ENDPOINT}/${bucketId}/definitions/${definitionId}/status`,
      { method: "PATCH", ...jsonBody(payload) }
    ),

  updateDefinitionOrder: (
    bucketId: number,
    definitionId: number,
    payload: TagOrderUpdatePayload
  ) =>
    requestJson<TagDefinition>(
      `${TAG_ENDPOINT}/${bucketId}/definitions/${definitionId}/order`,
      { method: "PATCH", ...jsonBody(payload) }
    ),

  moveDefinitionToTop: (bucketId: number, definitionId: number) =>
    requestJson<TagDefinition>(
      `${TAG_ENDPOINT}/${bucketId}/definitions/${definitionId}/top`,
      { method: "PATCH" }
    ),

  getDefinitionUsage: (bucketId: number, definitionId: number) =>
    requestJson<TagDefinitionUsage>(
      `${TAG_ENDPOINT}/${bucketId}/definitions/${definitionId}/usage`
    ),

  deleteDefinition: (bucketId: number, definitionId: number) =>
    requestJson<TagDeleteResult>(
      `${TAG_ENDPOINT}/${bucketId}/definitions/${definitionId}`,
      { method: "DELETE" }
    ),

  createValue: (
    bucketId: number,
    definitionId: number,
    payload: TagValueCreatePayload
  ) =>
    requestJson<TagValue>(
      `${TAG_ENDPOINT}/${bucketId}/definitions/${definitionId}/values`,
      { method: "POST", ...jsonBody(payload) }
    ),

  updateValue: (
    bucketId: number,
    definitionId: number,
    valueId: number,
    payload: TagValueUpdatePayload
  ) =>
    requestJson<TagValue>(
      `${TAG_ENDPOINT}/${bucketId}/definitions/${definitionId}/values/${valueId}`,
      { method: "PATCH", ...jsonBody(payload) }
    ),

  updateValueStatus: (
    bucketId: number,
    definitionId: number,
    valueId: number,
    payload: TagStatusUpdatePayload
  ) =>
    requestJson<TagValue>(
      `${TAG_ENDPOINT}/${bucketId}/definitions/${definitionId}/values/${valueId}/status`,
      { method: "PATCH", ...jsonBody(payload) }
    ),

  updateValueOrder: (
    bucketId: number,
    definitionId: number,
    valueId: number,
    payload: TagOrderUpdatePayload
  ) =>
    requestJson<TagValue>(
      `${TAG_ENDPOINT}/${bucketId}/definitions/${definitionId}/values/${valueId}/order`,
      { method: "PATCH", ...jsonBody(payload) }
    ),

  getValueUsage: (bucketId: number, definitionId: number, valueId: number) =>
    requestJson<TagValueUsage>(
      `${TAG_ENDPOINT}/${bucketId}/definitions/${definitionId}/values/${valueId}/usage`
    ),

  deleteValue: (bucketId: number, definitionId: number, valueId: number) =>
    requestJson<TagDeleteResult>(
      `${TAG_ENDPOINT}/${bucketId}/definitions/${definitionId}/values/${valueId}`,
      { method: "DELETE" }
    ),

  getAssignments: (
    resourceType: string,
    resourceId: string,
    options: { provider?: string | null; knowledgeBaseId?: string | null } = {}
  ) => {
    const search = new URLSearchParams();
    if (options.provider) search.set("provider", options.provider);
    if (options.knowledgeBaseId)
      search.set("knowledge_base_id", options.knowledgeBaseId);
    const query = search.toString();
    const cacheKey = mergeAssignmentCacheKey(resourceType, resourceId, query);
    return getCachedAssignmentPromise(
      cacheKey,
      () =>
        requestJson<TagAssignment>(
          `${TAG_ENDPOINT}/assignments/${resourceType}/${encodeURIComponent(resourceId)}${query ? `?${query}` : ""}`
        )
    );
  },

  replaceAssignments: (
    resourceType: string,
    resourceId: string,
    payload: TagAssignmentReplacePayload,
    options: { provider?: string | null; knowledgeBaseId?: string | null } = {}
  ) => {
    const search = new URLSearchParams();
    if (options.provider) search.set("provider", options.provider);
    if (options.knowledgeBaseId)
      search.set("knowledge_base_id", options.knowledgeBaseId);
    const query = search.toString();
    const url =
      `${TAG_ENDPOINT}/assignments/${resourceType}/${encodeURIComponent(resourceId)}` +
      (query ? `?${query}` : "");
    return requestJson<TagAssignment>(url, {
      method: "PUT",
      ...jsonBody(payload),
    }).then((result) => {
      clearCachedAssignmentsByResource(resourceType, resourceId);
      return result;
    });
  },

  replaceAssignmentsBulk: (
    resourceType: string,
    payload: TagAssignmentBulkReplacePayload
  ) =>
    requestJson<TagAssignmentBulkOutcome[]>(
      `${TAG_ENDPOINT}/assignments/${resourceType}/bulk`,
      { method: "PUT", ...jsonBody(payload) }
    ),

  getProjectionStatus: (
    resourceType: string,
    resourceId: string,
    options: { provider: string; knowledgeBaseId: string }
  ) => {
    const search = new URLSearchParams({
      provider: options.provider,
      knowledge_base_id: options.knowledgeBaseId,
    });
    return requestJson<TagProjectionStatusInfo>(
      `${TAG_ENDPOINT}/assignments/${resourceType}/${encodeURIComponent(resourceId)}/projection-status?${search.toString()}`
    );
  },

  getDocumentBatchStatus: (
    options: {
      provider: string;
      knowledgeBaseId: string;
      documentIds: string[];
    },
    predicates: TagDocumentPredicate[] = []
  ) => {
    const search = new URLSearchParams({
      provider: options.provider,
      knowledge_base_id: options.knowledgeBaseId,
    });
    return requestJson<TagDocumentBatchStatusEntry[]>(
      `${TAG_ENDPOINT}/documents/batch-status?${search.toString()}`,
      {
        method: "POST",
        ...jsonBody({
          document_ids: options.documentIds,
          predicates,
        }),
      }
    );
  },

  getLegacyFlatTags: (
    resourceType: string,
    resourceId: string,
    options: { provider?: string | null; knowledgeBaseId?: string | null } = {}
  ) => {
    const search = new URLSearchParams();
    if (options.provider) search.set("provider", options.provider);
    if (options.knowledgeBaseId)
      search.set("knowledge_base_id", options.knowledgeBaseId);
    const query = search.toString();
    return requestJson<TagLegacyFlatTagsProjection>(
      `${TAG_ENDPOINT}/assignments/${resourceType}/${encodeURIComponent(resourceId)}/compatibility/flat-tags${query ? `?${query}` : ""}`
    );
  },

  /**
   * Narrow an already-authorized non-document resource id set by tag predicates.
   * The caller must supply ids its own list flow has already authorized; the
   * service only intersects that set with resources matching every predicate.
   * Returns the subset of resource ids that match.
   */
  filterResourceIds: (
    resourceType: string,
    resourceIds: string[],
    predicates: TagResourcePredicate[] = []
  ) =>
    requestJson<TagResourceFilterResult>(
      `${TAG_ENDPOINT}/assignments/${resourceType}/filter`,
      {
        method: "POST",
        ...jsonBody({ resource_ids: resourceIds, predicates }),
      }
    ),
};

export function buildDocumentPredicate(
  definitionId: number,
  valueIds: number[]
): TagDocumentPredicate {
  return { definition_id: definitionId, value_ids: valueIds };
}

export function buildResourcePredicate(
  definitionId: number,
  valueIds: number[]
): TagResourcePredicate {
  return { definition_id: definitionId, value_ids: valueIds };
}
