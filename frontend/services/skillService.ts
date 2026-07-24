import { message } from "antd";
import log from "@/lib/logger";
import { fetchWithAuth } from "@/lib/auth";
import {
  createSkill,
  updateSkill,
  updateSkillById,
  createSkillFromFile,
  searchSkillsByName as searchSkillsByNameApi,
  fetchSkills,
  deleteSkill,
} from "@/services/agentConfigService";
import { API_ENDPOINTS, fetchWithErrorHandling } from "@/services/api";
import { InstallableSkill } from "@/types/agentConfig";
import {
  consumeSkillCreationStream,
  type SkillStreamCallbacks,
} from "@/lib/skillCreationStream";
import {
  THINKING_STEPS_EN,
  THINKING_STEPS_ZH,
  type CreateSkillStreamRequest,
  type SkillFileContent,
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
  files?: SkillFileContent[];
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
  config_values: Record<string, unknown> | null;
  config_schemas: unknown[] | null;
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
  return lang.startsWith("zh") ? THINKING_STEPS_ZH : THINKING_STEPS_EN;
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
              onThinkingUpdate(
                stepNum,
                steps.find((s) => s.step === stepNum)?.description || ""
              );
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

// ========== Skill Operation Functions ==========

/**
 * Load skills for lists (tenant-resources table, etc.).
 * Maps API payload to {@link SkillListItem} including config_schemas for config editing.
 * @param tenantId - Optional tenant ID for super admin to query a specific tenant's skills.
 */
export async function fetchSkillsList(
  tenantId?: string | null
): Promise<SkillListItem[]> {
  const res = await fetchSkills(tenantId);
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
    const rawConfigSchemas = s.config_schemas;
    let config_schemas: unknown[] | null = null;
    if (rawConfigSchemas !== undefined && rawConfigSchemas !== null) {
      if (Array.isArray(rawConfigSchemas)) {
        config_schemas = rawConfigSchemas;
      }
    }
    const rawConfigValues = s.config_values;
    let config_values: Record<string, unknown> | null = null;
    if (rawConfigValues !== undefined && rawConfigValues !== null) {
      if (
        typeof rawConfigValues === "object" &&
        !Array.isArray(rawConfigValues)
      ) {
        config_values = { ...(rawConfigValues as Record<string, unknown>) };
      }
    }
    const rawToolIds = s.tool_ids;
    const toolIds = Array.isArray(rawToolIds)
      ? rawToolIds.map((id) => Number(id)).filter((n) => !Number.isNaN(n))
      : [];
    return {
      skill_id: Number.isNaN(skillId) ? 0 : skillId,
      name: String(s.name ?? ""),
      description:
        s.description !== undefined ? String(s.description) : undefined,
      tags: Array.isArray(s.tags) ? (s.tags as string[]) : [],
      content: s.content !== undefined ? String(s.content) : undefined,
      config_schemas,
      config_values,
      source: String(s.source ?? "custom"),
      tool_ids: toolIds,
      created_by:
        s.created_by !== undefined
          ? (s.created_by as string | null)
          : undefined,
      create_time:
        s.create_time !== undefined
          ? (s.create_time as string | null)
          : undefined,
      updated_by:
        s.updated_by !== undefined
          ? (s.updated_by as string | null)
          : undefined,
      update_time:
        s.update_time !== undefined
          ? (s.update_time as string | null)
          : undefined,
    };
  });
}

/**
 * Submit skill form data (create or update)
 */
