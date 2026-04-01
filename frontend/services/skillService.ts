import { message } from "antd";
import log from "@/lib/logger";
import {
  createSkill,
  updateSkill,
  createSkillFromFile,
  searchSkillsByName as searchSkillsByNameApi,
  fetchSkills,
} from "@/services/agentConfigService";
import {
  THINKING_STEPS_ZH,
  SKILL_CREATOR_TEMP_FILE,
  type CreateSimpleSkillRequest,
} from "@/types/skill";

// ========== Type Definitions ==========

/**
 * Skill data for create/update operations
 */
export interface SkillData {
  name: string;
  description: string;
  source: string;
  tags: string[];
  content: string;
}

/**
 * Skill item from list
 */
export interface SkillListItem {
  skill_id: string;
  name: string;
  description?: string;
  tags: string[];
  content?: string;
  params: Record<string, unknown> | null;
  source: string;
  tool_ids: number[];
  created_by?: string | null;
  create_time?: string | null;
  updated_by?: string | null;
  update_time?: string | null;
}

/**
 * Result of skill creation/update operation
 */
export interface SkillOperationResult {
  success: boolean;
  message?: string;
}

/**
 * Callback for stream processing final answer
 */
export type FinalAnswerCallback = (answer: string) => void;

/**
 * Thinking step information
 */
export interface ThinkingStep {
  step: number;
  description: string;
}

// ========== Helper Functions ==========

/**
 * Get thinking steps based on language
 */
export const getThinkingSteps = (lang: string): ThinkingStep[] => {
  return lang === "zh" ? THINKING_STEPS_ZH : THINKING_STEPS_ZH;
};


/**
 * Process SSE stream from agent and extract final answer
 */
export const processSkillStream = async (
  reader: ReadableStreamDefaultReader<Uint8Array>,
  onThinkingUpdate: (step: number, description: string) => void,
  onThinkingVisible: (visible: boolean) => void,
  onFinalAnswer: (answer: string) => void,
  lang: string = "zh"
): Promise<string> => {
  const decoder = new TextDecoder();
  let buffer = "";
  let finalAnswer = "";
  const steps = getThinkingSteps(lang);

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      for (const line of lines) {
        if (!line.startsWith("data:")) continue;
        const jsonStr = line.substring(5).trim();
        try {
          const data = JSON.parse(jsonStr);

          if (data.type === "final_answer" && data.content) {
            finalAnswer += data.content;
          }

          if (data.type === "step_count") {
            const stepMatch = String(data.content).match(/\d+/);
            const stepNum = stepMatch ? parseInt(stepMatch[0], 10) : NaN;
            if (!isNaN(stepNum) && stepNum > 0) {
              onThinkingUpdate(stepNum, steps.find((s) => s.step === stepNum)?.description || "");
            }
          }
        } catch {
          // ignore parse errors
        }
      }
    }

    // Process remaining buffer
    if (buffer.trim() && buffer.startsWith("data:")) {
      const jsonStr = buffer.substring(5).trim();
      try {
        const data = JSON.parse(jsonStr);
        if (data.type === "final_answer" && data.content) {
          finalAnswer += data.content;
        }
      } catch {
        // ignore
      }
    }
  } finally {
    onThinkingVisible(false);
    onThinkingUpdate(0, "");
    onFinalAnswer(finalAnswer);
  }

  return finalAnswer;
};

/**
 * Delete temp file from skill creator directory
 */
export const deleteSkillCreatorTempFile = async (): Promise<void> => {
  try {
    await fetch(API_ENDPOINTS.skills.creatorCache, {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
    });
  } catch (error) {
    log.warn("Failed to delete temp file:", error);
  }
};

// ========== Skill Operation Functions ==========

/**
 * Load skills for lists (tenant-resources table, etc.).
 * Maps API payload to {@link SkillListItem} including params for config editing.
 */
