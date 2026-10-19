// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { getAuthHeaders } from "@/lib/auth";
import type {
  ConversationModelPreferenceView,
  ProfileListRequest,
  ProfileListResponse,
  ProfileProtocolsResponse,
  ModelProfileDraftRequest,
  ModelProfileDraftResponse,
  ModelOutletCreateRequest,
  ModelOutletResponse,
  ModelOutletPatchRequest,
  ModelOutletValidationRequest,
  ModelOutletValidationResponse,
} from "@/types/modelProfile";

import { API_ENDPOINTS, fetchWithErrorHandling } from "./api";

export async function listModelProfiles(
  request: ProfileListRequest = {},
  signal?: AbortSignal
): Promise<ProfileListResponse> {
  const response = await fetchWithErrorHandling(
    API_ENDPOINTS.model.modelProfiles(request),
    {
      headers: getAuthHeaders(),
      signal,
    }
  );
  return (await response.json()).data;
}

export async function listProviderProfiles(
  request: Omit<ProfileListRequest, "family"> = {},
  signal?: AbortSignal
): Promise<ProfileListResponse> {
  const response = await fetchWithErrorHandling(
    API_ENDPOINTS.model.providerProfiles(request),
    {
      headers: getAuthHeaders(),
      signal,
    }
  );
  return (await response.json()).data;
}

export async function listProfileProtocols(
  signal?: AbortSignal
): Promise<ProfileProtocolsResponse> {
  const response = await fetchWithErrorHandling(
    API_ENDPOINTS.model.profileProtocols,
    {
      headers: getAuthHeaders(),
      signal,
    }
  );
  return (await response.json()).data;
}

export async function previewModelProfile(
  request: ModelProfileDraftRequest,
  signal?: AbortSignal
): Promise<ModelProfileDraftResponse> {
  const response = await fetchWithErrorHandling(
    API_ENDPOINTS.model.profilePreviews,
    {
      method: "POST",
      headers: { ...getAuthHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify(request),
      signal,
    }
  );
  return (await response.json()).data;
}

export async function createModelOutlet(
  request: ModelOutletCreateRequest
): Promise<ModelOutletResponse> {
  const response = await fetchWithErrorHandling(API_ENDPOINTS.model.outlets, {
    method: "POST",
    headers: { ...getAuthHeaders(), "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  return (await response.json()).data;
}

export async function getModelOutlet(
  modelId: number,
  signal?: AbortSignal
): Promise<ModelOutletResponse> {
  const response = await fetchWithErrorHandling(
    API_ENDPOINTS.model.outlet(modelId),
    {
      headers: getAuthHeaders(),
      signal,
    }
  );
  return (await response.json()).data;
}

export async function updateModelOutlet(
  modelId: number,
  request: ModelOutletPatchRequest
): Promise<ModelOutletResponse> {
  const response = await fetchWithErrorHandling(
    API_ENDPOINTS.model.outlet(modelId),
    {
      method: "PATCH",
      headers: { ...getAuthHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify(request),
    }
  );
  return (await response.json()).data;
}

export async function validateModelOutlet(
  request: ModelOutletValidationRequest,
  signal?: AbortSignal
): Promise<ModelOutletValidationResponse> {
  const response = await fetchWithErrorHandling(
    API_ENDPOINTS.model.outletValidations,
    {
      method: "POST",
      headers: { ...getAuthHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify(request),
      signal,
    }
  );
  return (await response.json()).data;
}

export async function confirmModelOutletMigration(
  modelId: number,
  expectedRevision: number
): Promise<void> {
  await fetchWithErrorHandling(
    API_ENDPOINTS.model.outletMigrationReviews(modelId),
    {
      method: "POST",
      headers: { ...getAuthHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ expected_revision: expectedRevision }),
    }
  );
}

export async function getConversationModelPreferences(
  conversationId: number,
  modelId: number,
  signal?: AbortSignal
): Promise<ConversationModelPreferenceView> {
  const response = await fetchWithErrorHandling(
    API_ENDPOINTS.conversation.modelPreferences(conversationId, modelId),
    { headers: getAuthHeaders(), signal }
  );
  return (await response.json()).data;
}

export async function patchConversationModelPreferences(
  conversationId: number,
  modelId: number,
  request: {
    expected_version: number;
    parameter_values: Record<string, unknown>;
    delete_parameters: string[];
  }
): Promise<void> {
  await fetchWithErrorHandling(
    API_ENDPOINTS.conversation.modelPreferences(conversationId, modelId),
    {
      method: "PATCH",
      headers: { ...getAuthHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify(request),
    }
  );
}
