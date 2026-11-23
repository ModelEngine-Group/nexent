// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { API_ENDPOINTS, fetchWithErrorHandling } from "@/services/api";
import { getAuthHeaders } from "@/lib/auth";
import log from "@/lib/logger";
import type {
  AidpOntologyBinding,
  AidpOntologyBindingListResponse,
  AidpOntologyDomain,
  AidpOntologyDomainListResponse,
  AidpOntologyEntity,
  AidpOntologyEntityCreatePayload,
  AidpOntologyEntityListResponse,
  AidpOntologyEntityUpdatePayload,
  AidpOntologyAsyncAcknowledgment,
  AidpOntologyExportPayload,
  AidpOntologyExportResult,
  AidpOntologyImportResult,
  AidpOntologyJsonDocument,
  AidpOntologyMetadataField,
  AidpOntologyMetadataFieldListResponse,
  AidpOntologyRule,
  AidpOntologyRuleListResponse,
  AidpOntologyRulePayload,
  AidpOntologyTaskListResponse,
} from "../types/ontology";

type QueryValue = string | number | boolean | undefined | null;

const buildUrl = (
  base: string,
  params: Record<string, QueryValue> = {}
): string => {
  const url = new URL(base, globalThis.location.origin);
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      url.searchParams.set(key, String(value));
    }
  });
  return url.toString();
};

const jsonRequest = async <T>(
  url: string,
  init: RequestInit = {}
): Promise<T> => {
  const response = await fetchWithErrorHandling(url, {
    ...init,
    headers: {
      ...getAuthHeaders(),
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...(init.headers ?? {}),
    },
  });
  if (response.status === 204) return {} as T;
  return (await response.json()) as T;
};

class AidpOntologyService {
  listDomains(
    page = 1,
    pageSize = 20,
    search?: string
  ): Promise<AidpOntologyDomainListResponse> {
    return jsonRequest<AidpOntologyDomainListResponse>(
      buildUrl(API_ENDPOINTS.aidpMgmt.ontology.domains, {
        page,
        page_size: pageSize,
        search: search?.trim() || undefined,
      })
    );
  }

  createDomain(payload: {
    name: string;
    description: string;
  }): Promise<AidpOntologyDomain> {
    return jsonRequest<AidpOntologyDomain>(
      API_ENDPOINTS.aidpMgmt.ontology.domains,
      {
        method: "POST",
        body: JSON.stringify(payload),
      }
    );
  }

  getDomain(domainId: string): Promise<AidpOntologyDomain> {
    return jsonRequest<AidpOntologyDomain>(
      API_ENDPOINTS.aidpMgmt.ontology.domain(domainId)
    );
  }

  updateDomain(
    domainId: string,
    payload: { name?: string; description?: string }
  ): Promise<AidpOntologyDomain> {
    return jsonRequest<AidpOntologyDomain>(
      API_ENDPOINTS.aidpMgmt.ontology.domain(domainId),
      { method: "PATCH", body: JSON.stringify(payload) }
    );
  }

  deleteDomain(domainId: string): Promise<{ success: boolean }> {
    return jsonRequest<{ success: boolean }>(
      API_ENDPOINTS.aidpMgmt.ontology.domain(domainId),
      { method: "DELETE" }
    );
  }

  listEntities(
    domainId: string,
    page = 1,
    pageSize = 20,
    keyword?: string,
    kind?: "type" | "entity",
    signal?: AbortSignal
  ): Promise<AidpOntologyEntityListResponse> {
    return jsonRequest<AidpOntologyEntityListResponse>(
      buildUrl(API_ENDPOINTS.aidpMgmt.ontology.entities(domainId), {
        page,
        size: pageSize,
        keyword: keyword?.trim() || undefined,
        kind,
      }),
      { signal }
    );
  }

  createEntity(
    domainId: string,
    payload: AidpOntologyEntityCreatePayload
  ): Promise<AidpOntologyEntity> {
    return jsonRequest<AidpOntologyEntity>(
      API_ENDPOINTS.aidpMgmt.ontology.entities(domainId),
      { method: "POST", body: JSON.stringify(payload) }
    );
  }

