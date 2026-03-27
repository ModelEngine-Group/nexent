"use client";

import { useState, useEffect, useMemo, useRef } from "react";
import { useTranslation } from "react-i18next";
import ReactMarkdown from "react-markdown";
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
  Progress,
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
} from "lucide-react";
import { getAgentByName } from "@/services/agentConfigService";
import { conversationService } from "@/services/conversationService";
import { extractSkillInfo } from "@/lib/skillFileUtils";
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
  processSkillStream,
  deleteSkillCreatorTempFile,
  findSkillByName,
  searchSkillsByName as searchSkillsByNameUtil,
  type SkillListItem,
} from "@/services/skillService";
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

  // skill_creator agent state (cached after first lookup)
  const [skillCreatorAgentId, setSkillCreatorAgentId] = useState<number | null>(null);
  const skillCreatorAgentIdRef = useRef<number | null>(null);

  // Track if component is mounted to prevent state updates after unmount
  const isMountedRef = useRef(true);

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
      setSkillCreatorAgentId(null);
      skillCreatorAgentIdRef.current = null;
      setThinkingStep(0);
      setThinkingDescription("");
      setIsThinkingVisible(false);
    }
  }, [isOpen, form]);

  // Track component mount status for async callback safety
  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
    };
  }, []);

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
        source: skill.source || "Custom",
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

  // Cleanup temp file when modal is closed
  const handleModalClose = async () => {
    if (activeTab === "interactive" && chatMessages.length > 0) {
      await deleteSkillCreatorTempFile();
    }
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

  // Resolve skill_creator agent
  const resolveSkillCreatorAgent = async (): Promise<number | null> => {
    if (skillCreatorAgentIdRef.current !== null) {
      const cached = skillCreatorAgentIdRef.current;
      return cached < 0 ? null : cached;
    }
    const result = await getAgentByName("skill_creator");
    if (!result) return null;
    skillCreatorAgentIdRef.current = -result.agent_id;
    setSkillCreatorAgentId(result.agent_id);
    return result.agent_id;
  };

  // Handle chat send for interactive creation
  const handleChatSend = async () => {
    if (!chatInput.trim() || isChatLoading) return;

    const currentInput = chatInput.trim();
    setChatInput("");

    const userMessage: ChatMessage = {
      id: Date.now().toString(),
      role: "user",
      content: currentInput,
      timestamp: new Date(),
    };

    setChatMessages((prev) => [...prev, userMessage]);
    setIsChatLoading(true);
    setThinkingStep(0);
    setThinkingDescription(THINKING_STEPS_ZH.find((s) => s.step === 0)?.description || "");
    setIsThinkingVisible(true);

    const assistantId = (Date.now() + 1).toString();
    setChatMessages((prev) => [
      ...prev,
      { id: assistantId, role: "assistant", content: "", timestamp: new Date() },
    ]);

    try {
      const agentId = await resolveSkillCreatorAgent();
      if (!agentId) {
        throw new Error("skill_creator agent not found");
      }

      const history = chatMessages.map((msg) => ({
        role: msg.role === "user" ? "user" : "assistant",
        content: msg.content,
      }));

      const reader = await conversationService.runAgent(
        {
          query: currentInput,
          conversation_id: 0,
          history,
          agent_id: agentId,
          is_debug: true,
        },
        undefined as unknown as AbortSignal
      );

      await processSkillStream(
        reader,
        (step, description) => {
          setThinkingStep(step);
          setThinkingDescription(description);
        },
        setIsThinkingVisible,
        async (finalAnswer) => {
          if (!isMountedRef.current) return;

          setChatMessages((prev) =>
            prev.map((msg) =>
              msg.id === assistantId ? { ...msg, content: finalAnswer } : msg
            )
          );

          const { parseSkillDraft } = await import("@/lib/skillFileUtils");
          const skillDraft = parseSkillDraft(finalAnswer);

          if (skillDraft) {
            form.setFieldValue("name", skillDraft.name);
            form.setFieldValue("description", skillDraft.description);
            form.setFieldValue("tags", skillDraft.tags);
            form.setFieldValue("content", skillDraft.content);
            setInteractiveSkillName(skillDraft.name);
            const existingSkill = allSkills.find(
              (s) => s.name.toLowerCase() === skillDraft.name.toLowerCase()
            );
            setIsCreateMode(!existingSkill);
            message.success(t("skillManagement.message.skillReadyForSave"));
          } else {
            // Fallback: read from temp file
            try {
              const { fetchSkillConfig, fetchSkillFileContent } = await import("@/services/agentConfigService");
              const config = await fetchSkillConfig("simple-skill-creator");

              if (config && config.temp_filename) {
                const tempFilename = config.temp_filename as string;
                const tempContent = await fetchSkillFileContent("simple-skill-creator", tempFilename);

                if (tempContent) {
                  const { extractSkillInfoFromContent } = await import("@/lib/skillFileUtils");
                  const skillInfo = extractSkillInfoFromContent(tempContent);

                  if (skillInfo && skillInfo.name) {
                    form.setFieldValue("name", skillInfo.name);
                    setInteractiveSkillName(skillInfo.name);
                    const existingSkill = allSkills.find(
                      (s) => s.name.toLowerCase() === skillInfo.name.toLowerCase()
                    );
                    setIsCreateMode(!existingSkill);
                  }
                  if (skillInfo && skillInfo.description) {
                    form.setFieldValue("description", skillInfo.description);
                  }
                  if (skillInfo && skillInfo.tags && skillInfo.tags.length > 0) {
                    form.setFieldValue("tags", skillInfo.tags);
                  }
                  // Use content without frontmatter
                  if (skillInfo.contentWithoutFrontmatter) {
                    form.setFieldValue("content", skillInfo.contentWithoutFrontmatter);
                  }
                }
              }
            } catch (error) {
              log.warn("Failed to load temp file content:", error);
            }
          }
        },
        "zh"
      );
    } catch (error) {
      log.error("Interactive skill creation error:", error);
      message.error(t("skillManagement.message.chatError"));
      setChatMessages((prev) => prev.filter((m) => m.id !== assistantId));
    } finally {
      setIsChatLoading(false);
    }
  };

  // Handle chat clear
  const handleChatClear = async () => {
    const { clearChatAndTempFile } = await import("@/services/skillService");
    await clearChatAndTempFile();
    setChatMessages([]);
  };

  // Scroll to bottom of chat when new messages arrive
  useEffect(() => {
    if (chatContainerRef.current) {
      chatContainerRef.current.scrollTop = chatContainerRef.current.scrollHeight;
    }
  }, [chatMessages]);

  // Import extractSkillGenerationResult
  const extractSkillGenerationResult = (content: string): string => {
    const skillTagIndex = content.indexOf("</SKILL>");
    if (skillTagIndex !== -1) {
      return content.substring(skillTagIndex + 8).trim();
    }
    return content;
  };

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
                  {msg.role === "assistant" && isThinkingVisible && msg.content === "" ? (
                    <div className="min-w-[200px]">
                      <Progress
                        percent={thinkingStep * 20}
                        status="active"
                        strokeColor="#52c41a"
                        railColor="#e8e8e8"
                      />
                      {thinkingDescription && (
                        <span className="text-xs text-gray-500 mt-1 block">
                          {thinkingDescription}
                        </span>
                      )}
                    </div>
                  ) : msg.role === "assistant" ? (
                    <div className="markdown-body">
                      <ReactMarkdown>
                        {extractSkillGenerationResult(msg.content)}
                      </ReactMarkdown>
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
                rows={6}
                placeholder={t("skillManagement.form.contentPlaceholder")}
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
