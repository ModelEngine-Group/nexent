"use client";

import { useState, useEffect, useMemo, useRef, type ChangeEvent } from "react";
import { useTranslation } from "react-i18next";
import {
  Modal,
  Tabs,
  Form,
  Input,
  Button,
  message,
  Flex,
  Spin,
  Tooltip,
} from "antd";
import {
  Upload as UploadIcon,
  Send,
  Trash2,
  MessageCircle,
  Box,
  Bot,
  Loader2,
  Square,
} from "lucide-react";
import {
  extractSkillInfo,
  extractSkillInfoFromContent,
} from "@/lib/skillFileUtils";
import yaml from "js-yaml";
import {
  type SkillFormData,
  type ChatMessage,
  type SkillFileContent,
} from "@/types/skill";
import {
  fetchSkillsList,
  submitSkillForm,
  submitSkillFromFile,
  findSkillByName,
  createSkillStream,
  stopSkillCreation,
  getThinkingSteps,
  type SkillListItem,
  type SkillData,
} from "@/services/skillService";
import type { MyEditableSkillItem } from "@/types/skillRepository";
import {
  fetchSkillById,
  fetchSkillFileContent,
  fetchSkillFiles,
  type SkillFileNode,
} from "@/services/agentConfigService";
import { normalizeSkillFiles } from "@/lib/skillFileUtils";
import { MarkdownRenderer } from "@/components/common/markdownRenderer";
import log from "@/lib/logger";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { useGroupDetails, useGroupList } from "@/hooks/group/useGroupList";
import SkillDraftPanel from "./SkillDraftPanel";

const { TextArea } = Input;

interface SkillBuildModalProps {
  isOpen: boolean;
  onCancel: () => void;
  onSuccess: () => void | Promise<void>;
  editingSkill?: MyEditableSkillItem | null;
  onBeforeEditSave?: (skill: MyEditableSkillItem) => Promise<boolean>;
}

interface StreamedFrontmatter {
  name: string;
  description: string;
  tags: string[];
}

function parseStreamedFrontmatter(content: string): StreamedFrontmatter | null {
  try {
    const parsed = yaml.load(content) as Record<string, unknown> | null;
    if (!parsed || typeof parsed !== "object") {
      return null;
    }
    return {
      name: typeof parsed.name === "string" ? parsed.name.trim() : "",
      description:
        typeof parsed.description === "string" ? parsed.description.trim() : "",
      tags: Array.isArray(parsed.tags)
        ? parsed.tags.filter((tag): tag is string => typeof tag === "string")
        : [],
    };
  } catch {
    return null;
  }
}

function mergeGeneratedSkillTabs(
  currentTabs: SkillFileContent[],
  generatedTabs: SkillFileContent[],
  skillContent: string
) {
  const generatedByPath = new Map(
    generatedTabs.map((tab) => [tab.path, tab.content])
  );
  const currentPaths = new Set(currentTabs.map((tab) => tab.path));
  const updatedTabs = currentTabs.map((tab) => {
    if (tab.path === "SKILL.md") {
      return { ...tab, content: skillContent };
    }
    const generatedContent = generatedByPath.get(tab.path);
    return generatedContent ? { ...tab, content: generatedContent } : tab;
  });
  const newTabs = generatedTabs.filter((tab) => !currentPaths.has(tab.path));
  const finalTabs = [...updatedTabs, ...newTabs].sort((a, b) => {
    if (a.path === "SKILL.md") return -1;
    if (b.path === "SKILL.md") return 1;
    return a.path.localeCompare(b.path);
  });
  return { updatedTabs, finalTabs };
}

function flattenSkillFiles(
  nodes: SkillFileNode[],
  skillName: string
): string[] {
  const paths: string[] = [];
  const walk = (items: SkillFileNode[], parentPath = "") => {
    items.forEach((item) => {
      const isRootSkillDirectory =
        !parentPath && item.type === "directory" && item.name === skillName;
      const path = isRootSkillDirectory
        ? ""
        : parentPath
          ? `${parentPath}/${item.name}`
          : item.name;
      if (item.type === "file") {
        paths.push(path);
      } else if (item.children?.length) {
        walk(item.children, path);
      }
    });
  };
  walk(nodes);
  return paths;
}

function sortSkillTabs(tabs: SkillFileContent[]): SkillFileContent[] {
  return [...tabs].sort((a, b) => {
    if (a.path === "SKILL.md") return -1;
    if (b.path === "SKILL.md") return 1;
    return a.path.localeCompare(b.path);
  });
}

