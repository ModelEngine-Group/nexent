// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { API_ENDPOINTS, ApiError, fetchWithErrorHandling } from "./api";

export interface UserToken {
  token_id: number;
  /** Complete key; only present when `can_copy` is true. Use for copy actions. */
  access_key: string;
  /** Masked value for display; always present on list responses. */
  masked_access_key?: string;
  can_copy: boolean;
}

interface TokenListResponse {
  data: UserToken[];
  message: string;
}

interface TokenCreateResponse {
  data: UserToken;
  message: string;
}

/**
 * Fetch all API tokens for a given user
 */
export async function getUserTokens(
  userId: string | number
): Promise<UserToken[]> {
  try {
    const response = await fetchWithErrorHandling(
      `${API_ENDPOINTS.user.tokens}?user_id=${userId}`
    );
    const result: TokenListResponse = await response.json();
    return result.data ?? [];
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    throw new ApiError(500, "Failed to fetch user tokens");
  }
}

/**
 * Delete an API token by its ID
 */
export async function deleteUserToken(tokenId: number): Promise<void> {
  try {
    await fetchWithErrorHandling(API_ENDPOINTS.user.deleteToken(tokenId), {
      method: "DELETE",
    });
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    throw new ApiError(500, "Failed to delete token");
  }
}

/**
 * Create a new API token for the current user.
 * Replaces any existing tokens by deleting them first.
 */
export async function createUserToken(): Promise<UserToken> {
  try {
    const response = await fetchWithErrorHandling(API_ENDPOINTS.user.tokens, {
      method: "POST",
    });
    const result: TokenCreateResponse = await response.json();
    return result.data;
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    throw new ApiError(500, "Failed to create token");
  }
}
