"use client";

import { API_ENDPOINTS } from "./api";
import { STATUS_CODES } from "@/const/auth";
import { getAuthHeaders } from "@/lib/auth";

import type {
  AgentEvaluationCase,
  AgentEvaluationRun,
  EvaluationSet,
  EvaluationSetCase,
} from "@/types/agentEvaluation";

export const evaluationService = {
  uploadEvaluationSetExcel: async (params: {
    name: string;
    description?: string;
    file: File;
  }): Promise<EvaluationSet> => {
    const formData = new FormData();
    formData.append("name", params.name);
    if (params.description) formData.append("description", params.description);
    formData.append("file", params.file);

    const resp = await fetch(API_ENDPOINTS.evaluationSets.upload, {
      method: "POST",
      headers: {
        "User-Agent": "AgentFrontEnd/1.0",
      },
      body: formData,
    });

    const result = await resp.json();
    if (resp.status !== STATUS_CODES.SUCCESS) {
      throw new Error(result.detail || result.message || "Upload evaluation set failed");
    }
    return result.data;
  },

  downloadEvaluationSetTemplate: async (): Promise<Blob> => {
    const resp = await fetch(API_ENDPOINTS.evaluationSets.template, {
      headers: getAuthHeaders(),
    });
    if (resp.status !== STATUS_CODES.SUCCESS) {
      let msg = "Download template failed";
      try {
        const result = await resp.json();
        msg = result.detail || result.message || msg;
      } catch {
        // ignore
      }
      throw new Error(msg);
    }
    return await resp.blob();
  },

  createEvaluationSet: async (params: {
    name: string;
    description?: string;
    source_filename?: string;
    jsonl_text: string;
  }): Promise<EvaluationSet> => {
    const resp = await fetch(API_ENDPOINTS.evaluationSets.create, {
      method: "POST",
      headers: getAuthHeaders(),
      body: JSON.stringify(params),
    });
    const result = await resp.json();
    if (resp.status !== STATUS_CODES.SUCCESS) {
      throw new Error(result.detail || result.message || "Create evaluation set failed");
    }
    return result.data;
  },

  listEvaluationSets: async (params?: { limit?: number; offset?: number }): Promise<EvaluationSet[]> => {
    const url = new URL(API_ENDPOINTS.evaluationSets.list, window.location.origin);
    if (params?.limit != null) url.searchParams.set("limit", String(params.limit));
    if (params?.offset != null) url.searchParams.set("offset", String(params.offset));

    const resp = await fetch(url.toString(), {
      headers: getAuthHeaders(),
    });
    const result = await resp.json();
    if (resp.status !== STATUS_CODES.SUCCESS) {
      throw new Error(result.detail || result.message || "List evaluation sets failed");
    }
    return result.data || [];
  },

  listEvaluationSetCases: async (evaluationSetId: number, params?: { limit?: number; offset?: number }): Promise<EvaluationSetCase[]> => {
    const url = new URL(API_ENDPOINTS.evaluationSets.cases(evaluationSetId), window.location.origin);
    if (params?.limit != null) url.searchParams.set("limit", String(params.limit));
    if (params?.offset != null) url.searchParams.set("offset", String(params.offset));

    const resp = await fetch(url.toString(), {
      headers: getAuthHeaders(),
    });
    const result = await resp.json();
    if (resp.status !== STATUS_CODES.SUCCESS) {
      throw new Error(result.detail || result.message || "List evaluation set cases failed");
    }
    return result.data || [];
  },

  createAgentEvaluation: async (params: {
    agent_id: number;
    evaluation_set_id: number;
    judge_model_id: number;
  }): Promise<AgentEvaluationRun> => {
    const resp = await fetch(API_ENDPOINTS.agentEvaluations.create, {
      method: "POST",
      headers: getAuthHeaders(),
      body: JSON.stringify(params),
    });
    const result = await resp.json();
    if (resp.status !== STATUS_CODES.SUCCESS) {
      throw new Error(result.detail || result.message || "Create evaluation failed");
    }
    return result.data;
  },

  listAgentEvaluationsByAgent: async (agentId: number, params?: { limit?: number; offset?: number }): Promise<AgentEvaluationRun[]> => {
    const url = new URL(API_ENDPOINTS.agentEvaluations.listByAgent, window.location.origin);
    url.searchParams.set("agent_id", String(agentId));
    if (params?.limit != null) url.searchParams.set("limit", String(params.limit));
    if (params?.offset != null) url.searchParams.set("offset", String(params.offset));

    const resp = await fetch(url.toString(), { headers: getAuthHeaders() });
    const result = await resp.json();
    if (resp.status !== STATUS_CODES.SUCCESS) {
      throw new Error(result.detail || result.message || "List evaluations failed");
    }
    return result.data || [];
  },

  getAgentEvaluation: async (evaluationId: number): Promise<AgentEvaluationRun> => {
    const resp = await fetch(API_ENDPOINTS.agentEvaluations.detail(evaluationId), {
      headers: getAuthHeaders(),
    });
    const result = await resp.json();
    if (resp.status !== STATUS_CODES.SUCCESS) {
      throw new Error(result.detail || result.message || "Get evaluation failed");
    }
    return result.data;
  },

  downloadEvaluationReport: async (evaluationId: number): Promise<Blob> => {
    const resp = await fetch(API_ENDPOINTS.agentEvaluations.report(evaluationId), {
      headers: getAuthHeaders(),
    });
    if (!resp.ok) {
      let msg = "Download report failed";
      try {
        const result = await resp.json();
        msg = result.detail || result.message || msg;
      } catch {
        // ignore
      }
      throw new Error(msg);
    }
    return await resp.blob();
  },

  listAgentEvaluationCases: async (evaluationId: number, params?: { limit?: number; offset?: number }): Promise<AgentEvaluationCase[]> => {
    const url = new URL(API_ENDPOINTS.agentEvaluations.cases(evaluationId), window.location.origin);
    if (params?.limit != null) url.searchParams.set("limit", String(params.limit));
    if (params?.offset != null) url.searchParams.set("offset", String(params.offset));

    const resp = await fetch(url.toString(), { headers: getAuthHeaders() });
    const result = await resp.json();
    if (resp.status !== STATUS_CODES.SUCCESS) {
      throw new Error(result.detail || result.message || "List evaluation cases failed");
    }
    return result.data || [];
  },
};
