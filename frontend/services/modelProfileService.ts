// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { runModelCheck } from "@/lib/modelCheckQueue";
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

async function profileRequest(
  url: string,
  body?: unknown,
  signal?: AbortSignal,
  method = body === undefined ? "GET" : "POST"
) {
  return fetchWithErrorHandling(url, {
    method,
    headers:
      body === undefined
        ? getAuthHeaders()
        : { ...getAuthHeaders(), "Content-Type": "application/json" },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    signal,
  });
}

async function profileData<T>(
  ...args: Parameters<typeof profileRequest>
): Promise<T> {
  return (await (await profileRequest(...args)).json()).data;
}

export async function listModelProfiles(
  request: ProfileListRequest = {},
  signal?: AbortSignal
): Promise<ProfileListResponse> {
  return profileData(
    API_ENDPOINTS.model.modelProfiles(request),
    undefined,
    signal
  );
}

export async function listProviderProfiles(
  request: Omit<ProfileListRequest, "family"> = {},
  signal?: AbortSignal
): Promise<ProfileListResponse> {
  return profileData(
    API_ENDPOINTS.model.providerProfiles(request),
    undefined,
    signal
  );
}

export async function listProfileProtocols(
  signal?: AbortSignal
): Promise<ProfileProtocolsResponse> {
  return profileData(API_ENDPOINTS.model.profileProtocols, undefined, signal);
}

export async function previewModelProfile(
  request: ModelProfileDraftRequest,
  signal?: AbortSignal
): Promise<ModelProfileDraftResponse> {
  return profileData(API_ENDPOINTS.model.profilePreviews, request, signal);
}

export async function previewModelOutletPatch(
  modelId: number,
  request: ModelOutletPatchRequest,
  signal?: AbortSignal
): Promise<ModelProfileDraftResponse> {
  return profileData(
    `${API_ENDPOINTS.model.outlet(modelId)}/profile_previews`,
    request,
    signal
  );
}

export async function createModelOutlet(
  request: ModelOutletCreateRequest
): Promise<ModelOutletResponse> {
  return profileData(API_ENDPOINTS.model.outlets, request);
}

export async function getModelOutlet(
  modelId: number,
  signal?: AbortSignal
): Promise<ModelOutletResponse> {
  return profileData(API_ENDPOINTS.model.outlet(modelId), undefined, signal);
}

export async function updateModelOutlet(
  modelId: number,
  request: ModelOutletPatchRequest
): Promise<ModelOutletResponse> {
  // Draft provider_info also carries identity fields. Saved outlet identities
  // are immutable; PATCH accepts only the editable connection settings.
  const connection = request.connection;
  return profileData(
    API_ENDPOINTS.model.outlet(modelId),
    connection
      ? {
          ...request,
          connection: {
            base_url: connection.base_url,
            ssl_verify: connection.ssl_verify,
            timeout_seconds: connection.timeout_seconds,
            concurrency_limit: connection.concurrency_limit,
          },
        }
      : request,
    undefined,
    "PATCH"
  );
}

export async function validateModelOutlet(
  request: ModelOutletValidationRequest,
  signal?: AbortSignal
): Promise<ModelOutletValidationResponse> {
  return runModelCheck(
    () => profileData(API_ENDPOINTS.model.outletValidations, request, signal),
    signal
  );
}

export async function confirmModelOutletMigration(
  modelId: number,
  expectedRevision: number
): Promise<void> {
  await profileRequest(API_ENDPOINTS.model.outletMigrationReviews(modelId), {
    expected_revision: expectedRevision,
  });
}

export async function getConversationModelPreferences(
  conversationId: number,
  modelId: number,
  signal?: AbortSignal
): Promise<ConversationModelPreferenceView> {
  return profileData(
    API_ENDPOINTS.conversation.modelPreferences(conversationId, modelId),
    undefined,
    signal
  );
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
  await profileRequest(
    API_ENDPOINTS.conversation.modelPreferences(conversationId, modelId),
    request,
    undefined,
    "PATCH"
  );
}

export async function getConversationModelSelection(
  conversationId: number,
  signal?: AbortSignal
): Promise<{ selected_model_id: number | null; version: number }> {
  return profileData(
    API_ENDPOINTS.conversation.modelSelection(conversationId),
    undefined,
    signal
  );
}

export async function patchConversationModelSelection(
  conversationId: number,
  selectedModelId: number,
  expectedVersion: number
): Promise<{ selected_model_id: number | null; version: number }> {
  return profileData(
    API_ENDPOINTS.conversation.modelSelection(conversationId),
    { selected_model_id: selectedModelId, expected_version: expectedVersion },
    undefined,
    "PATCH"
  );
}