  updateEntity(
    domainId: string,
    entityId: string,
    payload: AidpOntologyEntityUpdatePayload
  ): Promise<AidpOntologyEntity> {
    return jsonRequest<AidpOntologyEntity>(
      API_ENDPOINTS.aidpMgmt.ontology.entity(domainId, entityId),
      { method: "PATCH", body: JSON.stringify(payload) }
    );
  }

  deleteEntity(
    domainId: string,
    entityId: string
  ): Promise<{ success: boolean }> {
    return jsonRequest<{ success: boolean }>(
      API_ENDPOINTS.aidpMgmt.ontology.entity(domainId, entityId),
      { method: "DELETE" }
    );
  }

  listBindings(domainId: string): Promise<AidpOntologyBindingListResponse> {
    return jsonRequest<AidpOntologyBindingListResponse>(
      API_ENDPOINTS.aidpMgmt.ontology.bindings(domainId)
    );
  }

  listAllBindings(): Promise<AidpOntologyBindingListResponse> {
    return jsonRequest<AidpOntologyBindingListResponse>(
      API_ENDPOINTS.aidpMgmt.ontology.allBindings
    );
  }

  createBinding(
    domainId: string,
    kdsId: string
  ): Promise<{
    binding_id?: string | null;
    od_id: string;
    kds_id: string;
    unchanged?: boolean;
  }> {
    return jsonRequest<{
      binding_id?: string | null;
      od_id: string;
      kds_id: string;
      unchanged?: boolean;
    }>(API_ENDPOINTS.aidpMgmt.ontology.bindings(domainId), {
      method: "PUT",
      body: JSON.stringify({ kb_id: kdsId }),
    });
  }

  deleteBinding(
    domainId: string,
    kdsId: string
  ): Promise<{
    success: boolean;
    accepted?: boolean;
    task_id?: string | null;
    task_type?: string | null;
  }> {
    return jsonRequest<{
      success: boolean;
      accepted?: boolean;
      task_id?: string | null;
      task_type?: string | null;
    }>(API_ENDPOINTS.aidpMgmt.ontology.unbind(domainId, kdsId), {
      method: "DELETE",
    });
  }

  listTasks(
    page = 1,
    pageSize = 20,
    taskType?: string
  ): Promise<AidpOntologyTaskListResponse> {
    return jsonRequest<AidpOntologyTaskListResponse>(
      buildUrl(API_ENDPOINTS.aidpMgmt.ontology.tasks, {
        page,
        page_size: pageSize,
        task_type: taskType || undefined,
      })
    );
  }

  getKnowledgeBaseBinding(
    kdsId: string,
    signal?: AbortSignal
  ): Promise<{ binding: AidpOntologyBinding | null }> {
    return jsonRequest<{ binding: AidpOntologyBinding | null }>(
      API_ENDPOINTS.aidpMgmt.ontology.bindingByKb(kdsId),
      { signal }
    );
  }

  listMetadataFields(
    domainId: string,
    page = 1,
    pageSize = 10,
    search?: string,
    signal?: AbortSignal
  ): Promise<AidpOntologyMetadataFieldListResponse> {
    return jsonRequest<AidpOntologyMetadataFieldListResponse>(
      buildUrl(API_ENDPOINTS.aidpMgmt.ontology.metadataFields(domainId), {
        page,
        page_size: pageSize,
        search: search?.trim() || undefined,
      }),
      { signal }
    );
  }

  createMetadataField(
    domainId: string,
    payload: { field_name: string; field_type: string }
  ): Promise<AidpOntologyMetadataField> {
    return jsonRequest<AidpOntologyMetadataField>(
      API_ENDPOINTS.aidpMgmt.ontology.metadataFields(domainId),
      { method: "POST", body: JSON.stringify(payload) }
    );
  }

  renameMetadataField(
    domainId: string,
    fieldRef: string | number,
    newFieldName: string
  ): Promise<
    AidpOntologyMetadataField & {
      accepted?: boolean;
      task_id?: string | null;
      status?: string | null;
    }
  > {
    return jsonRequest<AidpOntologyMetadataField>(
      API_ENDPOINTS.aidpMgmt.ontology.metadataField(domainId, fieldRef),
      {
        method: "PATCH",
        body: JSON.stringify({ new_field_name: newFieldName }),
      }
    );
  }