export const submitSkillForm = async (
  values: SkillData,
  _allSkills: SkillListItem[],
  onSuccess: () => void | Promise<void>,
  onCancel: () => void,
  t: (key: string) => string,
  options: { mode?: "create" | "edit"; skillId?: number } = { mode: "create" }
): Promise<boolean> => {
  try {
    let result;
    if (options.mode === "edit" && options.skillId) {
      result = await updateSkillById(options.skillId, {
        name: values.name,
        description: values.description,
        source: values.source,
        tags: values.tags,
        content: values.content,
        files: values.files,
      });
    } else {
      result = await createSkill({
        name: values.name,
        description: values.description,
        source: values.source,
        tags: values.tags,
        content: values.content,
        files: values.files,
      });
    }

    if (result.success) {
      message.success(
        options.mode === "edit"
          ? t("skillManagement.message.updateSuccess")
          : t("skillManagement.message.createSuccess")
      );
      await onSuccess();
      onCancel();
      return true;
    } else {
      throw new Error(
        result.message || t("skillManagement.message.submitFailed")
      );
    }
  } catch (error) {
    log.error("Skill create/update error:", error);
    throw error;
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
    const result = await createSkillFromFile(skillName.trim(), file, false);

    if (result.success) {
      message.success(t("skillManagement.message.createSuccess"));
      onSuccess();
      onCancel();
      return true;
    } else {
      message.error(
        result.message || t("skillManagement.message.submitFailed")
      );
      return false;
    }
  } catch (error) {
    log.error("Skill file upload error:", error);
    message.error(t("skillManagement.message.submitFailed"));
    return false;
  }
};

/**
 * Clear chat state (no backend call needed)
 */