export async function fetchSkillsList(): Promise<SkillListItem[]> {
  const res = await fetchSkills();
  if (!res.success) {
    throw new Error(res.message || "Failed to fetch skills");
  }
  const rows = res.data || [];
  return rows.map((s: Record<string, unknown>) => {
    const rawId = s.skill_id;
    const skillId =
      typeof rawId === "number"
        ? rawId
        : typeof rawId === "string"
          ? Number.parseInt(rawId, 10)
          : Number.NaN;
    const rawParams = s.params;
    let params: Record<string, unknown> | null = null;
    if (rawParams !== undefined && rawParams !== null) {
      if (typeof rawParams === "object" && !Array.isArray(rawParams)) {
        params = { ...(rawParams as Record<string, unknown>) };
      }
    }
    const rawToolIds = s.tool_ids;
    const toolIds = Array.isArray(rawToolIds)
      ? rawToolIds.map((id) => Number(id)).filter((n) => !Number.isNaN(n))
      : [];
    return {
      skill_id: Number.isNaN(skillId) ? 0 : skillId,
      name: String(s.name ?? ""),
      description: s.description !== undefined ? String(s.description) : undefined,
      tags: Array.isArray(s.tags) ? (s.tags as string[]) : [],
      content: s.content !== undefined ? String(s.content) : undefined,
      params,
      source: String(s.source ?? "custom"),
      tool_ids: toolIds,
      created_by: s.created_by !== undefined ? (s.created_by as string | null) : undefined,
      create_time: s.create_time !== undefined ? (s.create_time as string | null) : undefined,
      updated_by: s.updated_by !== undefined ? (s.updated_by as string | null) : undefined,
      update_time: s.update_time !== undefined ? (s.update_time as string | null) : undefined,
    };
  });
}

/**
 * Submit skill form data (create or update)
 */
export const submitSkillForm = async (
  values: SkillData,
  allSkills: SkillListItem[],
  onSuccess: () => void,
  onCancel: () => void,
  t: (key: string) => string
): Promise<boolean> => {
  try {
    const existingSkill = allSkills.find((s) => s.name === values.name);

    let result;
    if (existingSkill) {
      result = await updateSkill(values.name, {
        description: values.description,
        source: values.source,
        tags: values.tags,
        content: values.content,
      });
    } else {
      result = await createSkill({
        name: values.name,
        description: values.description,
        source: values.source,
        tags: values.tags,
        content: values.content,
      });
    }

    if (result.success) {
      await deleteSkillCreatorTempFile();
      message.success(
        existingSkill
          ? t("skillManagement.message.updateSuccess")
          : t("skillManagement.message.createSuccess")
      );
      onSuccess();
      onCancel();
      return true;
    } else {
      message.error(result.message || t("skillManagement.message.submitFailed"));
      return false;
    }
  } catch (error) {
    log.error("Skill create/update error:", error);
    message.error(t("skillManagement.message.submitFailed"));
    return false;
  }
};

/**
 * Submit skill from file upload
 */
export const submitSkillFromFile = async (
  skillName: string,
  file: File,
  allSkills: SkillListItem[],
  onSuccess: () => void,
  onCancel: () => void,
  t: (key: string) => string
): Promise<boolean> => {
  try {
    const normalizedName = skillName.trim().toLowerCase();
    const existingSkill = allSkills.find(
      (s) => s.name.trim().toLowerCase() === normalizedName
    );

    const result = await createSkillFromFile(skillName.trim(), file, !!existingSkill);

    if (result.success) {
      message.success(
        existingSkill
          ? t("skillManagement.message.updateSuccess")
          : t("skillManagement.message.createSuccess")
      );
      onSuccess();
      onCancel();
      return true;
    } else {
      message.error(result.message || t("skillManagement.message.submitFailed"));
      return false;
    }
  } catch (error) {
    log.error("Skill file upload error:", error);
    message.error(t("skillManagement.message.submitFailed"));
    return false;
  }
};

/**
 * Clear chat and delete temp file
 */
export const clearChatAndTempFile = async (): Promise<void> => {
  try {
    await fetch(API_ENDPOINTS.skills.creatorCache, {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
    });
  } catch (error) {
    log.warn("Failed to delete temp file on clear:", error);
  }
};

/**
 * Fetch skill creator temp file content
 */
