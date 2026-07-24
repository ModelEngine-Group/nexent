/**
 * Skill repository service for tenant marketplace listing API calls.
 */

import { API_ENDPOINTS, fetchWithErrorHandling } from "./api";
import { getAuthHeaders } from "@/lib/auth";
import log from "@/lib/logger";
import type {
  MyEditableSkillListParams,
  MyEditableSkillListResponse,
  SkillRepositoryListingCreatePayload,
  SkillRepositoryListingDetail,
  SkillRepositoryListingItem,
  SkillRepositoryListingListParams,
  SkillRepositoryListingListResponse,
  SkillRepositoryListingStatus,
} from "@/types/skillRepository";

export async function fetchSkillRepositoryListings(
  params?: SkillRepositoryListingListParams
): Promise<SkillRepositoryListingListResponse> {
  try {
    const response = await fetchWithErrorHandling(
      API_ENDPOINTS.skillRepository.listings(params),
      {
        method: "GET",
        headers: getAuthHeaders(),
      }
    );

    if (!response.ok) {
      throw new Error(
        `Failed to fetch skill repository listings: ${response.statusText}`
      );
    }

    return response.json();
  } catch (error) {
    log.error("Error fetching skill repository listings:", error);
    throw error;
  }
}

export async function fetchSkillRepositoryListingDetail(
  skillRepositoryId: number
): Promise<SkillRepositoryListingDetail> {
  try {
    const response = await fetchWithErrorHandling(
      API_ENDPOINTS.skillRepository.detail(skillRepositoryId),
      {
        method: "GET",
        headers: getAuthHeaders(),
      }
    );

    if (!response.ok) {
      throw new Error(
        `Failed to fetch skill repository listing detail: ${response.statusText}`
      );
    }

    return response.json();
  } catch (error) {
    log.error("Error fetching skill repository listing detail:", error);
    throw error;
  }
}

export async function fetchMyEditableSkills(
  params?: MyEditableSkillListParams
): Promise<MyEditableSkillListResponse> {
  try {
    const response = await fetchWithErrorHandling(
      API_ENDPOINTS.skillRepository.mineSkills(params),
      {
        method: "GET",
        headers: getAuthHeaders(),
      }
    );

    if (!response.ok) {
      throw new Error(
        `Failed to fetch my editable skills: ${response.statusText}`
      );
    }

    return response.json();
  } catch (error) {
    log.error("Error fetching my editable skills:", error);
    throw error;
  }
}

export async function createSkillRepositoryListing(
  skillId: number,
  payload: SkillRepositoryListingCreatePayload
): Promise<SkillRepositoryListingDetail> {
  try {
    const response = await fetchWithErrorHandling(
      API_ENDPOINTS.skillRepository.createListing(skillId),
      {
        method: "POST",
        headers: {
          ...getAuthHeaders(),
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      }
    );

    if (!response.ok) {
      throw new Error(
        `Failed to create skill repository listing: ${response.statusText}`
      );
    }

    return response.json();
  } catch (error) {
    log.error("Error creating skill repository listing:", error);
    throw error;
  }
}

export async function updateSkillRepositoryStatus(
  skillRepositoryId: number,
  status: SkillRepositoryListingStatus,
  content?: string
): Promise<SkillRepositoryListingItem> {
  try {
    const response = await fetchWithErrorHandling(
      API_ENDPOINTS.skillRepository.updateStatus(skillRepositoryId),
      {
        method: "PATCH",
        headers: {
          ...getAuthHeaders(),
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          status,
          ...(content != null && content !== "" ? { content } : {}),
        }),
      }
    );

    if (!response.ok) {
      throw new Error(
        `Failed to update skill repository status: ${response.statusText}`
      );
    }

    return response.json();
  } catch (error) {
    log.error("Error updating skill repository status:", error);
    throw error;
  }
}

export async function installSkillFromRepository(
  skillRepositoryId: number,
  payload?: { target_name?: string }
): Promise<{ skill_id?: number; name?: string }> {
  try {
    const response = await fetch(
      API_ENDPOINTS.skillRepository.install(skillRepositoryId),
      {
        method: "POST",
        headers: {
          ...getAuthHeaders(),
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload ?? {}),
      }
    );

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      const detail = errorData?.detail ?? errorData?.message;
      const error = new Error(
        typeof detail === "string"
          ? detail
          : response.status === 409
            ? "Skill already exists"
            : `Failed to copy skill from repository: ${response.statusText}`
      ) as Error & { status?: number; detail?: unknown };
      error.status = response.status;
      error.detail = detail;
      throw error;
    }
    return response.json();
  } catch (error) {
    if (error instanceof Error && "status" in error) {
      throw error;
    }
    log.error("Error copying skill from repository:", error);
    throw error;
  }
}

const skillRepositoryService = {
  fetchSkillRepositoryListings,
  fetchSkillRepositoryListingDetail,
  fetchMyEditableSkills,
  createSkillRepositoryListing,
  updateSkillRepositoryStatus,
  installSkillFromRepository,
};

export default skillRepositoryService;