export const clearChatAndTempFile = async (): Promise<void> => {
  // No backend call needed - just clear local state
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
export {
  createSkillFrontmatterStreamParser,
  consumeSkillCreationStream,
  isSafeSkillFilePath,
  SKILL_STREAM_TYPES,
} from "@/lib/skillCreationStream";
export type {
  SkillStreamCallbacks,
  SkillStreamEvent,
  StreamEventType,
} from "@/lib/skillCreationStream";

/**
 * Interactive skill creation via backend API (SDK-backed).
 */
export const createSkillStreamRequest = async (
  request: CreateSkillStreamRequest
): Promise<void> => {
  await fetchWithErrorHandling(API_ENDPOINTS.skills.createStream, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
};

/**
 * Initialize a skill content parser state that handles multi-file streaming.
 * Supports:
 * - <SKILL>...</SKILL>: Default SKILL.md content
 * - <FILE path="...">...</FILE>: Additional files
 * - Text outside all tags: Summary for chat bubble
 */
export function createSkillContentParser(): {
  update: (chunk: string) => {
    skillTabs: { path: string; content: string }[];
    newTabContent: string;
    newTabPath: string;
    summaryContent: string;
    activeTab: string;
    summaryStarted: boolean;
    done: boolean;
  };
  getFullResult: () => {
    skillTabs: { path: string; content: string }[];
    newTabContent: string;
    newTabPath: string;
    summaryContent: string;
    activeTab: string;
    summaryStarted: boolean;
    done: boolean;
  };
} {
  // State
  const skillTabs: { path: string; content: string }[] = [
    { path: "SKILL.md", content: "" },
  ];
  let activeTab = "SKILL.md";
  let summaryContent = "";
  let buffer = "";
  let summaryStarted = false;

  // Regex patterns
  const SKILL_OPEN = "<SKILL>";
  const SKILL_CLOSE = "</SKILL>";
  const FILE_OPEN_PATTERN = /<FILE\s+path="([^"]+)">/i;
  const FILE_CLOSE = "</FILE>";

  function findTagInBuffer(): {
    type: "skill_open" | "skill_close" | "file_open" | "file_close" | "none";
    tag: string;
    path?: string;
    index: number;
  } | null {
    // Check for SKILL open first
    const skillOpenIdx = buffer.indexOf(SKILL_OPEN);
    // Check for SKILL close
    const skillCloseIdx = buffer.indexOf(SKILL_CLOSE);
    // Check for FILE open
    const fileOpenMatch = FILE_OPEN_PATTERN.exec(buffer);
    // Check for FILE close
    const fileCloseIdx = buffer.indexOf(FILE_CLOSE);

    // Collect all found tags with their positions
    type TagInfo = {
      type: "skill_open" | "skill_close" | "file_open" | "file_close";
      tag: string;
      path?: string;
      index: number;
    };
    const foundTags: TagInfo[] = [];

    if (skillOpenIdx !== -1) {
      foundTags.push({
        type: "skill_open",
        tag: SKILL_OPEN,
        index: skillOpenIdx,
      });
    }
    if (skillCloseIdx !== -1) {
      foundTags.push({
        type: "skill_close",
        tag: SKILL_CLOSE,
        index: skillCloseIdx,
      });
    }
    if (fileOpenMatch?.index !== undefined) {
      foundTags.push({
        type: "file_open",
        tag: fileOpenMatch[0],
        path: fileOpenMatch[1],
        index: fileOpenMatch.index,
      });
    }
    if (fileCloseIdx !== -1) {
      foundTags.push({
        type: "file_close",
        tag: FILE_CLOSE,
        index: fileCloseIdx,
      });
    }

    // Return the earliest tag
    if (foundTags.length === 0) {
      return null;
    }

    return foundTags.reduce((earliest, current) =>
      current.index < earliest.index ? current : earliest
    );
  }

  return {
    update(chunk: string) {
      buffer += chunk;
      let newTabContent = "";
      let newTabPath = "";

      while (buffer.length > 0) {
        const tagInfo = findTagInBuffer();

        if (!tagInfo) {
          // No tag found - accumulate content based on state
          if (summaryStarted) {
            // Outside all tags, accumulate as summary
            summaryContent += buffer;
            newTabContent += buffer;
          } else {
            // Before any tag, just buffer (ignore preceding noise)
          }
          buffer = "";
          break;
        }

        // Content before the tag
        const beforeTag = buffer.substring(0, tagInfo.index);

        switch (tagInfo.type) {
          case "skill_open":
            // Content before <SKILL> is noise, ignore
            // Switch to SKILL.md tab
            activeTab = "SKILL.md";
            // Find or ensure SKILL.md tab exists
            if (!skillTabs.find((t) => t.path === "SKILL.md")) {
              skillTabs.push({ path: "SKILL.md", content: "" });
            }
            buffer = buffer.substring(tagInfo.index + tagInfo.tag.length);
            break;

          case "skill_close":
            // Add content before close tag to current tab
            if (beforeTag) {
              const tab = skillTabs.find((t) => t.path === activeTab);
              if (tab) {
                tab.content += beforeTag;
                newTabContent += beforeTag;
                newTabPath = activeTab;
              }
            }
            // Switch to summary mode
            summaryStarted = true;
            // Remove frontmatter from SKILL.md if present
            const skillTab = skillTabs.find((t) => t.path === "SKILL.md");
            if (skillTab) {
              skillTab.content = stripFrontmatter(skillTab.content);
            }
            buffer = buffer.substring(tagInfo.index + tagInfo.tag.length);
            break;

          case "file_open":
            // Add content before FILE tag to current tab
            if (beforeTag) {
              const tab = skillTabs.find((t) => t.path === activeTab);
              if (tab) {
                tab.content += beforeTag;
                newTabContent += beforeTag;
                newTabPath = activeTab;
              }
            }
            // Create new tab for the file
            const filePath = tagInfo.path || "file.txt";
            if (!skillTabs.some((t) => t.path === filePath)) {
              skillTabs.push({ path: filePath, content: "" });
            }
            activeTab = filePath;
            newTabPath = filePath;
            buffer = buffer.substring(tagInfo.index + tagInfo.tag.length);
            break;

          case "file_close":
            // Add content before close tag to current tab
            if (beforeTag) {
              const tab = skillTabs.find((t) => t.path === activeTab);
              if (tab) {
                tab.content += beforeTag;
                newTabContent += beforeTag;
                newTabPath = activeTab;
              }
            }
            // Switch to summary mode
            summaryStarted = true;
            buffer = buffer.substring(tagInfo.index + tagInfo.tag.length);
            break;
        }
      }

      return {
        skillTabs: [...skillTabs],
        newTabContent,
        newTabPath,
        summaryContent,
        activeTab,
        summaryStarted,
        done: false,
      };
    },

    getFullResult() {
      // Process any remaining buffer
      if (buffer.length > 0) {
        if (summaryStarted) {
          summaryContent += buffer;
        }
      }

      // Remove frontmatter from SKILL.md
      const skillTab = skillTabs.find((t) => t.path === "SKILL.md");
      if (skillTab) {
        skillTab.content = stripFrontmatter(skillTab.content);
      }

      return {
        skillTabs: [...skillTabs],
        newTabContent: "",
        newTabPath: "",
        summaryContent,
        activeTab,
        summaryStarted: true,
        done: true,
      };
    },
  };
}

