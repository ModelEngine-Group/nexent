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
  MessagesSquare,
  HardDriveUpload,
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
  clearChatAndTempFile,
  stopSkillCreation,
  type SkillListItem,
  type SkillData,
} from "@/services/skillService";
import {
  fetchSkillFiles,
  fetchSkillFileContent,
  type SkillFileNode,
} from "@/services/agentConfigService";
import { MarkdownRenderer } from "@/components/ui/markdownRenderer";
import log from "@/lib/logger";

const { TextArea } = Input;

interface SkillBuildModalProps {
  isOpen: boolean;
  onCancel: () => void;
  onSuccess: () => void;
}

export default function SkillBuildModal({
  isOpen,
  onCancel,
  onSuccess,
}: SkillBuildModalProps) {
  const { t } = useTranslation("common");
  const [form] = Form.useForm<SkillFormData>();
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

  // Whether the user is in multi-turn refinement mode (has already received a draft).
  // Used to switch the placeholder from "创建" to "继续修改" and to pass existing_skill.
  const [isMultiTurn, setIsMultiTurn] = useState(false);

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
      setIsMultiTurn(false);
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
  }, [interactiveSkillName, allSkills, form]);

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
      source: skill.source || "自定义",
      tags: skill.tags || [],
      content: skill.content || "",
    };
    form.setFieldsValue(fieldsToSet);

    await loadSkillFiles(skillName);
  };

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

      setSkillTabs(tabsContent);
      setActiveSkillTab("SKILL.md");
    } catch (error) {
      log.error("Failed to load skill files:", error);
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

        if (name) {
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

                if (name) {
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
              if (skillInfo && skillInfo.name) {
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
              setIsMultiTurn(true);

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

  // Handle chat clear - reset all form fields
  const handleChatClear = async () => {
    await clearChatAndTempFile();
    setChatMessages([]);
    form.resetFields(["name", "description", "source", "tags", "content"]);
    setInteractiveSkillName("");
    setSkillTabs([{ path: "SKILL.md", content: "" }]);
    streamingTabsRef.current = [{ path: "SKILL.md", content: "" }];
    setActiveSkillTab("SKILL.md");
    setSummaryContent("");
    setAccumulatedDraft(null);
    setIsMultiTurn(false);
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

  const renderInteractiveTab = () => {
    return (
      <div className="flex gap-4" style={{ height: 480 }}>
        {/* Left side: Chat dialog */}
        <div
          className="flex flex-col border border-gray-200 rounded-lg overflow-hidden"
          style={{ width: "40%", minWidth: 280 }}
        >
          {/* Chat header */}
          <div className="bg-gray-50 px-3 py-2 border-b border-gray-200 flex items-center justify-between">
            <span className="text-sm font-medium text-gray-700">
              {t("skillManagement.tabs.interactive")}
            </span>
            {chatMessages.length > 0 && (
              <button
                onClick={handleChatClear}
                className="text-gray-400 hover:text-gray-600 transition-colors"
                title={t("agent.debug.clear")}
              >
                <Trash2 size={14} />
              </button>
            )}
          </div>

          {/* Chat messages area */}
          <div
            ref={chatContainerRef}
            className="flex-1 overflow-y-auto p-3 space-y-3 custom-scrollbar"
          >
            {chatMessages.length === 0 && (
              <div className="text-center text-gray-400 text-sm mt-8">
                {t("skillManagement.form.chatPlaceholder")}
              </div>
            )}
            {chatMessages.map((msg) => (
              <div
                key={msg.id}
                className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
              >
                <div
                  className={`max-w-[90%] px-3 py-2 rounded-lg text-sm ${
                    msg.role === "user"
                      ? "bg-blue-500 text-white"
                      : "bg-gray-100 text-gray-800"
                  }`}
                >
                  {msg.role === "assistant" && msg.id === currentAssistantIdRef.current && isThinkingVisible ? (
                    <div className="min-w-[200px] flex flex-col items-center">
                      <Loader2 size={24} className="animate-spin text-blue-500" />
                      {thinkingDescription && (
                        <span className="text-xs text-gray-500 mt-2">
                          {thinkingDescription}
                        </span>
                      )}
                    </div>
                  ) : msg.role === "assistant" ? (
                    <div className="markdown-content">
                      <MarkdownRenderer
                        content={msg.content}
                        className="text-sm"
                      />
                    </div>
                  ) : (
                    <div className="whitespace-pre-wrap">{msg.content}</div>
                  )}
                </div>
              </div>
            ))}
          </div>

          {/* Chat input area */}
          <div className="p-3 border-t border-gray-200">
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
                placeholder={isMultiTurn
                  ? t("skillManagement.form.multiTurnPlaceholder")
                  : t("skillManagement.form.chatPlaceholder")
                }
                disabled={isChatLoading || isStreaming}
                autoSize={{ minRows: 1, maxRows: 3 }}
                className="resize-none"
              />
              {isChatLoading || isStreaming ? (
                <Tooltip title={t("skillManagement.stopGenerating") || "停止生成"}>
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
                  style={{ width: 30, height: 30, flexShrink: 0 }}
                />
              )}
            </Flex>
          </div>
        </div>

        {/* Right side: Form */}
        <div
          style={{ width: "60%" }}
          className="flex flex-col border border-gray-200 rounded-lg overflow-hidden"
        >
          {/* Form header area */}
          <div className="px-3 pt-3 pb-0 flex-shrink-0">
            <Form
              form={form}
              layout="vertical"
              initialValues={{
                source: "自定义",
                tags: [],
              }}
            >
              <Form.Item
                name="name"
                label={t("skillManagement.form.name")}
                rules={[
                  { required: true, message: t("skillManagement.form.nameRequired") },
                ]}
                help={interactiveSkillName.trim() ? (
                  isCreateMode ? (
                    <span className="text-xs text-green-600">
                      {t("skillManagement.form.newSkillHint")}
                    </span>
                  ) : (
                    <span className="text-xs text-amber-600">
                      {t("skillManagement.form.existingSkillHint")}
                    </span>
                  )
                ) : undefined}
                validateStatus={interactiveSkillName.trim() ? (isCreateMode ? "success" : "warning") : undefined}
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

              <Form.Item
                name="description"
                label={t("skillManagement.form.description")}
                rules={[
                  { required: true, message: t("skillManagement.form.descriptionRequired") },
                ]}
              >
                <TextArea
                  rows={2}
                  placeholder={t("skillManagement.form.descriptionPlaceholder")}
                />
              </Form.Item>

              <Row gutter={12}>
                <Col span={8}>
                  <Form.Item
                    name="source"
                    label={t("skillManagement.form.source")}
                  >
                    <Input value="自定义" />
                  </Form.Item>
                </Col>
                <Col span={16}>
                  <Form.Item
                    name="tags"
                    label={t("skillManagement.form.tags")}
                  >
                    <div className="overflow-x-auto" style={{ maxWidth: "100%" }}>
                      <Select
                        mode="tags"
                        suffixIcon={null}
                        placeholder={t("skillManagement.form.tagsPlaceholder")}
                        onFocus={() => setIsTagsFocused(true)}
                        onBlur={() => setIsTagsFocused(false)}
                        open={false}
                        style={{ width: "100%", minWidth: 200 }}
                        popupMatchSelectWidth={false}
                      />
                    </div>
                  </Form.Item>
                </Col>
              </Row>
            </Form>
          </div>

          {/* Tabs area */}
          <div className="flex-1 min-h-0 px-3 pb-3 flex flex-col">
            <Tabs
              activeKey={activeSkillTab}
              onChange={(key) => setActiveSkillTab(key)}
              type="card"
              size="small"
              className="flex-1 flex flex-col"
              tabBarStyle={{ marginBottom: 0, flexShrink: 0 }}
              tabBarExtraContent={{
                right: (
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
                    className="add-tab-btn"
                  />
                ),
              }}
              items={skillTabs.map((tab) => ({
                key: tab.path,
                label: (
                  <div className="flex items-center group/tab">
                    {editingTabKey === tab.path ? (
                      <input
                        className="text-xs px-1 py-0.5 border border-blue-400 rounded w-24"
                        value={editingTabName}
                        autoFocus
                        onChange={(e) => setEditingTabName(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") {
                            e.preventDefault();
                            e.stopPropagation();
                            setSkillTabs((prev) =>
                              prev.map((t) => (t.path === editingTabKey ? { ...t, path: editingTabName } : t))
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
                            prev.map((t) => (t.path === editingTabKey ? { ...t, path: editingTabName } : t))
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
                      <span className={activeSkillTab === tab.path ? "font-bold" : ""}>
                        {tab.path}
                      </span>
                    )}
                    {!isStreaming && (
                      <div className="flex items-center ml-1 w-0 group-hover/tab:w-auto overflow-hidden transition-all duration-200">
                        {tab.path !== "SKILL.md" && (
                          <button
                            className="p-0.5 hover:bg-gray-200 rounded flex-shrink-0"
                            onMouseDown={(e) => {
                              e.preventDefault();
                              e.stopPropagation();
                              setTimeout(() => {
                                setEditingTabKey(tab.path);
                                setEditingTabName(tab.path);
                              }, 0);
                            }}
                            title="Rename"
                          >
                            <Pencil size={12} />
                          </button>
                        )}
                        {tab.path !== "SKILL.md" && (
                          <button
                            className="p-0.5 hover:bg-gray-200 rounded flex-shrink-0"
                            onMouseDown={(e) => {
                              e.preventDefault();
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
                        )}
                      </div>
                    )}
                  </div>
                ),
                children: (
                  <TextArea
                    rows={6}
                    placeholder={isStreaming ? "" : `${tab.path} content...`}
                    value={tab.content}
                    disabled={isStreaming}
                    ref={(el) => {
                      textareaRefs.current[tab.path] = el;
                      if (el && shouldAutoScrollRef.current[tab.path] === undefined) {
                        shouldAutoScrollRef.current[tab.path] = true;
                      }
                    }}
                    onScroll={() => handleTextareaScroll(tab.path)}
                    onChange={(e) => {
                      if (isStreaming) return;
                      setSkillTabs((prev) =>
                        prev.map((t) =>
                          t.path === tab.path ? { ...t, content: e.target.value } : t
                        )
                      );
                    }}
                  />
                ),
              }))}
            />
          </div>
        </div>
      </div>
    );
  };

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
      <div className="p-3 bg-gray-50 border-t border-gray-200" style={{ height: 480 }}>
        <div className="h-full flex transition-all duration-300 ease-in-out">
          {/* Left: Name display + Upload Dragger */}
          <div
            className={`transition-all duration-300 ease-in-out ${
              uploadFile ? "w-[40%] pr-2" : "w-full"
            }`}
          >
            <div className="h-full flex flex-col gap-3">
              {/* Name field */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  {t("skillManagement.form.name")}
                </label>
                <Spin spinning={uploadExtractingName}>
                  <Input
                    value={uploadExtractedSkillName}
                    readOnly
                    placeholder={t("skillManagement.form.uploadSkillNamePlaceholder")}
                    style={{ fontWeight: 500 }}
                    status={!uploadExtractedSkillName && uploadFile ? "warning" : undefined}
                  />
                </Spin>
                {uploadExtractedSkillName && existingSkill && (
                  <span className="ml-1 text-xs text-amber-600">
                    {t("skillManagement.form.existingSkillHint")}
                  </span>
                )}
                {uploadExtractedSkillName && !existingSkill && (
                  <span className="text-xs text-green-600">
                    {t("skillManagement.form.newSkillHint")}
                  </span>
                )}
              </div>

              {/* Upload area */}
              <div className="flex-1 min-h-0">
                <div className="h-full" onClick={() => {
                  const input = document.getElementById("skill-upload-input") as HTMLInputElement;
                  input?.click();
                }}>
                  <div
                    className="!h-full flex flex-col justify-center !bg-transparent !border-gray-200 border-2 border-dashed rounded-lg cursor-pointer hover:border-blue-400 hover:bg-blue-50/30 transition-colors"
                    onDragOver={(e) => { e.preventDefault(); e.stopPropagation(); }}
                    onDragEnter={(e) => { e.preventDefault(); e.stopPropagation(); }}
                    onDragLeave={(e) => { e.preventDefault(); e.stopPropagation(); }}
                    onDrop={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      handleFileSelection(e.dataTransfer.files);
                    }}
                  >
                    <div className="flex flex-col items-center justify-center h-full py-6 px-4">
                      <p className="!mb-3">
                        <UploadIcon className="text-blue-600" size={48} />
                      </p>
                      <p className="ant-upload-text !mb-2 text-base text-gray-700">
                        {t("skillManagement.form.uploadDragText")}
                      </p>
                      <p className="ant-upload-hint text-gray-500">
                        {t("skillManagement.form.uploadHint")}
                      </p>
                    </div>
                  </div>
                </div>
                <input
                  id="skill-upload-input"
                  type="file"
                  accept=".md,.zip"
                  className="hidden"
                  onChange={(e) => handleFileSelection(e.target.files)}
                />
              </div>
            </div>
          </div>

          {/* Right: File list panel */}
          <div
            className={`rounded-lg transition-all duration-300 ease-in-out overflow-hidden ${
              uploadFile ? "w-[60%] opacity-100 pl-2" : "w-0 opacity-0"
            }`}
          >
            {uploadFile && (
              <div className="h-full">
                <div className="h-full border border-gray-200 rounded-lg bg-white">
                  <div className="flex items-center justify-between p-3 border-b border-gray-100 bg-gray-50">
                    <h4 className="text-sm font-medium text-gray-700 m-0">
                      {t("knowledgeBase.upload.completed")}
                    </h4>
                    <span className="text-xs text-gray-500">1</span>
                  </div>
                  <div className="overflow-auto h-[calc(100%-41px)]">
                    <div className="border-b border-gray-100 last:border-b-0">
                      <div className="flex items-center justify-between py-2 px-3 hover:bg-gray-50 transition-colors">
                        <div className="flex-1 min-w-0">
                          <div className="text-xs font-medium text-gray-700 truncate">
                            {uploadFile.name}
                          </div>
                        </div>
                        <Button
                          type="text"
                          danger
                          size="small"
                          className="ml-2 flex-shrink-0"
                          onClick={() => {
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
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    );
  };

  const tabItems = [
    {
      key: "interactive",
      label: (
        <Flex gap={6} align="center">
          <MessagesSquare size={14} />
          <span>{t("skillManagement.tabs.interactive")}</span>
        </Flex>
      ),
      children: renderInteractiveTab(),
    },
    {
      key: "upload",
      label: (
        <Flex gap={6} align="center">
          <HardDriveUpload size={14} />
          <span>{t("skillManagement.tabs.upload")}</span>
        </Flex>
      ),
      children: renderUploadTab(),
    },
  ];

  const getConfirmButtonText = () => {
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
      title={t("skillManagement.title")}
      open={isOpen}
      onCancel={handleModalClose}
      width={900}
      footer={[
        <Button
          key="cancel"
          onClick={handleModalClose}
        >
          {t("common.cancel")}
        </Button>,
        activeTab === "interactive" ? (
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
        activeKey={activeTab}
        onChange={setActiveTab}
        items={tabItems}
        className="skill-build-tabs"
      />
    </Modal>
  );
}
