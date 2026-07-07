"use client";

import { useState, useEffect, useMemo, useRef } from "react";
import { useTranslation } from "react-i18next";
import {
  Modal,
  Tabs,
  Form,
  Input,
  Button,
  AutoComplete,
  Select,
  message,
  Flex,
  Row,
  Col,
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
  FileText,
  Folder,
  Maximize2,
  Loader2,
  Plus,
  X,
  Pencil,
  Square,
} from "lucide-react";
import { extractSkillInfo, extractSkillInfoFromContent } from "@/lib/skillFileUtils";
import yaml from "js-yaml";
import {
  MAX_RECENT_SKILLS,
  THINKING_STEPS_ZH,
  type SkillFormData,
  type ChatMessage,
  type SkillFileContent,
} from "@/types/skill";
import {
  fetchSkillsList,
  submitSkillForm,
  submitSkillFromFile,
  findSkillByName,
  searchSkillsByName as searchSkillsByNameUtil,
  createSkillStream,
  stopSkillCreation,
  type SkillListItem,
  type SkillData,
} from "@/services/skillService";
import {
  fetchSkillFiles,
  fetchSkillFileContent,
  SkillFilesAccessDeniedError,
  type SkillFileNode,
} from "@/services/agentConfigService";
import type { MyEditableSkillItem } from "@/types/skillRepository";
import { MarkdownRenderer } from "@/components/common/markdownRenderer";
import log from "@/lib/logger";

const { TextArea } = Input;

interface SkillBuildModalProps {
  isOpen: boolean;
  onCancel: () => void;
  onSuccess: () => void;
  editingSkill?: MyEditableSkillItem | null;
}

