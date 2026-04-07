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
} from "antd";
import {
  Upload as UploadIcon,
  Send,
  Trash2,
  MessagesSquare,
  HardDriveUpload,
  Loader2,
} from "lucide-react";
import { extractSkillInfo, extractSkillInfoFromContent } from "@/lib/skillFileUtils";
import {
  MAX_RECENT_SKILLS,
  THINKING_STEPS_ZH,
  type SkillFormData,
  type ChatMessage,
} from "@/types/skill";
import {
  fetchSkillsList,
  submitSkillForm,
  submitSkillFromFile,
  findSkillByName,
  searchSkillsByName as searchSkillsByNameUtil,
  createSimpleSkillStream,
  clearChatAndTempFile,
  type SkillListItem,
} from "@/services/skillService";
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
  const [thinkingStep, setThinkingStep] = useState<number>(0);
  const [thinkingDescription, setThinkingDescription] = useState<string>("");
  const [isThinkingVisible, setIsThinkingVisible] = useState(false);
  const [interactiveSkillName, setInteractiveSkillName] = useState<string>("");
  const chatContainerRef = useRef<HTMLDivElement>(null);
  const contentTextAreaId = useRef<string>("skill-content-textarea-" + Date.now());

  // Content input streaming state
  const [formStreamingContent, setFormStreamingContent] = useState<string>("");
  const [isContentStreaming, setIsContentStreaming] = useState(false);
  const [thinkingStreamingContent, setThinkingStreamingContent] = useState<string>("");
  const [summaryStreamingContent, setSummaryStreamingContent] = useState<string>("");
  const [isSummaryVisible, setIsSummaryVisible] = useState(false);

  // Track if component is mounted to prevent state updates after unmount
  const isMountedRef = useRef(true);
  const currentAssistantIdRef = useRef<string>("");
  // Track if streaming is complete to prevent late onFormContent callbacks from overwriting cleaned content
  const isStreamingCompleteRef = useRef(false);

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
        if (!cancelled) setAllSkills(list);
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
      setThinkingStep(0);
      setThinkingDescription("");
      setIsThinkingVisible(false);
      setFormStreamingContent("");
      setThinkingStreamingContent("");
      setSummaryStreamingContent("");
      setIsSummaryVisible(false);
      setIsContentStreaming(false);
      currentAssistantIdRef.current = "";
    }
  }, [isOpen, form]);

  // Track component mount status for async callback safety
  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  // Sync streaming content to the current assistant chat message for real-time display.
  // Show thinking content while thinking is visible, then switch to summary.
  useEffect(() => {
    if (!currentAssistantIdRef.current) return;
    const displayContent = isSummaryVisible ? summaryStreamingContent : thinkingStreamingContent;
    if (!displayContent) return;
    setChatMessages((prev) =>
      prev.map((msg) =>
        msg.id === currentAssistantIdRef.current
          ? { ...msg, content: displayContent }
          : msg
      )
    );
  }, [thinkingStreamingContent, summaryStreamingContent, isSummaryVisible]);

  // Sync formStreamingContent to the form content field for real-time display
  useEffect(() => {
    if (!formStreamingContent) return;
    form.setFieldValue("content", formStreamingContent);
  }, [formStreamingContent, form]);

  // Detect create/update mode when skill name changes
  useEffect(() => {
    const nameValue = interactiveSkillName.trim();
    if (nameValue) {
      const matchedSkill = findSkillByName(nameValue, allSkills);
      setIsCreateMode(!matchedSkill);
      if (matchedSkill) {
        setSelectedSkillName(matchedSkill.name);
        form.setFieldsValue({
          description: matchedSkill.description || "",
          source: matchedSkill.source || "自定义",
          content: matchedSkill.content || "",
        });
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
    const skill = allSkills.find((s) => s.name === value);
    if (skill) {
      form.setFieldsValue({
        name: skill.name,
        description: skill.description || "",
        source: skill.source || "自定义",
        content: skill.content || "",
      });
    }
  };

  const handleNameChange = (value: string) => {
    setInteractiveSkillName(value);
    if (!value || value.trim() === "") {
      setSelectedSkillName("");
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
      await submitSkillForm(
        values,
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

  // Handle chat send for interactive creation
  const handleChatSend = async () => {
    if (!chatInput.trim() || isChatLoading) return;

    const currentInput = chatInput.trim();
    setChatInput("");

    // Read current form fields to provide context to the model
    const formValues = form.getFieldsValue();
    const formContext = [
      formValues.name ? `当前技能名称：${formValues.name}` : "",
      formValues.description ? `当前技能描述：${formValues.description}` : "",
      formValues.tags?.length ? `当前标签：${formValues.tags.join(", ")}` : "",
      formValues.content ? `当前内容：\n${formValues.content}` : "",
    ].filter(Boolean).join("\n\n");

    const userMessage: ChatMessage = {
      id: Date.now().toString(),
      role: "user",
      content: currentInput,
      timestamp: new Date(),
    };

    setChatMessages((prev) => [...prev, userMessage]);
    setIsChatLoading(true);
    setThinkingStep(1);
    setThinkingDescription(THINKING_STEPS_ZH.find((s) => s.step === 1)?.description || "生成技能内容中 ...");
    setIsThinkingVisible(true);

    // Clear content input before streaming
    form.setFieldValue("content", "");
    setFormStreamingContent("");
    setThinkingStreamingContent("");
    setSummaryStreamingContent("");
    setIsSummaryVisible(false);
    setIsContentStreaming(true);
    // Reset streaming complete flag
    isStreamingCompleteRef.current = false;

    const assistantId = (Date.now() + 1).toString();

    setChatMessages((prev) => [
      ...prev,
      { id: assistantId, role: "assistant", content: "", timestamp: new Date() },
    ]);

    // Track current assistant message ID for streaming updates
    currentAssistantIdRef.current = assistantId;

    try {
      // Build user prompt with form context
      const userPrompt = formContext
        ? `用户需求：${currentInput}\n\n${formContext}`
        : `用户需求：${currentInput}`;

      await createSimpleSkillStream(
        { user_request: userPrompt },
        {
          onThinkingUpdate: (step, desc) => {
            setThinkingStep(step);
            setThinkingDescription(desc || THINKING_STEPS_ZH.find((s) => s.step === step)?.description || "");
          },
          onThinkingVisible: (visible) => {
            setIsThinkingVisible(visible);
          },
          onStepCount: (step) => {
            setThinkingStep(step);
            setThinkingDescription(THINKING_STEPS_ZH.find((s) => s.step === step)?.description || "生成技能内容中 ...");
          },
          onFormContent: (content) => {
            if (isStreamingCompleteRef.current) return;
            setFormStreamingContent((prev) => prev + content);
          },
          onSummaryContent: (content) => {
            setSummaryStreamingContent((prev) => prev + content);
            setIsSummaryVisible(true);
          },
          onDone: (finalResult) => {
            if (!isMountedRef.current) return;
            setIsThinkingVisible(false);
            setIsContentStreaming(false);
            currentAssistantIdRef.current = "";
            isStreamingCompleteRef.current = true;

            const finalFormContent = finalResult.formContent;
            if (finalFormContent) {
              const skillInfo = extractSkillInfoFromContent(finalFormContent);

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
              if (skillInfo && skillInfo.contentWithoutFrontmatter) {
                form.setFieldsValue({ content: skillInfo.contentWithoutFrontmatter });
                setFormStreamingContent(skillInfo.contentWithoutFrontmatter);
              }
              message.success(t("skillManagement.message.skillReadyForSave"));
            }
          },
          onError: (errorMsg) => {
            log.error("Interactive skill creation error:", errorMsg);
            message.error(t("skillManagement.message.chatError"));
            setChatMessages((prev) => prev.filter((m) => m.id !== assistantId));
            setIsContentStreaming(false);
            currentAssistantIdRef.current = "";
          },
        }
      );
    } catch (error) {
      log.error("Interactive skill creation error:", error);
      message.error(t("skillManagement.message.chatError"));
      setChatMessages((prev) => prev.filter((m) => m.id !== assistantId));
      setIsContentStreaming(false);
    } finally {
      setIsChatLoading(false);
    }
  };

  // Handle chat clear - reset all form fields
  const handleChatClear = async () => {
    await clearChatAndTempFile();
    setChatMessages([]);
    form.resetFields(["name", "description", "source", "tags", "content"]);
    setInteractiveSkillName("");
    setFormStreamingContent("");
    setThinkingStreamingContent("");
    setSummaryStreamingContent("");
    setIsSummaryVisible(false);
  };

  // Scroll to bottom of chat when new messages arrive
  useEffect(() => {
    if (chatContainerRef.current) {
      chatContainerRef.current.scrollTop = chatContainerRef.current.scrollHeight;
    }
  }, [chatMessages]);

  // Scroll to bottom of content textarea when streaming content updates
  useEffect(() => {
    if (formStreamingContent) {
      const textarea = document.getElementById(contentTextAreaId.current);
      if (textarea) {
        textarea.scrollTop = textarea.scrollHeight;
      }
    }
  }, [formStreamingContent]);

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
                  {msg.role === "assistant" && isThinkingVisible && !isSummaryVisible ? (
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
                        content={isSummaryVisible ? summaryStreamingContent : msg.content}
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
                    handleChatSend();
                  }
                }}
                placeholder={t("skillManagement.form.chatPlaceholder")}
                disabled={isChatLoading}
                autoSize={{ minRows: 1, maxRows: 3 }}
                className="resize-none"
              />
              <Button
                type="primary"
                icon={<Send size={14} />}
                onClick={handleChatSend}
                loading={isChatLoading}
                disabled={!chatInput.trim()}
                style={{ width: 30, height: 30, flexShrink: 0 }}
              />
            </Flex>
          </div>
        </div>

        {/* Right side: Form */}
        <div style={{ width: "60%" }} className="overflow-y-auto overflow-x-hidden custom-scrollbar pr-1">
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
                  <Select
                    mode="tags"
                    suffixIcon={null}
                    placeholder={t("skillManagement.form.tagsPlaceholder")}
                    onFocus={() => setIsTagsFocused(true)}
                    onBlur={() => setIsTagsFocused(false)}
                    open={false}
                  />
                </Form.Item>
              </Col>
            </Row>

            <Form.Item
              name="content"
              label={t("skillManagement.form.content")}
            >
              <TextArea
                id={contentTextAreaId.current}
                rows={6}
                placeholder={t("skillManagement.form.contentPlaceholder")}
                value={formStreamingContent}
                onChange={(e) => {
                  if (isContentStreaming) return;
                  form.setFieldValue("content", e.target.value);
                  setFormStreamingContent(e.target.value);
                }}
                disabled={isContentStreaming}
              />
            </Form.Item>
          </Form>
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