export default function SkillBuildModal({
  isOpen,
  onCancel,
  onSuccess,
  editingSkill,
  onBeforeEditSave,
}: SkillBuildModalProps) {
  const { t, i18n } = useTranslation("common");
  const { user, getAccessibleGroupIds } = useAuthorizationContext();
  const [form] = Form.useForm<SkillFormData>();
  const isEditMode = Boolean(editingSkill);
  const { data: groupData } = useGroupList(user?.tenantId ?? null);
  const accessibleGroupIds = useMemo(
    () => getAccessibleGroupIds(),
    [getAccessibleGroupIds]
  );
  const { groups: filteredGroups } = useGroupDetails(
    groupData?.groups ?? [],
    accessibleGroupIds
  );
  const groupSelectOptions = useMemo(
    () =>
      filteredGroups.map((group) => ({
        label: group.group_name,
        value: group.group_id,
      })),
    [filteredGroups]
  );
  const [activeTab, setActiveTab] = useState<string>("interactive");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isLoadingEditFiles, setIsLoadingEditFiles] = useState(false);
  const [loadedEditSkillId, setLoadedEditSkillId] = useState<number | null>(
    null
  );
  const [editFilesError, setEditFilesError] = useState<string | null>(null);
  const [allSkills, setAllSkills] = useState<SkillListItem[]>([]);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadExtractedSkillName, setUploadExtractedSkillName] =
    useState<string>("");
  const [uploadExtractingName, setUploadExtractingName] = useState(false);

  // Interactive creation state
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [isChatLoading, setIsChatLoading] = useState(false);
  const [thinkingDescription, setThinkingDescription] = useState<string>("");
  const [isThinkingVisible, setIsThinkingVisible] = useState(false);
  const [interactiveSkillName, setInteractiveSkillName] = useState<string>("");
  const chatContainerRef = useRef<HTMLDivElement>(null);

  // Content input streaming state - multi-file tabs
  const [skillTabs, setSkillTabs] = useState<SkillFileContent[]>([
    { path: "SKILL.md", content: "" },
  ]);
  const [activeSkillTab, setActiveSkillTab] = useState<string>("SKILL.md");
  const [isStreaming, setIsStreaming] = useState(false);

  // Summary content for chat bubble
  const [summaryContent, setSummaryContent] = useState<string>("");

  // Frontmatter buffer for streaming - accumulate and parse at completion
  const frontmatterBufferRef = useRef<string>("");

  // Refs for per-tab scroll state: tracks whether each textarea should auto-scroll
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const textareaRefs = useRef<Record<string, any>>({});
  const shouldAutoScrollRef = useRef<Record<string, boolean>>({});

  // Detect if the textarea is currently near the bottom (within threshold pixels)
  const isTextareaAtBottom = (tabPath: string): boolean => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const ref = textareaRefs.current[tabPath] as any;
    const textarea = ref?.resizableTextArea?.textArea || ref?.textArea || ref;
    if (!textarea) return true;
    return (
      textarea.scrollHeight - textarea.scrollTop - textarea.clientHeight < 20
    );
  };

  // Update shouldAutoScrollRef when user scrolls manually
  const handleTextareaScroll = (tabPath: string) => {
    shouldAutoScrollRef.current[tabPath] = isTextareaAtBottom(tabPath);
  };

  // Scroll textarea to bottom, respecting user scroll preference and throttled via RAF
  const scrollTextareaToBottom = (tabPath: string) => {
    if (!shouldAutoScrollRef.current[tabPath]) return;
    requestAnimationFrame(() => {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const ref = textareaRefs.current[tabPath] as any;
      const textarea = ref?.resizableTextArea?.textArea || ref?.textArea || ref;
      if (textarea) {
        textarea.scrollTop = textarea.scrollHeight;
      }
    });
  };

  // Track if component is mounted to prevent state updates after unmount
  const isMountedRef = useRef(true);
  const currentAssistantIdRef = useRef<string>("");
  // Track if streaming is complete to prevent late onFormContent callbacks from overwriting cleaned content
  const isStreamingCompleteRef = useRef(false);

  // Track current tabs during streaming to avoid stale closure issues
  const streamingTabsRef = useRef<SkillFileContent[]>([
    { path: "SKILL.md", content: "" },
  ]);

  // AbortController ref for stopping streaming
  const abortControllerRef = useRef<AbortController | null>(null);

  // Task ID ref for backend stop API
  const taskIdRef = useRef<string>("");

  // Multi-turn conversation state: accumulated skill draft from previous turns.
  // When the user sends a follow-up message, this draft is passed as existing_skill
  // so the backend can refine the skill rather than generating from scratch.
  const [accumulatedDraft, setAccumulatedDraft] = useState<{
    name: string;
    description: string;
    tags: string[];
    content: string;
  } | null>(null);

  useEffect(() => {
    if (!isOpen) return;
    let cancelled = false;
    fetchSkillsList()
      .then((list) => {
        if (!cancelled) {
          setAllSkills(list);
        }
      })
      .catch((err) => {
        log.error("Failed to load skills for SkillBuildModal", err);
      });
    return () => {
      cancelled = true;
    };
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen || isEditMode) return;
    form.setFieldsValue({
      group_ids: accessibleGroupIds,
      ingroup_permission: "READ_ONLY",
    });
  }, [accessibleGroupIds, form, isEditMode, isOpen]);

  useEffect(() => {
    if (!isOpen) {
      // Abort any ongoing streaming request
      if (abortControllerRef.current) {
        abortControllerRef.current.abort("Modal closed");
        abortControllerRef.current = null;
      }
      // Reset task ID
      taskIdRef.current = "";
      setActiveTab("interactive");
      setUploadFile(null);
      setChatMessages([]);
      setChatInput("");
      setInteractiveSkillName("");
      setUploadExtractingName(false);
      setUploadExtractedSkillName("");
      setThinkingDescription("");
      setIsThinkingVisible(false);
      setSkillTabs([{ path: "SKILL.md", content: "" }]);
      streamingTabsRef.current = [{ path: "SKILL.md", content: "" }];
      shouldAutoScrollRef.current = {};
      setActiveSkillTab("SKILL.md");
      setIsStreaming(false);
      setSummaryContent("");
      currentAssistantIdRef.current = "";
      setAccumulatedDraft(null);
      setLoadedEditSkillId(null);
      setEditFilesError(null);
      setIsLoadingEditFiles(false);
    }
  }, [isOpen]);

  // Track component mount status for async callback safety
  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  // Sync summary content to the current assistant chat message for real-time display.
  useEffect(() => {
    if (!currentAssistantIdRef.current) return;
    setChatMessages((prev) => {
      if (!prev.some((m) => m.id === currentAssistantIdRef.current))
        return prev;
      return prev.map((msg) =>
        msg.id === currentAssistantIdRef.current
          ? { ...msg, content: summaryContent }
          : msg
      );
    });
  }, [summaryContent]);

  // Detect create/update mode when extracted skill name changes (upload tab)
  const [uploadIsCreateMode, setUploadIsCreateMode] = useState(true);
  useEffect(() => {
    const nameValue = uploadExtractedSkillName.trim();
    if (nameValue) {
      const matched = findSkillByName(nameValue, allSkills);
      setUploadIsCreateMode(!matched);
    } else {
      setUploadIsCreateMode(true);
    }
  }, [uploadExtractedSkillName, allSkills]);

  useEffect(() => {
    if (!isOpen || !editingSkill) return;
    const skillName = editingSkill.name?.trim() || "";
    let cancelled = false;

    const applySkillInfo = (
      skill: Partial<SkillListItem> & { content?: string | null }
    ) => {
      if (cancelled) return;
      const nextName = skill.name?.trim() || skillName;
      setInteractiveSkillName(nextName);
      form.setFieldsValue({
        name: nextName,
        description: skill.description || "",
        source: skill.source || "custom",
        tags: Array.isArray(skill.tags) ? skill.tags : [],
        group_ids: Array.isArray(skill.group_ids) ? skill.group_ids : [],
        ingroup_permission: skill.ingroup_permission || "READ_ONLY",
      });
    };

    setActiveTab("interactive");
    setEditFilesError(null);
    setLoadedEditSkillId(null);
    setIsLoadingEditFiles(true);

    const loadEditFiles = async () => {
      try {
        const result = await fetchSkillById(editingSkill.skill_id);
        const skillInfo =
          result.success && result.data
            ? result.data
            : {
                name: skillName,
                description: editingSkill.description || "",
                source: editingSkill.source || "custom",
                tags: editingSkill.tags || [],
                group_ids: editingSkill.group_ids || [],
                ingroup_permission:
                  editingSkill.ingroup_permission || "READ_ONLY",
              };
        const resolvedSkillName = skillInfo.name?.trim() || skillName;
        const fileTree = await fetchSkillFiles(resolvedSkillName);
        const filePaths = flattenSkillFiles(
          normalizeSkillFiles(fileTree),
          resolvedSkillName
        );
        if (filePaths.length === 0) {
          throw new Error("Skill file tree is empty");
        }
        const tabs = await Promise.all(
          filePaths.map(async (path) => {
            const content = await fetchSkillFileContent(
              resolvedSkillName,
              path
            );
            if (content === null) {
              throw new Error(`Failed to load skill file: ${path}`);
            }
            return { path, content };
          })
        );
        if (!cancelled) {
          const sortedTabs = sortSkillTabs(tabs);
          applySkillInfo(skillInfo);
          setSkillTabs(sortedTabs);
          setActiveSkillTab(sortedTabs[0]?.path || "SKILL.md");
          setLoadedEditSkillId(editingSkill.skill_id);
        }
      } catch (error) {
        log.error("Failed to load skill files for editing:", error);
        if (!cancelled) {
          setEditFilesError(t("skillManagement.message.loadFilesFailed"));
        }
      } finally {
        if (!cancelled) {
          setIsLoadingEditFiles(false);
        }
      }
    };

    void loadEditFiles();

    return () => {
      cancelled = true;
    };
  }, [isOpen, editingSkill?.skill_id]);

  const handleNameChange = (event: ChangeEvent<HTMLInputElement>) => {
    const value = event.target.value;
    setInteractiveSkillName(value);
    form.setFieldsValue({ name: value });
    if (!value.trim()) {
      // Reset skillTabs when input is cleared
      setSkillTabs([{ path: "SKILL.md", content: "" }]);
      setActiveSkillTab("SKILL.md");
    }
  };

  const closeModal = () => {
    form.resetFields();
    onCancel();
  };

  // Cleanup when modal is closed
  const handleModalClose = () => {
    closeModal();
  };

  const handleManualSubmit = async () => {
    try {
      if (isEditMode && (isLoadingEditFiles || editFilesError)) {
        message.error(
          editFilesError || t("skillManagement.message.loadFilesFailed")
        );
        return;
      }
      const values = await form.validateFields();
      if (isEditMode && editingSkill && onBeforeEditSave) {
        const shouldContinue = await onBeforeEditSave(editingSkill);
        if (!shouldContinue) {
          return;
        }
      }
      setIsSubmitting(true);

      const skillTab = skillTabs.find((t) => t.path === "SKILL.md");
      const content = skillTab?.content || "";

      const extraFiles = skillTabs
        .filter((t) => t.path !== "SKILL.md")
        .map((t) => ({
          path: t.path,
          content: t.content || "",
        }));

      await submitSkillForm(
        {
          ...values,
          content,
          files: extraFiles.length > 0 ? extraFiles : undefined,
        } as SkillData,
        allSkills,
        onSuccess,
        closeModal,
        t,
        isEditMode && editingSkill?.skill_id
          ? { mode: "edit", skillId: editingSkill.skill_id }
          : { mode: "create" }
      );
    } catch (error) {
      log.error("Skill create/update error:", error);
      const errorMessage = error instanceof Error ? error.message : "";
      if (/already exists|409/.test(errorMessage)) {
        form.setFields([
          {
            name: "name",
            errors: [t("skillManagement.message.nameExists")],
          },
        ]);
        return;
      }
      message.error(t("skillManagement.message.submitFailed"));
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleUploadSubmit = async () => {
    if (!uploadFile) {
      message.warning(t("skillManagement.message.pleaseSelectFile"));
      return;
    }

    if (!uploadExtractedSkillName.trim()) {
      message.warning(t("skillManagement.form.nameRequired"));
      return;
    }

    setIsSubmitting(true);
    try {
      await submitSkillFromFile(
        uploadExtractedSkillName,
        uploadFile,
        allSkills,
        onSuccess,
        closeModal,
        t
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  // Helper function to update tab content
  const updateTabContent = (tabPath: string, content: string) => {
    setSkillTabs((prev) => {
      const newTabs = prev.map((tab) =>
        tab.path === tabPath ? { ...tab, content: tab.content + content } : tab
      );
      streamingTabsRef.current = newTabs;
      return newTabs;
    });
    // Scroll to bottom after content update during streaming
    if (isStreaming) {
      setTimeout(() => scrollTextareaToBottom(tabPath), 0);
    }
  };

  const ensureStreamingTab = (tabPath: string) => {
    setSkillTabs((prev) => {
      const newTabs = prev.find((tab) => tab.path === tabPath)
        ? prev
        : [...prev, { path: tabPath, content: "" }];
      streamingTabsRef.current = newTabs;
      shouldAutoScrollRef.current[tabPath] = true;
      return newTabs;
    });
  };

  // Assemble skill files into XML-like format for agent consumption
  const assembleSkillContent = (tabs: SkillFileContent[]): string => {
    const parts: string[] = [];

    for (const tab of tabs) {
      if (tab.path === "SKILL.md") {
        parts.push(`<SKILL>\n${tab.content}\n</SKILL>`);
      } else {
        parts.push(`<FILE path="${tab.path}">\n${tab.content}\n</FILE>`);
      }
    }

    return parts.join("\n\n");
  };

  // Parse frontmatter YAML and update form fields
  const parseAndUpdateFrontmatter = (frontmatterYaml: string) => {
    const parsed = parseStreamedFrontmatter(frontmatterYaml);
    if (!parsed) {
      return;
    }

    const updates: Partial<SkillFormData> = {};
    if (parsed.name && !isEditMode) {
      updates.name = parsed.name;
      setInteractiveSkillName(parsed.name);
    }
    if (parsed.description) {
      updates.description = parsed.description;
    }
    if (parsed.tags.length > 0) {
      updates.tags = parsed.tags;
    }
    if (Object.keys(updates).length > 0) {
      form.setFieldsValue(updates);
    }
  };

  // Handle chat send for interactive creation
  const handleChatSend = async () => {
    if (!chatInput.trim() || isChatLoading) return;

    const currentInput = chatInput.trim();
    setChatInput("");

    // Read current form fields to provide context to the model.
    const formValues = form.getFieldsValue();
    const draft = accumulatedDraft;

    // Assemble skill content from all tabs
    const assembledContent = assembleSkillContent(skillTabs);
    const formContext = [
      formValues.name
        ? t("skillManagement.chat.context.name", { name: formValues.name })
        : "",
      formValues.description
        ? t("skillManagement.chat.context.description", {
            description: formValues.description,
          })
        : "",
      formValues.tags?.length
        ? t("skillManagement.chat.context.tags", {
            tags: formValues.tags.join(", "),
          })
        : "",
      assembledContent
        ? t("skillManagement.chat.context.content", {
            content: assembledContent,
          })
        : "",
    ]
      .filter(Boolean)
      .join("\n\n");

    const userMessage: ChatMessage = {
      id: Date.now().toString(),
      role: "user",
      content: currentInput,
      timestamp: new Date(),
    };

    setChatMessages((prev) => [...prev, userMessage]);
    setIsChatLoading(true);
    setIsThinkingVisible(true);
    setThinkingDescription(t("skillManagement.generatingSkill"));

    // Clear content input before streaming — start fresh so the streamed content
    // reflects the (possibly refined) result of this turn.
    setSkillTabs([{ path: "SKILL.md", content: "" }]);
    streamingTabsRef.current = [{ path: "SKILL.md", content: "" }];
    shouldAutoScrollRef.current = { "SKILL.md": true };
    setActiveSkillTab("SKILL.md");
    setIsStreaming(true);
    setSummaryContent("");
    isStreamingCompleteRef.current = false;

    const assistantId = (Date.now() + 1).toString();

    setChatMessages((prev) => [
      ...prev,
      {
        id: assistantId,
        role: "assistant",
        content: "",
        timestamp: new Date(),
      },
    ]);

    currentAssistantIdRef.current = assistantId;

    try {
      // Create AbortController for this request
      abortControllerRef.current = new AbortController();

      // On first turn, no existing_skill is sent → backend creates from scratch.
      // On subsequent turns (accumulatedDraft exists), existing_skill is passed
      // → backend follows the modify-workflow template and refines the draft.
      const userPrompt = formContext
        ? t("skillManagement.chat.userRequestWithContext", {
            request: currentInput,
            context: formContext,
          })
        : t("skillManagement.chat.userRequest", { request: currentInput });

      await createSkillStream(
        {
          user_request: userPrompt,
          existing_skill: draft
            ? {
                name: draft.name || formValues.name || "",
                description: draft.description || formValues.description || "",
                tags: draft.tags?.length ? draft.tags : formValues.tags || [],
                content: assembledContent,
              }
            : undefined,
          complexity: "complicated",
          language: i18n.language?.startsWith("en") ? "en" : "zh",
        },
        {
          onTaskId: (taskId) => {
            taskIdRef.current = taskId;
          },
          onThinkingUpdate: (step, desc) => {
            setThinkingDescription(
              desc || t("skillManagement.generatingSkill")
            );
          },
          onThinkingVisible: (visible) => {
            setIsThinkingVisible(visible);
          },
          onStepCount: (step) => {
            setThinkingDescription(
              getThinkingSteps(i18n.language).find((s) => s.step === step)?.description ||
                t("skillManagement.generatingSkill")
            );
          },
          onFrontmatter: (content) => {
            frontmatterBufferRef.current += content;
            const parsed = parseStreamedFrontmatter(
              frontmatterBufferRef.current
            );
            if (!parsed) return;
            if (parsed.name && !isEditMode) {
              form.setFieldsValue({ name: parsed.name });
              setInteractiveSkillName(parsed.name);
            }
            if (parsed.description) {
              form.setFieldsValue({ description: parsed.description });
            }
            if (parsed.tags.length > 0) {
              form.setFieldsValue({ tags: parsed.tags });
            }
          },
          onSkillBody: (content) => {
            if (isStreamingCompleteRef.current) return;
            setSummaryContent("");
            // Frontmatter is complete when skill_body starts - clear the buffer
            frontmatterBufferRef.current = "";
            // Only add body content to textarea (no frontmatter)
            updateTabContent("SKILL.md", content);
          },
          onFileContent: (path, content, isNewFile) => {
            if (isStreamingCompleteRef.current) return;
            setSummaryContent("");

            if (isNewFile) {
              ensureStreamingTab(path);
            }

            updateTabContent(path, content);
            setActiveSkillTab(path);
          },
          onSummary: (content) => {
            if (isStreamingCompleteRef.current) return;
            setSummaryContent((prev) => prev + content);
          },
          onDone: (result) => {
            if (!isMountedRef.current) return;
            setIsThinkingVisible(false);
            setIsStreaming(false);
            currentAssistantIdRef.current = "";
            isStreamingCompleteRef.current = true;

            // Get SKILL.md content and strip frontmatter for textarea display
            const skillTab = result.skillTabs.find(
              (t) => t.path === "SKILL.md"
            );
            const fullContent = skillTab?.content || "";

            if (fullContent || result.skillTabs.length > 0) {
              // Strip frontmatter from SKILL.md content for textarea display
              const skillInfo = extractSkillInfoFromContent(fullContent);
              const contentWithoutFrontmatter =
                skillInfo?.contentWithoutFrontmatter || "";

              const currentTabs = streamingTabsRef.current;
              const { updatedTabs, finalTabs } = mergeGeneratedSkillTabs(
                currentTabs,
                result.skillTabs,
                contentWithoutFrontmatter
              );

              setSkillTabs(finalTabs);

              if (skillInfo?.name && !isEditMode) {
                form.setFieldsValue({ name: skillInfo.name });
                setInteractiveSkillName(skillInfo.name);
              }
              if (skillInfo?.description) {
                form.setFieldsValue({ description: skillInfo.description });
              }
              if (skillInfo?.tags?.length) {
                form.setFieldsValue({ tags: skillInfo.tags });
              }

              // Update accumulated draft with assembled content for next turn
              const assembledDraft = assembleSkillContent(updatedTabs);
              const newDraft = {
                name: skillInfo?.name || draft?.name || "",
                description: skillInfo?.description || draft?.description || "",
                tags: skillInfo?.tags?.length
                  ? skillInfo.tags
                  : draft?.tags || [],
                content: assembledDraft,
              };
              setAccumulatedDraft(newDraft);

              // Scroll to bottom after content is fully loaded
              setTimeout(() => scrollTextareaToBottom("SKILL.md"), 0);

              message.success(t("skillManagement.message.skillReadyForSave"));
            }
          },
          onError: (errorMsg) => {
            log.error("Interactive skill creation error:", errorMsg);
            message.error(t("skillManagement.message.chatError"));
            setChatMessages((prev) => prev.filter((m) => m.id !== assistantId));
            setIsStreaming(false);
            currentAssistantIdRef.current = "";
          },
        },
        { signal: abortControllerRef.current.signal }
      );
    } catch (error) {
      // Handle AbortError gracefully when user stops the stream
      const err = error as Error;
      if (err?.name === "AbortError") {
        // User stopped - just reset states silently
        setIsChatLoading(false);
        setIsStreaming(false);
        setIsThinkingVisible(false);
        return;
      }
      log.error("Interactive skill creation error:", error);
      message.error(t("skillManagement.message.chatError"));
      setChatMessages((prev) => prev.filter((m) => m.id !== assistantId));
      setIsStreaming(false);
    } finally {
      abortControllerRef.current = null;
      setIsChatLoading(false);
    }
  };

  // Handle stop - cancel the ongoing streaming request
  const handleStop = async () => {
    // Call backend stop API first
    if (taskIdRef.current) {
      try {
        await stopSkillCreation(taskIdRef.current);
      } catch (error) {
        log.error("Failed to stop backend task:", error);
      }
    }

    // Abort frontend fetch
    if (abortControllerRef.current) {
      abortControllerRef.current.abort("User stopped");
      abortControllerRef.current = null;
    }

    // Reset all states
    setIsChatLoading(false);
    setIsStreaming(false);
    setIsThinkingVisible(false);
    currentAssistantIdRef.current = "";
    taskIdRef.current = "";
    isStreamingCompleteRef.current = true;
  };

  // Scroll to bottom of chat when new messages arrive
  useEffect(() => {
    if (chatContainerRef.current) {
      chatContainerRef.current.scrollTop =
        chatContainerRef.current.scrollHeight;
    }
  }, [chatMessages]);

  const modalBodyFrame = "min(92vh, 760px)";
  const editingSkillName =
    editingSkill?.name?.trim() || interactiveSkillName.trim();
  const isEditContentReady =
    !isEditMode || loadedEditSkillId === editingSkill?.skill_id;

  const renderUploadTab = () => {
    const existingSkill = allSkills.find(
      (s) =>
        s.name.trim().toLowerCase() ===
        uploadExtractedSkillName.trim().toLowerCase()
    );

    const handleFileSelection = async (files: FileList | null) => {
      if (!files || files.length === 0) return;
      const file = files[files.length - 1];

      if (uploadFile) {
        message.warning(t("skillManagement.message.onlyOneFileAllowed"));
      }

      setUploadFile(file);
      setUploadExtractingName(true);
      try {
        const skillInfo = await extractSkillInfo(file);
        const extractedName = skillInfo?.name || "";
        const extractedDesc = skillInfo?.description || "";
        if (!extractedName || !extractedDesc) {
          setUploadFile(null);
          setUploadExtractedSkillName("");
          message.warning(
            t("skillManagement.message.nameOrDescriptionMissing")
          );
          return;
        }
        setUploadExtractedSkillName(extractedName);
      } finally {
        setUploadExtractingName(false);
      }
    };

    return (
      <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div className="border-b border-slate-200 bg-slate-50/80 px-5 py-4">
          <p className="text-sm font-semibold text-gray-800">
            {t("skillManagement.tabs.install")}
          </p>
          <p className="text-xs text-gray-500">
            {t("skillManagement.form.uploadHint")}
          </p>
        </div>

        <div className="flex flex-1 flex-col gap-4 p-5">
          <Spin spinning={uploadExtractingName}>
            <div>
              <label className="mb-1 block text-sm font-medium text-gray-700">
                {t("skillManagement.form.name")}
              </label>
              <Input
                value={uploadExtractedSkillName}
                readOnly
                placeholder={t(
                  "skillManagement.form.uploadSkillNamePlaceholder"
                )}
                style={{ fontWeight: 500 }}
                status={
                  existingSkill
                    ? "error"
                    : !uploadExtractedSkillName && uploadFile
                      ? "warning"
                      : undefined
                }
              />
              {uploadExtractedSkillName && existingSkill ? (
                <span className="ml-1 text-xs text-red-500">
                  {t("skillManagement.form.uploadSkillExists")}
                </span>
              ) : null}
              {uploadExtractedSkillName && !existingSkill ? (
                <span className="text-xs text-green-600">
                  {t("skillManagement.form.newSkillHint")}
                </span>
              ) : null}
            </div>
          </Spin>

          <label
            htmlFor="skill-upload-input"
            className="flex flex-1 cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed border-slate-200 bg-slate-50/70 px-6 py-10 text-center transition-colors hover:border-blue-400 hover:bg-blue-50/50"
            onDragOver={(e) => {
              e.preventDefault();
              e.stopPropagation();
            }}
            onDragEnter={(e) => {
              e.preventDefault();
              e.stopPropagation();
            }}
            onDragLeave={(e) => {
              e.preventDefault();
              e.stopPropagation();
            }}
            onDrop={(e) => {
              e.preventDefault();
              e.stopPropagation();
              handleFileSelection(e.dataTransfer.files);
            }}
          >
            <UploadIcon className="mb-3 text-blue-600" size={48} />
            <p className="mb-2 text-base font-medium text-gray-700">
              {t("skillManagement.form.uploadDragText")}
            </p>
            <p className="text-sm text-gray-500">
              {t("skillManagement.form.uploadHint")}
            </p>
            <input
              id="skill-upload-input"
              type="file"
              accept=".md,.zip"
              className="hidden"
              onChange={(e) => handleFileSelection(e.target.files)}
            />
          </label>

          {uploadFile ? (
            <div className="rounded-lg border border-gray-200 bg-white">
              <div className="flex items-center justify-between border-b border-gray-100 bg-gray-50 px-3 py-2">
                <h4 className="m-0 text-sm font-medium text-gray-700">
                  {t("knowledgeBase.upload.completed")}
                </h4>
                <span className="text-xs text-gray-500">1</span>
              </div>
              <div className="flex items-center justify-between px-3 py-2 hover:bg-gray-50">
                <div className="min-w-0 flex-1">
                  <div className="truncate text-xs font-medium text-gray-700">
                    {uploadFile.name}
                  </div>
                </div>
                <Button
                  type="text"
                  danger
                  size="small"
                  className="ml-2 flex-shrink-0"
                  onClick={(event) => {
                    event.stopPropagation();
                    setUploadFile(null);
                    setUploadExtractedSkillName("");
                    const input = document.getElementById(
                      "skill-upload-input"
                    ) as HTMLInputElement;
                    if (input) input.value = "";
                  }}
                >
                  <Trash2 size={14} />
                </Button>
              </div>
            </div>
          ) : null}
        </div>
      </div>
    );
  };
  const renderChatPanel = () => (
    <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div
        ref={chatContainerRef}
        className="custom-scrollbar flex-1 space-y-3 overflow-y-auto px-4 py-5"
      >
        {chatMessages.length === 0 ? (
          <div className="flex pt-7">
            <div className="mr-3 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-blue-600 text-white">
              <Bot size={16} />
            </div>
            <div className="max-w-[88%] rounded-2xl bg-blue-50 px-5 py-3 text-sm leading-6 text-slate-700">
              {isEditMode ? (
                <>
                  <p>
                    {t("skillManagement.chat.editGreetingTitle", {
                      name: editingSkillName,
                    })}
                  </p>
                  <p className="mt-3">
                    {t("skillManagement.chat.editGreetingBody")}
                  </p>
                </>
              ) : (
                <>
                  <p>{t("skillManagement.chat.createGreetingTitle")}</p>
                  <p className="mt-3">
                    {t("skillManagement.chat.createGreetingExample")}
                  </p>
                </>
              )}
            </div>
          </div>
        ) : null}
        {chatMessages.map((msg) => (
          <div
            key={msg.id}
            className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
          >
            <div
              className={`max-w-[88%] rounded-2xl px-3 py-2 text-sm leading-relaxed ${
                msg.role === "user"
                  ? "rounded-tr-sm bg-blue-500 text-white"
                  : "rounded-tl-sm bg-gray-100 text-gray-800"
              }`}
            >
              {msg.role === "assistant" &&
              msg.id === currentAssistantIdRef.current &&
              isThinkingVisible ? (
                <div className="flex min-w-[200px] flex-col items-center">
                  <Loader2 size={24} className="animate-spin text-blue-500" />
                  {thinkingDescription ? (
                    <span className="mt-2 text-xs text-gray-500">
                      {thinkingDescription}
                    </span>
                  ) : null}
                </div>
              ) : msg.role === "assistant" ? (
                <div className="markdown-content">
                  <MarkdownRenderer content={msg.content} className="text-sm" />
                </div>
              ) : (
                <div className="whitespace-pre-wrap">{msg.content}</div>
              )}
            </div>
          </div>
        ))}
      </div>

      <div className="border-t border-slate-200 bg-white p-4">
        <div>
          <Flex gap={8} align="center">
            <TextArea
              value={chatInput}
              onChange={(e) => setChatInput(e.target.value)}
              onPressEnter={(e) => {
                if (!e.shiftKey) {
                  e.preventDefault();
                  if (!isChatLoading && !isStreaming) {
                    handleChatSend();
                  }
                }
              }}
              placeholder={
                isEditMode
                  ? t("skillManagement.chat.editPlaceholder")
                  : t("skillManagement.chat.createPlaceholder")
              }
              disabled={isChatLoading || isStreaming}
              autoSize={{ minRows: 1, maxRows: 3 }}
              className="resize-none rounded-xl"
            />
            {isChatLoading || isStreaming ? (
              <Tooltip
                title={t("skillManagement.stopGenerating") || "Stop generating"}
              >
                <Button
                  type="primary"
                  danger
                  shape="circle"
                  icon={<Square size={14} />}
                  onClick={handleStop}
                  style={{ backgroundColor: "#ef4444" }}
                />
              </Tooltip>
            ) : (
              <Button
                type="primary"
                icon={<Send size={14} />}
                onClick={handleChatSend}
                disabled={!chatInput.trim()}
                style={{
                  width: 40,
                  height: 40,
                  flexShrink: 0,
                  borderRadius: 12,
                }}
              />
            )}
          </Flex>
          <div className="mt-3 text-xs text-slate-500">
            {t("skillManagement.chat.sendHint")}
          </div>
        </div>
      </div>
    </div>
  );

  const renderDraftPanel = () => (
    <SkillDraftPanel
      form={form}
      skillTabs={skillTabs}
      setSkillTabs={setSkillTabs}
      activeSkillTab={activeSkillTab}
      setActiveSkillTab={setActiveSkillTab}
      isStreaming={isStreaming}
      onNameChange={handleNameChange}
      textareaRefs={textareaRefs}
      shouldAutoScrollRef={shouldAutoScrollRef}
      onTextareaScroll={handleTextareaScroll}
      groupSelectOptions={groupSelectOptions}
    />
  );

  const tabItems = [
    {
      key: "interactive",
      label: (
        <Flex gap={6} align="center">
          <MessageCircle size={16} />
          <span>{t("skillManagement.tabs.interactive")}</span>
        </Flex>
      ),
    },
    {
      key: "upload",
      label: (
        <Flex gap={6} align="center">
          <Box size={16} />
          <span>{t("skillManagement.tabs.install")}</span>
        </Flex>
      ),
    },
  ];
  const visibleTabItems = isEditMode ? [tabItems[0]] : tabItems;

  const getConfirmButtonText = () => {
    if (isEditMode) {
      return t("skillManagement.mode.saveChanges");
    }
    if (activeTab === "interactive") {
      return t("skillManagement.mode.create");
    }
    return t("skillManagement.mode.create");
  };

  return (
    <Modal
      title={
        <div>
          <div className="text-xl font-semibold leading-7 text-slate-900 dark:text-slate-100">
            {isEditMode
              ? t("skillManagement.edit.title")
              : t("skillManagement.title")}
          </div>
          <div className="mt-1 text-sm font-normal text-slate-500 dark:text-slate-400">
            {isEditMode
              ? t("skillManagement.edit.subtitle", { name: editingSkillName })
              : t("skillManagement.create.subtitle")}
          </div>
        </div>
      }
      open={isOpen}
      onCancel={handleModalClose}
      centered
      width={1180}
      styles={{
        body: {
          display: "flex",
          flexDirection: "column",
          height: modalBodyFrame,
          maxHeight: modalBodyFrame,
          overflow: "hidden",
        },
      }}
      footer={[
        <Button key="cancel" onClick={handleModalClose}>
          {t("common.cancel")}
        </Button>,
        isEditMode || activeTab === "interactive" ? (
          <Button
            key="submit"
            type="primary"
            loading={isSubmitting}
            onClick={handleManualSubmit}
            disabled={
              isEditMode && (isLoadingEditFiles || Boolean(editFilesError))
            }
          >
            {getConfirmButtonText()}
          </Button>
        ) : (
          <Button
            key="submit"
            type="primary"
            loading={isSubmitting}
            onClick={handleUploadSubmit}
            disabled={
              !uploadFile ||
              !uploadExtractedSkillName.trim() ||
              !uploadIsCreateMode
            }
          >
            {getConfirmButtonText()}
          </Button>
        ),
      ]}
    >
      <Tabs
        activeKey={isEditMode ? "interactive" : activeTab}
        onChange={(key) => {
          if (!isEditMode) {
            setActiveTab(key);
          }
        }}
        items={visibleTabItems}
        className="skill-build-tabs shrink-0"
      />
      {isEditMode && !isEditContentReady ? (
        <div className="flex min-h-0 flex-1 items-center justify-center">
          <Spin spinning={isLoadingEditFiles}>
            {editFilesError ? (
              <p className="text-sm text-red-500">{editFilesError}</p>
            ) : (
              <div className="h-16 w-16" />
            )}
          </Spin>
        </div>
      ) : isEditMode || activeTab === "interactive" ? (
        <div className="grid min-h-0 flex-1 gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          {renderChatPanel()}
          {renderDraftPanel()}
        </div>
      ) : (
        <div className="min-h-0 flex-1">{renderUploadTab()}</div>
      )}
      <style jsx global>{`
        .skill-build-info-form .ant-form-item-label {
          padding-bottom: 3px !important;
        }

        .skill-build-info-form .ant-form-item-label > label {
          height: 20px;
          color: #475569;
          font-size: 12px;
          line-height: 20px;
        }

        .expanded-file-editor textarea {
          max-height: 70vh !important;
          overflow-y: auto !important;
          resize: none !important;
        }
      `}</style>
    </Modal>
  );
}