export const fetchSkillCreatorTempFile = async (): Promise<string | null> => {
  try {
    const response = await fetch(API_ENDPOINTS.skills.creatorCache, {
      method: "GET",
      headers: { "Content-Type": "application/json" },
    });
    if (!response.ok) {
      return null;
    }
    const data = await response.json();
    return data.content || null;
  } catch (error) {
    log.warn("Failed to fetch skill creator temp file:", error);
    return null;
  }
};

/**
 * Search skills by name for autocomplete
 */
export const searchSkillsByName = (
  prefix: string,
  allSkills: SkillListItem[]
): SkillListItem[] => {
  return searchSkillsByNameApi(prefix, allSkills);
};

/**
 * Find existing skill by name (case-insensitive)
 */
export const findSkillByName = (
  name: string,
  allSkills: SkillListItem[]
): SkillListItem | undefined => {
  return allSkills.find((s) => s.name.toLowerCase() === name.toLowerCase());
};

/**
 * Check if skill name exists (case-insensitive)
 */
export const skillNameExists = (
  name: string,
  allSkills: SkillListItem[]
): boolean => {
  return allSkills.some((s) => s.name.toLowerCase() === name.toLowerCase());
};

export { updateSkill };

/**
 * Call the /skills/create-simple backend API to generate a skill.
 */
import { API_ENDPOINTS, fetchWithErrorHandling } from "@/services/api";

export interface CreateSimpleSkillResponse {
  skill_name: string;
  skill_description: string;
  tags: string[];
  skill_content: string;
}

/**
 * Interactive skill creation via backend API (SDK-backed).
 */
export const createSimpleSkill = async (
  request: CreateSimpleSkillRequest
): Promise<CreateSimpleSkillResponse> => {
  const response = await fetchWithErrorHandling(API_ENDPOINTS.skills.createSimple, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  return response.json();
};

/**
 * SSE event types for streaming skill creation
 */
export interface SkillCreationStreamEvent {
  type: "step_count" | "final_answer" | "skill_result" | "done" | "error";
  content?: string;
  skill_name?: string;
  skill_description?: string;
  tags?: string[];
  message?: string;
}

/**
 * Interactive skill creation via SSE stream with progress updates.
 */
export const createSimpleSkillStream = async (
  request: CreateSimpleSkillRequest,
  callbacks: {
    onStepCount: (step: number, description: string) => void;
    onThinkingVisible: (visible: boolean) => void;
    onThinkingUpdate: (step: number, description: string) => void;
    onFinalAnswer: (content: string) => void;
    onSkillResult?: (result: { skill_name: string; skill_description: string; tags: string[] }) => void;
    onDone: () => void;
    onError: (message: string) => void;
  }
): Promise<void> => {
  const response = await fetch(API_ENDPOINTS.skills.createSimple, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    callbacks.onError(`HTTP error: ${response.status}`);
    return;
  }

  if (!response.body) {
    callbacks.onError("No response body");
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  callbacks.onThinkingVisible(true);

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      for (const line of lines) {
        if (!line.startsWith("data:")) continue;
        const jsonStr = line.substring(5).trim();
        if (!jsonStr) continue;

        try {
          const event: SkillCreationStreamEvent = JSON.parse(jsonStr);

          switch (event.type) {
            case "step_count": {
              const stepMatch = String(event.content).match(/\d+/);
              const stepNum = stepMatch ? parseInt(stepMatch[0], 10) : NaN;
              if (!isNaN(stepNum)) {
                callbacks.onThinkingUpdate(stepNum, "");
                callbacks.onStepCount(stepNum, "");
              }
              break;
            }
            case "final_answer":
              callbacks.onFinalAnswer(event.content || "");
              break;
            case "skill_result":
              if (callbacks.onSkillResult) {
                callbacks.onSkillResult({
                  skill_name: event.skill_name || "",
                  skill_description: event.skill_description || "",
                  tags: event.tags || [],
                });
              }
              break;
            case "done":
              callbacks.onThinkingVisible(false);
              callbacks.onDone();
              break;
            case "error":
              callbacks.onThinkingVisible(false);
              callbacks.onError(event.message || "Unknown error");
              break;
          }
        } catch {
          // Ignore parse errors
        }
      }
    }
  } finally {
    callbacks.onThinkingVisible(false);
  }
};
