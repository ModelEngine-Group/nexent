import { message } from "antd";
import log from "@/lib/logger";
import { conversationService } from "@/services/conversationService";
import {
  createSkill,
  updateSkill,
  createSkillFromFile,
  searchSkillsByName as searchSkillsByNameApi,
  fetchSkillConfig,
  deleteSkillTempFile,
} from "@/services/agentConfigService";
import {
  extractSkillInfoFromContent,
  parseSkillDraft,
} from "@/lib/skillFileUtils";
import {
  THINKING_STEPS_ZH,
  THINKING_STEPS_EN,
  type SkillDraftResult,
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
  return lang === "zh" ? THINKING_STEPS_ZH : THINKING_STEPS_EN;
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
    const config = await fetchSkillConfig("simple-skill-creator");
    if (config && typeof config === "object" && config.temp_filename) {
      await deleteSkillTempFile("simple-skill-creator", config.temp_filename as string);
    }
  } catch (error) {
    log.warn("Failed to delete temp file:", error);
  }
};

// ========== Skill Operation Functions ==========

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
 * Interactive skill creation via chat with agent
 */
export const runInteractiveSkillCreation = async (
  input: string,
  history: { role: "user" | "assistant"; content: string }[],
  skillCreatorAgentId: number,
  onThinkingUpdate: (step: number, description: string) => void,
  onThinkingVisible: (visible: boolean) => void,
  onMessageUpdate: (messages: { id: string; role: "user" | "assistant"; content: string; timestamp: Date }[]) => void,
  onLoadingChange: (loading: boolean) => void,
  allSkills: SkillListItem[],
  form: { setFieldValue: (name: string, value: unknown) => void },
  t: (key: string) => string,
  isMountedRef: React.MutableRefObject<boolean>
): Promise<{ success: boolean; skillDraft: SkillDraftResult | null }> => {
  try {
    const reader = await conversationService.runAgent(
      {
        query: input,
        conversation_id: 0,
        history,
        agent_id: skillCreatorAgentId,
        is_debug: true,
      },
      undefined as unknown as AbortSignal
    );

    let finalAnswer = "";

    await processSkillStream(
      reader,
      onThinkingUpdate,
      onThinkingVisible,
      (answer) => {
        finalAnswer = answer;
      },
      "zh"
    );

    if (!isMountedRef.current) {
      return { success: false, skillDraft: null };
    }

    const skillDraft = parseSkillDraft(finalAnswer);
    if (skillDraft) {
      form.setFieldValue("name", skillDraft.name);
      form.setFieldValue("description", skillDraft.description);
      form.setFieldValue("tags", skillDraft.tags);
      form.setFieldValue("content", skillDraft.content);

      message.success(t("skillManagement.message.skillReadyForSave"));
      return { success: true, skillDraft };
    } else {
      // Fallback: read temp file if no skill draft parsed
      if (!isMountedRef.current) {
        return { success: false, skillDraft: null };
      }

      try {
        const config = await fetchSkillConfig("simple-skill-creator");
        if (config && config.temp_filename && isMountedRef.current) {
          const { fetchSkillFileContent } = await import("@/services/agentConfigService");
          const tempFilename = config.temp_filename as string;
          const tempContent = await fetchSkillFileContent("simple-skill-creator", tempFilename);

          if (tempContent && isMountedRef.current) {
            const skillInfo = extractSkillInfoFromContent(tempContent);

            if (skillInfo && skillInfo.name) {
              form.setFieldValue("name", skillInfo.name);
            }
            if (skillInfo && skillInfo.description) {
              form.setFieldValue("description", skillInfo.description);
            }
            if (skillInfo && skillInfo.tags && skillInfo.tags.length > 0) {
              form.setFieldValue("tags", skillInfo.tags);
            }
            if (skillInfo.contentWithoutFrontmatter) {
              form.setFieldValue("content", skillInfo.contentWithoutFrontmatter);
            }
          }
        }
      } catch (error) {
        log.warn("Failed to load temp file content:", error);
      }

      return { success: false, skillDraft: null };
    }
  } catch (error) {
    log.error("Interactive skill creation error:", error);
    message.error(t("skillManagement.message.chatError"));
    return { success: false, skillDraft: null };
  }
};

/**
 * Clear chat and delete temp file
 */
export const clearChatAndTempFile = async (): Promise<void> => {
  try {
    const config = await fetchSkillConfig("simple-skill-creator");
    if (config && typeof config === "object" && config.temp_filename) {
      await deleteSkillTempFile("simple-skill-creator", config.temp_filename as string);
    }
  } catch (error) {
    log.warn("Failed to delete temp file on clear:", error);
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
