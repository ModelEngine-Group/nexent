import { message } from "antd";
import log from "@/lib/logger";
import {
  createSkill,
  updateSkill,
  createSkillFromFile,
  searchSkillsByName as searchSkillsByNameApi,
  fetchSkills,
  deleteSkill,
} from "@/services/agentConfigService";
import {
  THINKING_STEPS_ZH,
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
 * Parse streaming content with <SKILL> delimiters.
 * Content inside <SKILL></SKILL> goes to form content.
 * Content outside <SKILL></SKILL> that appears BEFORE the <SKILL> tag is ignored (preceding noise).
 * Content outside that appears AFTER the </SKILL> tag is the summary.
 */
export interface SkillDelimiterParseResult {
  formContent: string;
  summaryContent: string;
  newFormContent: string;
  newSummaryContent: string;
  summaryStarted: boolean;
}

/**
 * Extract summary content from final_answer.
 * final_answer contains the FULL response including <SKILL> block.
 * The SKILL content was already streamed via skill_content events,
 * so we only need the summary (content AFTER </SKILL>).
 */
function extractSummaryFromFinalAnswer(fullContent: string): string {
  const SKILL_CLOSE = "</SKILL>";
  const closeIndex = fullContent.indexOf(SKILL_CLOSE);
  if (closeIndex === -1) {
    return fullContent;
  }
  return fullContent.substring(closeIndex + SKILL_CLOSE.length).trim();
}

/**
 * Initialize a skill delimiter parser state.
 * Matches uppercase <SKILL></SKILL> XML delimiters from the backend.
 */
export function createSkillDelimiterParser(): {
  update: (chunk: string) => SkillDelimiterParseResult;
  getFullResult: () => SkillDelimiterParseResult;
} {
  let formContent = "";
  let summaryContent = "";
  let buffer = "";
  let isInsideSkillTag = false;
  let summaryStarted = false;
  // Tracks potential partial </SKILL> prefix across chunks
  let pendingClose = "";
  const SKILL_OPEN = "<SKILL>";
  const SKILL_CLOSE = "</SKILL>";
  const CLOSE_LEN = SKILL_CLOSE.length; // 8

  return {
    update(chunk: string): SkillDelimiterParseResult {
      buffer += chunk;
      let newFormContent = "";
      let newSummaryContent = "";

      while (buffer.length > 0) {
        if (isInsideSkillTag) {
          // Check if pendingClose + buffer contains </SKILL>
          const combined = pendingClose + buffer;
          const closeIdx = combined.indexOf(SKILL_CLOSE);
          if (closeIdx !== -1) {
            // Found </SKILL>!
            // Content before it (minus pendingClose) is safe to output as form content.
            const content = combined.substring(0, closeIdx);
            const safeContent = content.substring(pendingClose.length);
            if (safeContent.length > 0) {
              formContent += safeContent;
              newFormContent += safeContent;
            }
            // Everything after </SKILL> is summary.
            const afterClose = combined.substring(closeIdx + CLOSE_LEN);
            if (afterClose.length > 0) {
              summaryContent += afterClose;
              newSummaryContent += afterClose;
            }
            buffer = "";
            pendingClose = "";
            isInsideSkillTag = false;
            summaryStarted = true;
            break;
          }

          // No full </SKILL> in combined. Decide what to save as pendingClose.
          if (combined.length <= CLOSE_LEN - 1) {
            // Too short to contain </SKILL>. Hold all as pending, output nothing.
            pendingClose = combined;
            buffer = "";
            break;
          }

          // Buffer is long enough. Check if combined ends with potential partial </SKILL.
          const lastPossible = combined.slice(-(CLOSE_LEN - 1)); // Last 7 chars
          if (lastPossible.startsWith("</SK")) {
            // Looks like partial </SKILL. Hold last 7 chars, output rest.
            const safeLen = combined.length - (CLOSE_LEN - 1);
            const safe = combined.substring(0, safeLen);
            formContent += safe;
            newFormContent += safe;
            pendingClose = lastPossible;
            buffer = "";
            break;
          }

          // Does not look like partial </SKILL>. Output all as content.
          formContent += combined;
          newFormContent += combined;
          buffer = "";
          pendingClose = "";
          break;
        } else {
          const openIdx = buffer.indexOf(SKILL_OPEN);
          if (openIdx !== -1) {
            buffer = buffer.substring(openIdx + SKILL_OPEN.length);
            isInsideSkillTag = true;
            pendingClose = "";
          } else {
            if (buffer.includes("<")) {
              break;
            } else {
              buffer = "";
              break;
            }
          }
        }
      }

      return {
        formContent,
        summaryContent,
        newFormContent,
        newSummaryContent,
        summaryStarted,
      };
    },

    getFullResult(): SkillDelimiterParseResult {
      if (isInsideSkillTag) {
        // Any remaining buffer or pendingClose is form content
        if (buffer.length > 0) {
          formContent += buffer;
        }
        if (pendingClose.length > 0) {
          formContent += pendingClose;
        }
      }
      isInsideSkillTag = false;
      return {
        formContent,
        summaryContent,
        newFormContent: "",
        newSummaryContent: "",
        summaryStarted: true,
      };
    },
  };
}

/**
 * SSE event types for streaming skill creation
 */
export interface SkillCreationStreamEvent {
  type: "step_count" | "final_answer" | "skill_content" | "skill_result" | "done" | "error";
  content?: string;
  skill_name?: string;
  skill_description?: string;
  tags?: string[];
  message?: string;
}

/**
 * Interactive skill creation via SSE stream with progress updates.
 * Uses <SKILL></SKILL> delimiters to separate form content from summary.
 */
export const createSimpleSkillStream = async (
  request: CreateSimpleSkillRequest,
  callbacks: {
    onStepCount: (step: number, description: string) => void;
    onThinkingVisible: (visible: boolean) => void;
    onThinkingUpdate: (step: number, description: string) => void;
    onSkillContent?: (content: string) => void;
    onSkillResult?: (result: { skill_name: string; skill_description: string; tags: string[] }) => void;
    onFormContent?: (content: string) => void;
    onSummaryContent?: (content: string) => void;
    onDone: (finalResult: SkillDelimiterParseResult) => void;
    onError: (message: string) => void;
  }
): Promise<SkillDelimiterParseResult> => {
  const response = await fetch(API_ENDPOINTS.skills.createSimple, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    callbacks.onError(`HTTP error: ${response.status}`);
    return { formContent: "", summaryContent: "", newFormContent: "", newSummaryContent: "", summaryStarted: false };
  }

  if (!response.body) {
    callbacks.onError("No response body");
    return { formContent: "", summaryContent: "", newFormContent: "", newSummaryContent: "", summaryStarted: false };
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  const delimiterParser = createSkillDelimiterParser();
  // Track pending stream promises so 'done' case can await them
  const pendingStreamPromises: Promise<void>[] = [];

  callbacks.onThinkingVisible(true);

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      // Strip any stray \r so the buffer uses only \n internally.
      // This handles Windows CRLF line endings in the SSE stream.
      const cleanChunk = decoder.decode(value, { stream: true }).replace(/\r/g, "");
      buffer += cleanChunk;
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
            case "skill_content":
              if (event.content) {
                const parsed = delimiterParser.update(event.content);
                // Only send to form when still inside <SKILL> tags (summaryStarted=false).
                // Once summaryStarted=true, all content is summary text, not form content.
                if (parsed.newFormContent && !parsed.summaryStarted && callbacks.onFormContent) {
                  callbacks.onFormContent(parsed.newFormContent);
                }
                if (parsed.newSummaryContent && callbacks.onSummaryContent) {
                  callbacks.onSummaryContent(parsed.newSummaryContent);
                }
                if (callbacks.onSkillContent) {
                  callbacks.onSkillContent(event.content);
                }
              }
              break;
            case "final_answer":
              if (event.content) {
                // final_answer contains the FULL response including <SKILL> block.
                // The SKILL content was already streamed via skill_content events.
                // Only extract the summary (content after </SKILL>) from final_answer.
                const summary = extractSummaryFromFinalAnswer(event.content);
                if (summary && callbacks.onSummaryContent) {
                  // Use async loop with setTimeout to allow React to render each chunk.
                  // Without the delay, all state updates batch into one render.
                  const CHUNK_SIZE = 3; // characters per chunk
                  const CHUNK_DELAY = 15; // ms between chunks
                  // Wrap streaming in a promise so we can await it before onDone
                  const streamPromise = new Promise<void>((resolve) => {
                    const streamChunk = (index: number): void => {
                      if (index >= summary.length) {
                        resolve();
                        return;
                      }
                      const chunk = summary.substring(index, index + CHUNK_SIZE);
                      callbacks.onSummaryContent!(chunk);
                      setTimeout(() => streamChunk(index + CHUNK_SIZE), CHUNK_DELAY);
                    };
                    streamChunk(0);
                  });
                  // Store promise to be awaited in 'done' case
                  pendingStreamPromises.push(streamPromise);
                }
              }
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
              {
                const finalResult = delimiterParser.getFullResult();
                // Await all pending stream promises before calling onDone
                Promise.all(pendingStreamPromises)
                  .then(() => {
                    try {
                      callbacks.onDone(finalResult);
                    } catch {
                      // Ignore callback errors
                    }
                  })
                  .catch(() => {
                    // Ignore promise errors
                    try {
                      callbacks.onDone(finalResult);
                    } catch {
                      // Ignore callback errors
                    }
                  });
              }
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
  return delimiterParser.getFullResult();
};

/**
 * Delete a skill by name
 * @param skillName skill name to delete
 * @returns delete result
 */
export const deleteSkillByName = async (skillName: string) => {
  return deleteSkill(skillName);
};