/**
 * Strip YAML frontmatter from markdown content
 */
function stripFrontmatter(content: string): string {
  const frontmatterRegex = /^---\n[\s\S]*?\n---\n?/;
  return content.replace(frontmatterRegex, "").trim();
}

/**
 * Interactive skill creation via SSE stream with multi-file tab support.
 * Uses backend-classified events (frontmatter, skill_body, file_content, summary)
 * instead of frontend parsing.
 */
export const createSkillStream = async (
  request: CreateSkillStreamRequest,
  callbacks: SkillStreamCallbacks,
  options?: { signal?: AbortSignal }
): Promise<{
  skillTabs: { path: string; content: string }[];
  summaryContent: string;
}> => {
  const response = await fetch(API_ENDPOINTS.skills.createStream, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
    signal: options?.signal,
  });

  if (!response.ok) {
    callbacks.onThinkingVisible(false);
    callbacks.onError(`HTTP error: ${response.status}`);
    return { skillTabs: [], summaryContent: "" };
  }

  if (!response.body) {
    callbacks.onThinkingVisible(false);
    callbacks.onError("No response body");
    return { skillTabs: [], summaryContent: "" };
  }

  // Capture task ID from response headers
  const taskId = response.headers.get("X-Task-ID");
  if (taskId && callbacks.onTaskId) {
    callbacks.onTaskId(taskId);
  }

  return consumeSkillCreationStream(response.body, callbacks, {
    signal: options?.signal,
    onProtocolWarning: (messageText, detail) => log.warn(messageText, detail),
  });
};

/**
 * Delete a skill by name
 * @param skillName skill name to delete
 * @returns delete result
 */
export const deleteSkillByName = async (skillName: string) => {
  return deleteSkill(skillName);
};

/**
 * Stop an active skill creation task on the backend.
 * @param taskId The task ID returned from createSkillStream
 * @returns Promise resolving to success status
 */
export const stopSkillCreation = async (taskId: string): Promise<boolean> => {
  try {
    const response = await fetch(API_ENDPOINTS.skills.stopCreate(taskId), {
      method: "GET",
    });
    return response.ok;
  } catch (error) {
    log.error("Failed to stop skill creation task:", error);
    return false;
  }
};

/**
 * Fetch official skills with installation status for a tenant.
 * Used in the tenant creation flow to show which skills are installable.
 * @param tenantId - Optional tenant ID for super admin to query a specific tenant's skills.
 */
export async function fetchOfficialSkillsWithStatus(
  tenantId?: string
): Promise<InstallableSkill[]> {
  try {
    const url = tenantId
      ? `${API_ENDPOINTS.skills.official}?tenant_id=${encodeURIComponent(tenantId)}`
      : API_ENDPOINTS.skills.official;
    const response = await fetchWithAuth(url);
    if (!response.ok) {
      throw new Error(`Request failed: ${response.status}`);
    }
    const data = await response.json();
    const rawSkills: unknown[] = data.skills || [];
    return (rawSkills as Record<string, unknown>[]).map((s) => ({
      skill_id: Number(s.skill_id),
      name: String(s.name ?? ""),
      description: s.description !== undefined ? String(s.description) : "",
      source: String(s.source ?? "official"),
      status: (s.status as InstallableSkill["status"]) ?? "installable",
    }));
  } catch (error) {
    log.error("Failed to fetch official skills with status:", error);
    throw error;
  }
}

export async function installOfficialSkills(
  skillNames: string[],
  locale: string = "en",
  tenantId?: string
): Promise<{ installed: string[]; total: number }> {
  try {
    const url = tenantId
      ? `${API_ENDPOINTS.skills.install}?tenant_id=${encodeURIComponent(tenantId)}`
      : API_ENDPOINTS.skills.install;
    const response = await fetchWithAuth(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ skill_names: skillNames, locale }),
    });
    if (!response.ok) {
      throw new Error(`Request failed: ${response.status}`);
    }
    const data = await response.json();
    return { installed: data.installed || [], total: data.total || 0 };
  } catch (error) {
    log.error("Failed to install official skills:", error);
    throw error;
  }
}