  deleteMetadataField(
    domainId: string,
    fieldRef: string | number
  ): Promise<{
    success?: boolean;
    deleted?: boolean | null;
    accepted?: boolean;
    task_id?: string | null;
    status?: string | null;
    failed_kbs?: string[];
    dropped_kbs?: string[];
    partial_failure?: boolean;
  }> {
    return jsonRequest<{
      success?: boolean;
      deleted?: boolean | null;
      accepted?: boolean;
      task_id?: string | null;
      status?: string | null;
      failed_kbs?: string[];
      dropped_kbs?: string[];
      partial_failure?: boolean;
    }>(API_ENDPOINTS.aidpMgmt.ontology.metadataField(domainId, fieldRef), {
      method: "DELETE",
    });
  }

  batchUnbindMetadata(
    domainId: string,
    metadataIds: Array<string | number>
  ): Promise<AidpOntologyAsyncAcknowledgment> {
    return jsonRequest<AidpOntologyAsyncAcknowledgment>(
      API_ENDPOINTS.aidpMgmt.ontology.metadataBatchUnbind(domainId),
      {
        method: "POST",
        body: JSON.stringify({ metadata_ids: metadataIds.map(String) }),
      }
    );
  }

  listRules(
    domainId: string,
    page = 1,
    size = 20,
    enabledOnly = false
  ): Promise<AidpOntologyRuleListResponse> {
    return jsonRequest<AidpOntologyRuleListResponse>(
      buildUrl(API_ENDPOINTS.aidpMgmt.ontology.rules(domainId), {
        page,
        size,
        enabled_only: enabledOnly || undefined,
      })
    );
  }

  countRules(domainId: string): Promise<{ count: number }> {
    return jsonRequest<{ count: number }>(
      API_ENDPOINTS.aidpMgmt.ontology.ruleCount(domainId)
    );
  }

  getRule(domainId: string, ruleId: string): Promise<AidpOntologyRule> {
    return jsonRequest<AidpOntologyRule>(
      API_ENDPOINTS.aidpMgmt.ontology.rule(domainId, ruleId)
    );
  }

  createRule(
    domainId: string,
    payload: AidpOntologyRulePayload
  ): Promise<AidpOntologyRule> {
    return jsonRequest<AidpOntologyRule>(
      API_ENDPOINTS.aidpMgmt.ontology.rules(domainId),
      { method: "PUT", body: JSON.stringify(payload) }
    );
  }

  updateRule(
    domainId: string,
    ruleId: string,
    payload: AidpOntologyRulePayload
  ): Promise<AidpOntologyRule> {
    return jsonRequest<AidpOntologyRule>(
      API_ENDPOINTS.aidpMgmt.ontology.rule(domainId, ruleId),
      { method: "PATCH", body: JSON.stringify(payload) }
    );
  }

  deleteRule(domainId: string, ruleId: string): Promise<{ success: boolean }> {
    return jsonRequest<{ success: boolean }>(
      API_ENDPOINTS.aidpMgmt.ontology.rule(domainId, ruleId),
      { method: "DELETE" }
    );
  }

  exportDomain(
    domainId: string,
    payload: AidpOntologyExportPayload
  ): Promise<AidpOntologyExportResult> {
    return jsonRequest<AidpOntologyExportResult>(
      API_ENDPOINTS.aidpMgmt.ontology.export(domainId),
      { method: "POST", body: JSON.stringify(payload) }
    );
  }

  importDomain(
    domainId: string,
    fileName: string,
    document: AidpOntologyJsonDocument
  ): Promise<AidpOntologyImportResult> {
    return jsonRequest<AidpOntologyImportResult>(
      API_ENDPOINTS.aidpMgmt.ontology.import(domainId),
      {
        method: "POST",
        body: JSON.stringify({ file_name: fileName, document }),
      }
    );
  }

  /** Download a synchronous export payload as a JSON file. */
  downloadExport(result: {
    data: Record<string, unknown>;
    filename: string;
  }): void {
    try {
      const blob = new Blob([JSON.stringify(result.data, null, 2)], {
        type: "application/json;charset=utf-8",
      });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = result.filename || "ontology.json";
      document.body.appendChild(anchor);
      anchor.click();
      document.body.removeChild(anchor);
      URL.revokeObjectURL(url);
    } catch (error) {
      log.error("Failed to download ontology export", error);
      throw error;
    }
  }
}

export const aidpOntologyService = new AidpOntologyService();

export default aidpOntologyService;
