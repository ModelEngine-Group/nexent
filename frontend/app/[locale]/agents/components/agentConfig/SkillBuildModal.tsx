"use client";

import {
  useState,
  useEffect,
  useMemo,
  useRef,
  useCallback,
  type ChangeEvent,
} from "react";
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
import { Upload as UploadIcon, Trash2, MessageCircle, Box } from "lucide-react";
import { extractSkillInfo } from "@/lib/skillFileUtils";
import yaml from "js-yaml";
import { type SkillFormData, type SkillFileContent } from "@/types/skill";
import {
  fetchSkillsList,
  submitSkillForm,
  submitSkillFromFile,
  findSkillByName,
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
import log from "@/lib/logger";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { USER_ROLES } from "@/const/auth";
import { useGroupDetails, useGroupList } from "@/hooks/group/useGroupList";
import SkillDraftPanel from "./SkillDraftPanel";
import { Nl2SkillChatPanel } from "../../../newchat/assistant-ui/nl2skill-chat-panel";
import type { Nl2SkillStreamEvent } from "../../../newchat/adapter/remote-chat-model-adapter";

const { TextArea } = Input;

const CAN_EDIT_ALL_ROLES: ReadonlySet<string> = new Set([
  USER_ROLES.SU,
  USER_ROLES.ADMIN,
  USER_ROLES.SPEED,
  USER_ROLES.ASSET_OWNER,
]);

interface SkillBuildModalProps {
  isOpen: boolean;
  onCancel: () => void;
  onSuccess: () => void | Promise<void>;
  editingSkill?: MyEditableSkillItem | null;
  onBeforeEditSave?: (skill: MyEditableSkillItem) => Promise<boolean>;
  zIndex?: number;
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

function stripLeadingSkillFrontmatter(content: string): string {
  let normalizedContent = content;
  const frontmatterPattern = /^(?:\uFEFF)?---\r?\n[\s\S]*?\r?\n---(?:\r?\n)*/;

  while (frontmatterPattern.test(normalizedContent)) {
    normalizedContent = normalizedContent.replace(frontmatterPattern, "");
  }

  return normalizedContent;
}

function flattenSkillFiles(
  nodes: SkillFileNode[],
  skillName: string
): Array<{ path: string; previewStatus: "readable" | "unsupported" }> {
  const paths: Array<{
    path: string;
    previewStatus: "readable" | "unsupported";
  }> = [];
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
        paths.push({
          path,
          previewStatus:
            item.preview_status === "unsupported" ? "unsupported" : "readable",
        });
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
  zIndex = 1000,
}: SkillBuildModalProps) {
  const { t, i18n } = useTranslation("common");
  const { user, getAccessibleGroupIds } = useAuthorizationContext();
  const [form] = Form.useForm<SkillFormData>();
  const isEditMode = Boolean(editingSkill);
  const isAdmin = !!user?.role && CAN_EDIT_ALL_ROLES.has(user.role);
  const isCreator =
    !isEditMode ||
    (!!editingSkill?.created_by &&
      !!user?.id &&
      String(editingSkill.created_by) === String(user.id));
  const canEditGroupSettings = isAdmin || isCreator;
  const { data: groupData } = useGroupList(user?.tenantId ?? null);
  const groupNamesById = useMemo(
    () =>
      new Map(
        (groupData?.groups ?? []).map((group) => [
          group.group_id,
          group.group_name,
        ])
      ),
    [groupData?.groups]
  );
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

  const [interactiveSkillName, setInteractiveSkillName] = useState<string>("");

  // Content input streaming state - multi-file tabs
  const [skillTabs, setSkillTabs] = useState<SkillFileContent[]>([
    { path: "SKILL.md", content: "" },
  ]);
  const [activeSkillTab, setActiveSkillTab] = useState<string>("SKILL.md");
  const [isStreaming, setIsStreaming] = useState(false);

  const skillBodyBufferRef = useRef("");
  const streamedBodyLengthRef = useRef(0);
  const streamHasDraftRef = useRef(false);
  const previousTabsRef = useRef<SkillFileContent[] | null>(null);
  const previousDraftFieldsRef = useRef<Partial<SkillFormData> | null>(null);

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

  // Track current tabs during streaming to avoid stale closure issues
  const streamingTabsRef = useRef<SkillFileContent[]>([
    { path: "SKILL.md", content: "" },
  ]);

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
      setActiveTab("interactive");
      setUploadFile(null);
      setInteractiveSkillName("");
      setUploadExtractingName(false);
      setUploadExtractedSkillName("");
      setSkillTabs([{ path: "SKILL.md", content: "" }]);
      streamingTabsRef.current = [{ path: "SKILL.md", content: "" }];
      shouldAutoScrollRef.current = {};
      setActiveSkillTab("SKILL.md");
      setIsStreaming(false);
      skillBodyBufferRef.current = "";
      streamedBodyLengthRef.current = 0;
      streamHasDraftRef.current = false;
      previousTabsRef.current = null;
      previousDraftFieldsRef.current = null;
      setLoadedEditSkillId(null);
      setEditFilesError(null);
      setIsLoadingEditFiles(false);
    }
  }, [isOpen]);

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
          filePaths.map(async ({ path, previewStatus }) => {
            if (previewStatus === "unsupported") {
              return { path, content: "", status: "unsupported" as const };
            }
            try {
              const result = await fetchSkillFileContent(
                resolvedSkillName,
                path
              );
              if (result.status === "unsupported") {
                return { path, content: "", status: "unsupported" as const };
              }
              return {
                path,
                content:
                  path === "SKILL.md"
                    ? stripLeadingSkillFrontmatter(result.content)
                    : result.content,
                status: "readable" as const,
                encoding: result.encoding,
              };
            } catch (error) {
              log.error(`Failed to load skill file ${path}:`, error);
              return { path, content: "", status: "read_error" as const };
            }
          })
        );
        if (!cancelled) {
          const sortedTabs = sortSkillTabs(tabs);
          applySkillInfo(skillInfo);
          setSkillTabs(sortedTabs);
          setActiveSkillTab(sortedTabs[0]?.path || "SKILL.md");
          if (
            sortedTabs.some(
              (tab) => tab.path === "SKILL.md" && tab.status === "read_error"
            )
          ) {
            setEditFilesError(t("skillManagement.message.loadFilesFailed"));
          }
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
        .filter(
          (t) =>
            t.path !== "SKILL.md" &&
            t.status !== "unsupported" &&
            t.status !== "read_error"
        )
        .map((t) => ({
          path: t.path,
          content: t.content || "",
          encoding: t.encoding,
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

  useEffect(() => {
    streamingTabsRef.current = skillTabs;
  }, [skillTabs]);

  const parseAndApplyStreamedFrontmatter = (frontmatterYaml: string) => {
    const parsed = parseStreamedFrontmatter(frontmatterYaml);
    if (!parsed) return;
    const updates: Partial<SkillFormData> = {};
    if (parsed.name && !isEditMode) {
      updates.name = parsed.name;
      setInteractiveSkillName(parsed.name);
    }
    if (parsed.description) updates.description = parsed.description;
    if (parsed.tags.length > 0) updates.tags = parsed.tags;
    if (Object.keys(updates).length > 0) form.setFieldsValue(updates);
  };

  const getDraftSnapshot = useCallback((): Record<string, unknown> => {
    const values = form.getFieldsValue();
    return {
      name: values.name || "",
      description: values.description || "",
      tags: values.tags || [],
      files: streamingTabsRef.current
        .filter(
          (tab) => tab.status !== "unsupported" && tab.status !== "read_error"
        )
        .map((tab) => ({ ...tab })),
    };
  }, [form]);

  const targetedFilesRef = useRef<string[] | null>(null);

  const beginDraftStream = () => {
    if (streamHasDraftRef.current) return;
    previousTabsRef.current = streamingTabsRef.current.map((tab) => ({
      ...tab,
    }));
    const currentFields = form.getFieldsValue();
    previousDraftFieldsRef.current = {
      name: currentFields.name,
      description: currentFields.description,
      tags: currentFields.tags,
    };
    const targets = targetedFilesRef.current;
    const initialTabs = targets?.length
      ? streamingTabsRef.current.map((tab) =>
          targets.includes(tab.path) ? { ...tab, content: "" } : { ...tab }
        )
      : [{ path: "SKILL.md", content: "" }];
    streamHasDraftRef.current = true;
    skillBodyBufferRef.current = "";
    streamedBodyLengthRef.current = 0;
    shouldAutoScrollRef.current = { "SKILL.md": true };
    streamingTabsRef.current = initialTabs;
    setSkillTabs(initialTabs);
    setActiveSkillTab("SKILL.md");
  };

  const appendFileDelta = (path: string, content: string) => {
    setSkillTabs((previous) => {
      const next = previous.some((tab) => tab.path === path)
        ? previous.map((tab) =>
            tab.path === path ? { ...tab, content: tab.content + content } : tab
          )
        : [...previous, { path, content }];
      streamingTabsRef.current = next;
      return next;
    });
  };

  const appendSkillBodyDelta = (content: string) => {
    skillBodyBufferRef.current += content;
    const normalized = skillBodyBufferRef.current.replace(/^\r?\n/, "");
    if (!normalized.startsWith("---")) {
      const delta = normalized.slice(streamedBodyLengthRef.current);
      streamedBodyLengthRef.current = normalized.length;
      if (delta) appendFileDelta("SKILL.md", delta);
      return;
    }

    const frontmatterEnd = normalized.search(/\r?\n---(?:\r?\n|$)/);
    if (frontmatterEnd < 0) {
      parseAndApplyStreamedFrontmatter(
        normalized.slice(3).replace(/^\r?\n/, "")
      );
      return;
    }

    const frontmatter = normalized
      .slice(3, frontmatterEnd)
      .replace(/^\r?\n/, "");
    parseAndApplyStreamedFrontmatter(frontmatter);
    const delimiter =
      normalized.slice(frontmatterEnd).match(/^\r?\n---(?:\r?\n|$)/)?.[0] || "";
    const body = normalized.slice(frontmatterEnd + delimiter.length);
    const delta = body.slice(streamedBodyLengthRef.current);
    streamedBodyLengthRef.current = body.length;
    if (delta) appendFileDelta("SKILL.md", delta);
  };

  const rollbackDraftStream = () => {
    if (previousTabsRef.current) {
      const restored = previousTabsRef.current.map((tab) => ({ ...tab }));
      streamingTabsRef.current = restored;
      setSkillTabs(restored);
    }
    if (previousDraftFieldsRef.current) {
      form.setFieldsValue(previousDraftFieldsRef.current);
      if (!isEditMode) {
        setInteractiveSkillName(previousDraftFieldsRef.current.name || "");
      }
    }
    previousTabsRef.current = null;
    previousDraftFieldsRef.current = null;
    streamHasDraftRef.current = false;
    setIsStreaming(false);
  };

  const handleNl2SkillStreamEvent = useCallback(
    (event: Nl2SkillStreamEvent) => {
      if (event.type === "target_files") {
        targetedFilesRef.current = event.paths?.length ? event.paths : null;
      }
      if (event.type === "agent_new_run" || event.type === "step_count") {
        setIsStreaming(true);
      }
      if (event.type === "skill_body" || event.type === "file_content") {
        beginDraftStream();
        setIsStreaming(true);
      }
      if (event.type === "skill_body") {
        appendSkillBodyDelta(event.content || "");
      } else if (event.type === "file_content") {
        appendFileDelta(event.path || "file.txt", event.content || "");
      } else if (event.type === "done") {
        previousTabsRef.current = null;
        previousDraftFieldsRef.current = null;
        streamHasDraftRef.current = false;
        targetedFilesRef.current = null;
        setIsStreaming(false);
        if (skillBodyBufferRef.current) {
          message.success(t("skillManagement.message.skillReadyForSave"));
        }
      } else if (event.type === "error") {
        targetedFilesRef.current = null;
        rollbackDraftStream();
        message.error(t("skillManagement.message.chatError"));
      } else if (event.type === "stream_closed") {
        if (streamHasDraftRef.current) rollbackDraftStream();
        setIsStreaming(false);
        targetedFilesRef.current = null;
      }
    },
    // The helpers above operate on refs and stable React/Ant Design setters.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [isEditMode, t]
  );

  const modalBodyFrame = "min(92vh, 760px)";
  const modalViewportFrame = "calc(100vh - 32px)";
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
    <Nl2SkillChatPanel
      getDraftSnapshot={getDraftSnapshot}
      onStreamEvent={handleNl2SkillStreamEvent}
      language={i18n.language?.startsWith("en") ? "en" : "zh"}
      availableFiles={skillTabs.filter(
        (tab) => tab.status !== "unsupported" && tab.status !== "read_error"
      )}
      onSkillFileSelect={setActiveSkillTab}
    />
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
      groupNamesById={groupNamesById}
      canEditGroupSettings={canEditGroupSettings}
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
      destroyOnHidden
      zIndex={zIndex}
      centered
      width="min(1180px, calc(100vw - 32px))"
      styles={{
        container: {
          display: "flex",
          flexDirection: "column",
          maxHeight: modalViewportFrame,
          overflow: "hidden",
        },
        body: {
          display: "flex",
          flex: "1 1 auto",
          flexDirection: "column",
          height: modalBodyFrame,
          maxHeight: modalBodyFrame,
          minHeight: 0,
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