export default function SkillBuildModal({
  isOpen,
  onCancel,
  onSuccess,
  editingSkill,
}: SkillBuildModalProps) {
  const { t } = useTranslation("common");
  const [form] = Form.useForm<SkillFormData>();
  const isEditMode = Boolean(editingSkill);
  const [activeTab, setActiveTab] = useState<string>("interactive");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [allSkills, setAllSkills] = useState<SkillListItem[]>([]);
  const [searchResults, setSearchResults] = useState<SkillListItem[]>([]);
  const [selectedSkillName, setSelectedSkillName] = useState<string>("");
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadExtractedSkillName, setUploadExtractedSkillName] = useState<string>("");
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
  const [expandedEditorPath, setExpandedEditorPath] = useState<string>("");
  const [expandedEditorContent, setExpandedEditorContent] = useState<string>("");
  const [isStreaming, setIsStreaming] = useState(false);

  // Tab management state
  const [editingTabKey, setEditingTabKey] = useState<string | null>(null);
  const [editingTabName, setEditingTabName] = useState<string>("");

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
    return textarea.scrollHeight - textarea.scrollTop - textarea.clientHeight < 20;
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
  const streamingTabsRef = useRef<SkillFileContent[]>([{ path: "SKILL.md", content: "" }]);

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

  const dedupeSkillTabs = (tabs: SkillFileContent[]) =>
    tabs.filter((tab, index, self) => self.findIndex((item) => item.path === tab.path) === index);

  // Name input dropdown control
  const [isNameDropdownOpen, setIsNameDropdownOpen] = useState(false);
  const [isTagsFocused, setIsTagsFocused] = useState(false);

  // Create/Update mode detection
  const [isCreateMode, setIsCreateMode] = useState(true);

  // Recent skills (sorted by update_time descending, take top 5)
  const recentSkills = useMemo(() => {
    return [...allSkills]
      .filter((s) => s.update_time)
      .sort((a, b) => {
        const timeA = new Date(a.update_time!).getTime();
        const timeB = new Date(b.update_time!).getTime();
        return timeB - timeA;
      })
      .slice(0, MAX_RECENT_SKILLS);
  }, [allSkills]);

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
    if (!isOpen) {
      // Abort any ongoing streaming request
      if (abortControllerRef.current) {
        abortControllerRef.current.abort("Modal closed");
        abortControllerRef.current = null;
      }
      // Reset task ID
      taskIdRef.current = "";
      form.resetFields();
      setActiveTab("interactive");
      setSelectedSkillName("");
      setUploadFile(null);
      setSearchResults([]);
      setChatMessages([]);
      setChatInput("");
      setInteractiveSkillName("");
      setIsNameDropdownOpen(false);
      setIsTagsFocused(false);
      setIsCreateMode(true);
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
      setEditingTabKey(null);
      setEditingTabName("");
    }
  }, [isOpen, form]);

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
    if (!summaryContent) return;
    setChatMessages((prev) => {
      if (!prev.some((m) => m.id === currentAssistantIdRef.current)) return prev;
      return prev.map((msg) =>
        msg.id === currentAssistantIdRef.current
          ? { ...msg, content: summaryContent }
          : msg
      );
    });
  }, [summaryContent]);

  // Detect create/update mode when skill name changes
  useEffect(() => {
    const nameValue = interactiveSkillName.trim();
    if (isEditMode) {
      setIsCreateMode(false);
      return;
    }
    if (nameValue) {
      const matchedSkill = findSkillByName(nameValue, allSkills);
      setIsCreateMode(!matchedSkill);
      if (matchedSkill) {
        setSelectedSkillName(matchedSkill.name);
        // Load all skill data including files
        loadSkillData(nameValue);
      }
    } else {
      setIsCreateMode(true);
      setSelectedSkillName("");
    }
  }, [interactiveSkillName, allSkills, form, isEditMode]);

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

  // Dropdown options based on input state
  const dropdownOptions = useMemo(() => {
    if (!interactiveSkillName || interactiveSkillName.trim() === "") {
      return recentSkills.map((skill) => ({
        value: skill.name,
        label: (
          <Flex justify="space-between" align="center">
            <span>{skill.name}</span>
            <span className="text-xs text-gray-400">{skill.source}</span>
          </Flex>
        ),
      }));
    }
    return searchResults.map((skill) => ({
      value: skill.name,
      label: (
        <Flex justify="space-between" align="center">
          <span>{skill.name}</span>
          <span className="text-xs text-gray-400">{skill.source}</span>
        </Flex>
      ),
    }));
  }, [interactiveSkillName, searchResults, recentSkills]);

  // Determine if dropdown should be open
  const shouldShowDropdown = isNameDropdownOpen && !isTagsFocused;

  const handleNameSearch = (value: string) => {
    setInteractiveSkillName(value);
    if (!value || value.trim() === "") {
      setSearchResults([]);
    } else {
      const results = searchSkillsByNameUtil(value, allSkills);
      setSearchResults(results);
    }
  };

  const handleNameSelect = (value: string) => {
    setSelectedSkillName(value);
    setInteractiveSkillName(value);
    setIsNameDropdownOpen(false);
  };

  // Load skill data when name is selected or typed
  const loadSkillData = async (skillName: string) => {
    const skill = allSkills.find((s) => s.name === skillName);
    if (!skill) return;

    const fieldsToSet = {
      name: skill.name,
      description: skill.description || "",
      source: skill.source || "custom",
      tags: skill.tags || [],
      content: skill.content || "",
    };
    form.setFieldsValue(fieldsToSet);

    await loadSkillFiles(skillName);
  };

  useEffect(() => {
    if (!isOpen || !editingSkill) return;
    const skillName = editingSkill.name?.trim() || "";
    setActiveTab("interactive");
    setSelectedSkillName(skillName);
    setInteractiveSkillName(skillName);
    setIsCreateMode(false);
    form.setFieldsValue({
      name: skillName,
      description: editingSkill.description || "",
      source: editingSkill.source || "custom",
      tags: editingSkill.tags || [],
    });
    if (skillName && allSkills.length > 0) {
      void loadSkillData(skillName);
    }
  }, [isOpen, editingSkill?.skill_id, allSkills.length]);

  const handleNameChange = (value: string) => {
    setInteractiveSkillName(value);
    if (!value || value.trim() === "") {
      setSelectedSkillName("");
      // Reset skillTabs when input is cleared
      setSkillTabs([{ path: "SKILL.md", content: "" }]);
      setActiveSkillTab("SKILL.md");
    }
  };

  const handleNameFocus = () => {
    setIsNameDropdownOpen(true);
  };

  const handleNameBlur = () => {
    setTimeout(() => {
      setIsNameDropdownOpen(false);
    }, 200);
  };

  // Cleanup when modal is closed
  const handleModalClose = () => {
    onCancel();
  };

  const handleManualSubmit = async () => {
    try {
      const values = await form.validateFields();
      setIsSubmitting(true);

      const skillTab = skillTabs.find(t => t.path === "SKILL.md");
      const content = skillTab?.content || "";

      const extraFiles = skillTabs
        .filter(t => t.path !== "SKILL.md")
        .map(t => ({
          path: t.path,
          content: t.content || "",
        }));

      await submitSkillForm(
        { ...values, content, files: extraFiles.length > 0 ? extraFiles : undefined } as SkillData,
        allSkills,
        onSuccess,
        onCancel,
        t
      );
    } catch (error) {
      log.error("Skill create/update error:", error);
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
        onCancel,
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

  // Load all files for a skill into skillTabs
  const loadSkillFiles = async (skillName: string) => {
    try {
      const files = await fetchSkillFiles(skillName);
      if (files.length === 0) {
        // Fallback: load SKILL.md content from the skill list item
        const skill = allSkills.find((s) => s.name === skillName);
        if (skill?.content) {
          setSkillTabs([{ path: "SKILL.md", content: skill.content }]);
        }
        return;
      }

      // Flatten file tree and get all file paths.
      // The root node's name IS the skill_name — skip the root itself and
      // start from its children so paths stay relative (e.g. "SKILL.md", not "skill_name/SKILL.md").
      const flattenFiles = (nodes: SkillFileNode[], prefix = ""): string[] => {
        const result: string[] = [];
        for (const node of nodes) {
          if (node.type === "directory" && node.name === skillName && prefix === "") {
            // Root directory — recurse into children without prepending the root name
            if (node.children) {
              result.push(...flattenFiles(node.children, ""));
            }
          } else {
            const fullPath = prefix ? `${prefix}/${node.name}` : node.name;
            if (node.type === "file") {
              result.push(fullPath);
            } else if (node.children) {
              result.push(...flattenFiles(node.children, fullPath));
            }
          }
        }
        return result;
      };

      const filePaths = flattenFiles(files);

      // Load content for each file
      const tabsContent: SkillFileContent[] = [];
      for (const filePath of filePaths) {
        const content = await fetchSkillFileContent(skillName, filePath);
        tabsContent.push({ path: filePath, content: content || "" });
      }

      // Sort so SKILL.md is always first
      tabsContent.sort((a, b) => {
        if (a.path === "SKILL.md") return -1;
        if (b.path === "SKILL.md") return 1;
        return a.path.localeCompare(b.path);
      });

      setSkillTabs(dedupeSkillTabs(tabsContent));
      setActiveSkillTab("SKILL.md");
    } catch (error) {
      log.error("Failed to load skill files:", error);
      if (error instanceof SkillFilesAccessDeniedError) {
        message.warning(error.message);
        return;
      }
      // Fallback to basic content
      const skill = allSkills.find((s) => s.name === skillName);
      if (skill?.content) {
        setSkillTabs([{ path: "SKILL.md", content: skill.content }]);
        setActiveSkillTab("SKILL.md");
      }
    }
  };

  // Parse frontmatter YAML and update form fields
  const parseAndUpdateFrontmatter = (frontmatterYaml: string) => {
    try {
      // Parse the frontmatter using js-yaml
      const parsed = yaml.load(frontmatterYaml) as Record<string, unknown> | null;
      if (parsed && typeof parsed === "object") {
        const name = typeof parsed.name === "string" ? parsed.name.trim() : "";
        const description = typeof parsed.description === "string" ? parsed.description.trim() : "";
        const tags = Array.isArray(parsed.tags) ? parsed.tags.filter((t): t is string => typeof t === "string") : [];

        if (name && !isEditMode) {
          form.setFieldsValue({ name });
          setInteractiveSkillName(name);
          const existingSkill = allSkills.find(
            (s) => s.name.toLowerCase() === name.toLowerCase()
          );
          setIsCreateMode(!existingSkill);
        }
        if (description) {
          form.setFieldsValue({ description });
        }
        if (tags.length > 0) {
          form.setFieldsValue({ tags });
        }
      }
    } catch (e) {
      log.warn("Failed to parse frontmatter:", e);
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
      formValues.name ? `当前技能名称：${formValues.name}` : "",
      formValues.description ? `当前技能描述：${formValues.description}` : "",
      formValues.tags?.length ? `当前标签：${formValues.tags.join(", ")}` : "",
      assembledContent ? `当前技能文件内容：\n${assembledContent}` : "",
    ].filter(Boolean).join("\n\n");

    const userMessage: ChatMessage = {
      id: Date.now().toString(),
      role: "user",
      content: currentInput,
      timestamp: new Date(),
    };

    setChatMessages((prev) => [...prev, userMessage]);
    setIsChatLoading(true);
    setIsThinkingVisible(true);
    setThinkingDescription(t("skillManagement.generatingSkill") || "生成技能内容中 ...");

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
      { id: assistantId, role: "assistant", content: "", timestamp: new Date() },
    ]);

    currentAssistantIdRef.current = assistantId;

    try {
      // Create AbortController for this request
      abortControllerRef.current = new AbortController();

      // On first turn, no existing_skill is sent → backend creates from scratch.
      // On subsequent turns (accumulatedDraft exists), existing_skill is passed
      // → backend follows the modify-workflow template and refines the draft.
      const userPrompt = formContext
        ? `用户需求：${currentInput}\n\n${formContext}`
        : `用户需求：${currentInput}`;

      await createSkillStream(
        {
          user_request: userPrompt,
          existing_skill: draft ? {
            name: draft.name || formValues.name || "",
            description: draft.description || formValues.description || "",
            tags: draft.tags?.length ? draft.tags : (formValues.tags || []),
            content: assembledContent,
          } : undefined,
          complexity: "complicated",
          language: "zh",
        },
        {
          onTaskId: (taskId) => {
            taskIdRef.current = taskId;
          },
          onThinkingUpdate: (step, desc) => {
            setThinkingDescription(desc || "生成技能内容中 ...");
          },
          onThinkingVisible: (visible) => {
            setIsThinkingVisible(visible);
          },
          onStepCount: (step) => {
            setThinkingDescription(THINKING_STEPS_ZH.find((s) => s.step === step)?.description || "生成技能内容中 ...");
          },
          onFrontmatter: (content) => {
            // Accumulate frontmatter content as it streams in
            // Parse frontmatter incrementally as it streams to update form fields
            frontmatterBufferRef.current += content;
            // Try to parse incrementally for form field updates
            try {
              const parsed = yaml.load(frontmatterBufferRef.current) as Record<string, unknown> | null;
              if (parsed && typeof parsed === "object") {
                const name = typeof parsed.name === "string" ? parsed.name.trim() : "";
                const description = typeof parsed.description === "string" ? parsed.description.trim() : "";
                const tags = Array.isArray(parsed.tags) ? parsed.tags.filter((t): t is string => typeof t === "string") : [];

                if (name && !isEditMode) {
                  form.setFieldsValue({ name });
                  setInteractiveSkillName(name);
                }
                if (description) {
                  form.setFieldsValue({ description });
                }
                if (tags.length > 0) {
                  form.setFieldsValue({ tags });
                }
              }
            } catch {
              // YAML not complete yet, will parse when skill body starts
            }
          },
          onSkillBody: (content) => {
            if (isStreamingCompleteRef.current) return;
            // Frontmatter is complete when skill_body starts - clear the buffer
            frontmatterBufferRef.current = "";
            // Only add body content to textarea (no frontmatter)
            updateTabContent("SKILL.md", content);
          },
          onFileContent: (path, content, isNewFile) => {
            if (isStreamingCompleteRef.current) return;

            if (isNewFile) {
              // New file detected, create a new tab
              setSkillTabs((prev) => {
                const newTabs = prev.find((t) => t.path === path) ? prev : [...prev, { path, content: "" }];
                streamingTabsRef.current = newTabs;
                shouldAutoScrollRef.current[path] = true;
                return newTabs;
              });
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
            const skillTab = result.skillTabs.find(t => t.path === "SKILL.md");
            const fullContent = skillTab?.content || "";

            if (fullContent || result.skillTabs.length > 0) {
              // Strip frontmatter from SKILL.md content for textarea display
              const skillInfo = extractSkillInfoFromContent(fullContent);
              const contentWithoutFrontmatter = skillInfo?.contentWithoutFrontmatter || "";

              // Use the current tabs from ref (avoids stale closure)
              const currentTabs = streamingTabsRef.current;

              // Build updated tabs: start with current tabs, update matching ones from backend
              const updatedTabs = currentTabs.map((tab) => {
                const backendTab = result.skillTabs.find((t) => t.path === tab.path);
                if (tab.path === "SKILL.md") {
                  return { ...tab, content: contentWithoutFrontmatter };
                }
                if (backendTab) {
                  return { ...tab, content: backendTab.content || tab.content };
                }
                return tab;
              });

              // Add any new tabs from backend that don't exist in current tabs
              const newTabsFromBackend = result.skillTabs.filter((t) => !currentTabs.find((tab) => tab.path === t.path));
              const finalTabs = [...updatedTabs, ...newTabsFromBackend];

              // Sort so SKILL.md is always first
              finalTabs.sort((a, b) => {
                if (a.path === "SKILL.md") return -1;
                if (b.path === "SKILL.md") return 1;
                return a.path.localeCompare(b.path);
              });

              setSkillTabs(finalTabs);

              // Update form fields from parsed skill info
              if (skillInfo && skillInfo.name && !isEditMode) {
                form.setFieldsValue({ name: skillInfo.name });
                setInteractiveSkillName(skillInfo.name);
                const existingSkill = allSkills.find(
                  (s) => s.name.toLowerCase() === skillInfo.name?.toLowerCase()
                );
                setIsCreateMode(!existingSkill);
              }
              if (skillInfo && skillInfo.description) {
                form.setFieldsValue({ description: skillInfo.description });
              }
              if (skillInfo && skillInfo.tags && skillInfo.tags.length > 0) {
                form.setFieldsValue({ tags: skillInfo.tags });
              }

              // Update accumulated draft with assembled content for next turn
              const assembledDraft = assembleSkillContent(updatedTabs);
              const newDraft = {
                name: skillInfo?.name || draft?.name || "",
                description: skillInfo?.description || draft?.description || "",
                tags: skillInfo?.tags?.length ? skillInfo.tags : (draft?.tags || []),
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
      chatContainerRef.current.scrollTop = chatContainerRef.current.scrollHeight;
    }
  }, [chatMessages]);

  const modalBodyFrame = "min(92vh, 760px)";
  const editingSkillName = editingSkill?.name?.trim() || interactiveSkillName.trim();

  const renderUploadTab = () => {
    const existingSkill = allSkills.find(
      (s) => s.name.trim().toLowerCase() === uploadExtractedSkillName.trim().toLowerCase()
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
          message.warning(t("skillManagement.message.nameOrDescriptionMissing"));
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
            安装
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
                placeholder={t("skillManagement.form.uploadSkillNamePlaceholder")}
                style={{ fontWeight: 500 }}
                status={!uploadExtractedSkillName && uploadFile ? "warning" : undefined}
              />
              {uploadExtractedSkillName && existingSkill ? (
                <span className="ml-1 text-xs text-amber-600">
                  {t("skillManagement.form.existingSkillHint")}
                </span>
              ) : null}
              {uploadExtractedSkillName && !existingSkill ? (
                <span className="text-xs text-green-600">
                  {t("skillManagement.form.newSkillHint")}
                </span>
              ) : null}
            </div>
          </Spin>

          <div
            className="flex flex-1 cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed border-slate-200 bg-slate-50/70 px-6 py-10 text-center transition-colors hover:border-blue-400 hover:bg-blue-50/50"
            onClick={() => {
              const input = document.getElementById("skill-upload-input") as HTMLInputElement;
              input?.click();
            }}
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
          </div>

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
                    const input = document.getElementById("skill-upload-input") as HTMLInputElement;
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
                    你好！我是 Skill 构建助手，当前正在编辑「{editingSkillName}」。
                  </p>
                  <p className="mt-3">
                    你可以告诉我需要优化或调整的地方，我会帮你更新对应的文件内容。
                  </p>
                </>
              ) : (
                <>
                  <p>
                    你好！我是 Skill 构建助手。请告诉我你想创建什么样的技能，我来帮你生成 Skill 的结构和代码。
                  </p>
                  <p className="mt-3">
                    例如：「创建一个能够分析 CSV 文件并生成数据报告的技能」
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
              placeholder={isEditMode ? "告诉我需要如何优化这个技能..." : "描述你想要的技能..."}
              disabled={isChatLoading || isStreaming}
              autoSize={{ minRows: 1, maxRows: 3 }}
              className="resize-none rounded-xl"
            />
            {isChatLoading || isStreaming ? (
              <Tooltip title={t("skillManagement.stopGenerating") || "Stop generating"}>
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
                style={{ width: 40, height: 40, flexShrink: 0, borderRadius: 12 }}
              />
            )}
          </Flex>
          <div className="mt-3 text-xs text-slate-500">
            按 Enter 发送，Shift+Enter 换行
          </div>
        </div>
      </div>
    </div>
  );

  const renderDraftPanel = () => (
    <div className="flex h-full min-h-0 flex-col gap-2 overflow-hidden">
      {(() => {
        const visibleSkillTabs = dedupeSkillTabs(skillTabs);
        const activeFile = visibleSkillTabs.find((tab) => tab.path === activeSkillTab) || visibleSkillTabs[0];

        return (
          <>
      <div className="shrink-0 rounded-2xl border border-slate-200 bg-white px-5 pb-2 pt-3 shadow-sm">
        <Form
          form={form}
          layout="vertical"
          className="skill-build-info-form"
          initialValues={{
            source: "custom",
            tags: [],
          }}
        >
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                name="name"
                label={t("skillManagement.form.name")}
                style={{ marginBottom: 10 }}
                rules={[
                  { required: true, message: t("skillManagement.form.nameRequired") },
                ]}
                help={
                  interactiveSkillName.trim() ? (
                    isCreateMode ? (
                      <span className="text-xs text-green-600">
                        {t("skillManagement.form.newSkillHint")}
                      </span>
                    ) : (
                      <span className="text-xs text-amber-600">
                        {t("skillManagement.form.existingSkillHint")}
                      </span>
                    )
                  ) : undefined
                }
                validateStatus={
                  interactiveSkillName.trim()
                    ? isCreateMode
                      ? "success"
                      : "warning"
                    : undefined
                }
              >
                <AutoComplete
                  open={shouldShowDropdown && dropdownOptions.length > 0}
                  options={dropdownOptions}
                  onSearch={handleNameSearch}
                  onSelect={handleNameSelect}
                  onChange={handleNameChange}
                  onFocus={handleNameFocus}
                  onBlur={handleNameBlur}
                  value={interactiveSkillName}
                  placeholder={t("skillManagement.form.namePlaceholder")}
                  allowClear
                />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                name="source"
                label={t("skillManagement.form.source")}
                style={{ marginBottom: 10 }}
              >
                <Select
                  options={[{ label: "自定义", value: "custom" }]}
                />
              </Form.Item>
            </Col>
          </Row>

          <Form.Item
            name="description"
            label={t("skillManagement.form.description")}
            style={{ marginBottom: 10 }}
            rules={[
              { required: true, message: t("skillManagement.form.descriptionRequired") },
            ]}
          >
            <TextArea
              rows={2}
              placeholder={t("skillManagement.form.descriptionPlaceholder")}
            />
          </Form.Item>

          <Form.Item
            name="tags"
            label={t("skillManagement.form.tags")}
            style={{ marginBottom: 8 }}
          >
            <Select
              mode="tags"
              suffixIcon={null}
              placeholder={t("skillManagement.form.tagsPlaceholder")}
              onFocus={() => setIsTagsFocused(true)}
              onBlur={() => setIsTagsFocused(false)}
              open={false}
              style={{ width: "100%" }}
              popupMatchSelectWidth={false}
            />
          </Form.Item>
        </Form>
      </div>

      <div className="flex min-h-0 flex-1 flex-col">
        <div className="flex min-h-0 flex-1 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
          <div className="flex w-[28%] min-w-[140px] shrink-0 flex-col border-r border-slate-200 bg-slate-50/60">
            <div className="flex h-11 items-center justify-between border-b border-slate-200 px-3">
              <span className="text-sm font-medium text-slate-700">文件</span>
              {!isStreaming ? (
                <Button
                  type="text"
                  size="small"
                  icon={<Plus size={14} />}
                  onClick={() => {
                    const newPath = `file_${Date.now()}.md`;
                    setSkillTabs((prev) => [...prev, { path: newPath, content: "" }]);
                    setActiveSkillTab(newPath);
                    shouldAutoScrollRef.current[newPath] = true;
                  }}
                />
              ) : null}
            </div>
            <div className="custom-scrollbar min-h-0 flex-1 overflow-y-auto py-2">
              {visibleSkillTabs.filter((tab) => !tab.path.includes("/")).map((tab) => (
                <div
                  key={tab.path}
                  className={`group/file mx-2 flex h-9 cursor-pointer items-center gap-2 rounded-lg px-2 text-xs transition-colors ${
                    activeSkillTab === tab.path
                      ? "bg-blue-50 text-blue-700"
                      : "text-slate-600 hover:bg-slate-100"
                  }`}
                  onClick={() => setActiveSkillTab(tab.path)}
                >
                  <FileText size={15} className="shrink-0" />
                  {editingTabKey === tab.path ? (
                    <input
                      className="min-w-0 flex-1 rounded border border-blue-400 px-1 py-0.5 text-xs"
                      value={editingTabName}
                      autoFocus
                      onChange={(e) => setEditingTabName(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          e.preventDefault();
                          e.stopPropagation();
                          setSkillTabs((prev) =>
                            prev.map((t) =>
                              t.path === editingTabKey ? { ...t, path: editingTabName } : t
                            )
                          );
                          if (activeSkillTab === editingTabKey) {
                            setActiveSkillTab(editingTabName);
                          }
                          setEditingTabKey(null);
                          setEditingTabName("");
                        } else if (e.key === "Escape") {
                          e.stopPropagation();
                          setEditingTabKey(null);
                          setEditingTabName("");
                        }
                      }}
                      onBlur={() => {
                        setSkillTabs((prev) =>
                          prev.map((t) =>
                            t.path === editingTabKey ? { ...t, path: editingTabName } : t
                          )
                        );
                        if (activeSkillTab === editingTabKey) {
                          setActiveSkillTab(editingTabName);
                        }
                        setEditingTabKey(null);
                        setEditingTabName("");
                      }}
                      onClick={(e) => e.stopPropagation()}
                    />
                  ) : (
                    <span className="min-w-0 flex-1 truncate">{tab.path}</span>
                  )}
                  {!isStreaming && tab.path !== "SKILL.md" ? (
                    <div className="hidden items-center gap-1 group-hover/file:flex">
                      <button
                        className="rounded p-0.5 hover:bg-slate-200"
                        onClick={(e) => {
                          e.stopPropagation();
                          setEditingTabKey(tab.path);
                          setEditingTabName(tab.path);
                        }}
                        title="Rename"
                      >
                        <Pencil size={12} />
                      </button>
                      <button
                        className="rounded p-0.5 hover:bg-slate-200"
                        onClick={(e) => {
                          e.stopPropagation();
                          const newTabs = skillTabs.filter((t) => t.path !== tab.path);
                          setSkillTabs(newTabs);
                          if (activeSkillTab === tab.path) {
                            setActiveSkillTab(newTabs[0]?.path || "");
                          }
                        }}
                        title="Delete"
                      >
                        <X size={12} />
                      </button>
                    </div>
                  ) : null}
                </div>
              ))}
              {Array.from(new Set(
                visibleSkillTabs
                  .filter((tab) => tab.path.includes("/"))
                  .map((tab) => tab.path.split("/")[0])
              )).map((folderName) => (
                <div key={folderName}>
                  <div className="mx-2 mt-1 flex h-8 items-center gap-2 rounded-lg px-2 text-xs font-normal text-slate-500">
                    <Folder size={15} className="shrink-0 text-amber-500" />
                    <span className="min-w-0 flex-1 truncate">{folderName}</span>
                  </div>
                  {visibleSkillTabs
                    .filter((tab) => tab.path.startsWith(`${folderName}/`))
                    .map((tab) => (
                      <div
                        key={tab.path}
                        className={`group/file mx-2 flex h-9 cursor-pointer items-center gap-2 rounded-lg pl-7 pr-2 text-xs transition-colors ${
                          activeSkillTab === tab.path
                            ? "bg-blue-50 text-blue-700"
                            : "text-slate-600 hover:bg-slate-100"
                        }`}
                        onClick={() => setActiveSkillTab(tab.path)}
                      >
                        <FileText size={15} className="shrink-0" />
                        {editingTabKey === tab.path ? (
                          <input
                            className="min-w-0 flex-1 rounded border border-blue-400 px-1 py-0.5 text-xs"
                            value={editingTabName}
                            autoFocus
                            onChange={(e) => setEditingTabName(e.target.value)}
                            onKeyDown={(e) => {
                              if (e.key === "Enter") {
                                e.preventDefault();
                                e.stopPropagation();
                                setSkillTabs((prev) =>
                                  prev.map((t) =>
                                    t.path === editingTabKey ? { ...t, path: editingTabName } : t
                                  )
                                );
                                if (activeSkillTab === editingTabKey) {
                                  setActiveSkillTab(editingTabName);
                                }
                                setEditingTabKey(null);
                                setEditingTabName("");
                              } else if (e.key === "Escape") {
                                e.stopPropagation();
                                setEditingTabKey(null);
                                setEditingTabName("");
                              }
                            }}
                            onBlur={() => {
                              setSkillTabs((prev) =>
                                prev.map((t) =>
                                  t.path === editingTabKey ? { ...t, path: editingTabName } : t
                                )
                              );
                              if (activeSkillTab === editingTabKey) {
                                setActiveSkillTab(editingTabName);
                              }
                              setEditingTabKey(null);
                              setEditingTabName("");
                            }}
                            onClick={(e) => e.stopPropagation()}
                          />
                        ) : (
                          <span className="min-w-0 flex-1 truncate">
                            {tab.path.slice(folderName.length + 1)}
                          </span>
                        )}
                        {!isStreaming && tab.path !== "SKILL.md" ? (
                          <div className="hidden items-center gap-1 group-hover/file:flex">
                            <button
                              className="rounded p-0.5 hover:bg-slate-200"
                              onClick={(e) => {
                                e.stopPropagation();
                                setEditingTabKey(tab.path);
                                setEditingTabName(tab.path);
                              }}
                              title="Rename"
                            >
                              <Pencil size={12} />
                            </button>
                            <button
                              className="rounded p-0.5 hover:bg-slate-200"
                              onClick={(e) => {
                                e.stopPropagation();
                                const newTabs = skillTabs.filter((t) => t.path !== tab.path);
                                setSkillTabs(newTabs);
                                if (activeSkillTab === tab.path) {
                                  setActiveSkillTab(newTabs[0]?.path || "");
                                }
                              }}
                              title="Delete"
                            >
                              <X size={12} />
                            </button>
                          </div>
                        ) : null}
                      </div>
                    ))}
                </div>
              ))}
            </div>
          </div>
          {(() => {
            if (!activeFile) {
              return null;
            }
            return (
              <div className="flex min-w-0 flex-1 flex-col">
                <div className="flex h-11 shrink-0 items-center justify-between border-b border-slate-200 px-4 text-sm font-medium text-slate-700">
                  <span className="min-w-0 flex-1 truncate">{activeFile.path}</span>
                  <Tooltip title="放大查看">
                    <Button
                      type="text"
                      size="small"
                      icon={<Maximize2 size={15} />}
                      onClick={() => {
                        setExpandedEditorPath(activeFile.path);
                        setExpandedEditorContent(activeFile.content);
                      }}
                    />
                  </Tooltip>
                </div>
                <TextArea
                  className="min-h-0 flex-1 rounded-none border-0 font-mono text-xs shadow-none focus:border-0 focus:shadow-none"
                  placeholder={isStreaming ? "" : `${activeFile.path} content...`}
                  value={activeFile.content}
                  disabled={isStreaming}
                  style={{ resize: "none" }}
                  ref={(el) => {
                    textareaRefs.current[activeFile.path] = el;
                    if (el && shouldAutoScrollRef.current[activeFile.path] === undefined) {
                      shouldAutoScrollRef.current[activeFile.path] = true;
                    }
                  }}
                  onScroll={() => handleTextareaScroll(activeFile.path)}
                  onChange={(e) => {
                    if (isStreaming) return;
                    setSkillTabs((prev) =>
                      prev.map((t) =>
                        t.path === activeFile.path ? { ...t, content: e.target.value } : t
                      )
                    );
                  }}
                />
              </div>
            );
          })()}
        </div>
      </div>
          </>
        );
      })()}
    </div>
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
          <span>安装</span>
        </Flex>
      ),
    },
  ];
  const visibleTabItems = isEditMode ? [tabItems[0]] : tabItems;

  const getConfirmButtonText = () => {
    if (isEditMode) {
      return "保存更改";
    }
    if (activeTab === "interactive") {
      return isCreateMode
        ? t("skillManagement.mode.create")
        : t("skillManagement.mode.update");
    }
    return uploadIsCreateMode
      ? t("skillManagement.mode.create")
      : t("skillManagement.mode.update");
  };

  return (
    <Modal
      title={
        <div>
          <div className="text-xl font-semibold leading-7 text-slate-900 dark:text-slate-100">
            {isEditMode ? "编辑技能" : t("skillManagement.title")}
          </div>
          <div className="mt-1 text-sm font-normal text-slate-500 dark:text-slate-400">
            {isEditMode ? `正在编辑：${editingSkillName}` : "创建、编辑并发布你的 Skill。"}
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
        <Button
          key="cancel"
          onClick={handleModalClose}
        >
          {t("common.cancel")}
        </Button>,
        isEditMode || activeTab === "interactive" ? (
          <Button
            key="submit"
            type="primary"
            loading={isSubmitting}
            onClick={handleManualSubmit}
          >
            {getConfirmButtonText()}
          </Button>
        ) : (
          <Button
            key="submit"
            type="primary"
            loading={isSubmitting}
            onClick={handleUploadSubmit}
            disabled={!uploadFile || !uploadExtractedSkillName.trim()}
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
      {isEditMode || activeTab === "interactive" ? (
        <div className="grid min-h-0 flex-1 gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          {renderChatPanel()}
          {renderDraftPanel()}
        </div>
      ) : (
        <div className="min-h-0 flex-1">
          {renderUploadTab()}
        </div>
      )}
      <Modal
        title={expandedEditorPath}
        open={Boolean(expandedEditorPath)}
        onCancel={() => {
          setExpandedEditorPath("");
          setExpandedEditorContent("");
        }}
        centered
        width={640}
        styles={{
          body: {
            padding: 0,
          },
        }}
        footer={[
          <Button
            key="cancel-expanded-editor"
            onClick={() => {
              setExpandedEditorPath("");
              setExpandedEditorContent("");
            }}
          >
            取消
          </Button>,
          <Button
            key="save-expanded-editor"
            type="primary"
            disabled={isStreaming}
            onClick={() => {
              setSkillTabs((prev) =>
                prev.map((tab) =>
                  tab.path === expandedEditorPath
                    ? { ...tab, content: expandedEditorContent }
                    : tab
                )
              );
              setExpandedEditorPath("");
              setExpandedEditorContent("");
            }}
          >
            保存
          </Button>,
        ]}
      >
        <TextArea
          value={expandedEditorContent}
          disabled={isStreaming}
          onChange={(e) => setExpandedEditorContent(e.target.value)}
          autoSize={{ minRows: 10, maxRows: 28 }}
          className="expanded-file-editor rounded-none border-0 font-mono text-sm shadow-none focus:border-0 focus:shadow-none"
          style={{ resize: "none" }}
        />
      </Modal>
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
