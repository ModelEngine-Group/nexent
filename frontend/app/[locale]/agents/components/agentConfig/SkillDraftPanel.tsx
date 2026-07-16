"use client";

import { useState } from "react";
import type {
  ChangeEvent,
  Dispatch,
  KeyboardEvent,
  MutableRefObject,
  SetStateAction,
} from "react";
import type { FormInstance } from "antd";
import { Button, Col, Form, Input, Modal, Row, Select, Tooltip } from "antd";
import { FileText, Folder, Maximize2, Pencil, Plus, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { SkillFileContent, SkillFormData } from "@/types/skill";

const { TextArea } = Input;
const MAX_SKILL_TAGS = 5;
const MAX_SKILL_TAG_LENGTH = 20;

interface SkillDraftPanelProps {
  form: FormInstance<SkillFormData>;
  skillTabs: SkillFileContent[];
  setSkillTabs: Dispatch<SetStateAction<SkillFileContent[]>>;
  activeSkillTab: string;
  setActiveSkillTab: Dispatch<SetStateAction<string>>;
  isStreaming?: boolean;
  readOnly?: boolean;
  onNameChange?: (event: ChangeEvent<HTMLInputElement>) => void;
  textareaRefs?: MutableRefObject<Record<string, unknown>>;
  shouldAutoScrollRef?: MutableRefObject<Record<string, boolean>>;
  onTextareaScroll?: (tabPath: string) => void;
  className?: string;
}

export default function SkillDraftPanel({
  form,
  skillTabs,
  setSkillTabs,
  activeSkillTab,
  setActiveSkillTab,
  isStreaming = false,
  readOnly = false,
  onNameChange,
  textareaRefs,
  shouldAutoScrollRef,
  onTextareaScroll,
  className,
}: SkillDraftPanelProps) {
  const { t } = useTranslation("common");
  const [editingTabKey, setEditingTabKey] = useState<string | null>(null);
  const [editingTabName, setEditingTabName] = useState("");
  const [expandedEditorPath, setExpandedEditorPath] = useState("");
  const [expandedEditorContent, setExpandedEditorContent] = useState("");

  const dedupeSkillTabs = (tabs: SkillFileContent[]) =>
    tabs.filter(
      (tab, index, self) =>
        self.findIndex((item) => item.path === tab.path) === index
    );

  const visibleSkillTabs = dedupeSkillTabs(skillTabs);
  const activeFile =
    visibleSkillTabs.find((tab) => tab.path === activeSkillTab) ||
    visibleSkillTabs[0];
  const canEditFiles = !readOnly && !isStreaming;

  const renameTab = (fromPath: string | null, toPath: string) => {
    if (!fromPath || !toPath.trim()) return;
    const nextPath = toPath.trim();
    setSkillTabs((prev) =>
      prev.map((tab) =>
        tab.path === fromPath ? { ...tab, path: nextPath } : tab
      )
    );
    if (activeSkillTab === fromPath) {
      setActiveSkillTab(nextPath);
    }
  };

  const renderFileActions = (tab: SkillFileContent) => {
    if (!canEditFiles || tab.path === "SKILL.md") return null;
    return (
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
            const newTabs = skillTabs.filter((item) => item.path !== tab.path);
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
    );
  };

  const handleFileRowKeyDown = (
    event: KeyboardEvent<HTMLDivElement>,
    path: string
  ) => {
    if (
      event.target === event.currentTarget &&
      (event.key === "Enter" || event.key === " ")
    ) {
      event.preventDefault();
      setActiveSkillTab(path);
    }
  };

  const renderFileName = (tab: SkillFileContent, displayName: string) => {
    if (editingTabKey !== tab.path) {
      return <span className="min-w-0 flex-1 truncate">{displayName}</span>;
    }

    return (
      <input
        className="min-w-0 flex-1 rounded border border-blue-400 px-1 py-0.5 text-xs"
        value={editingTabName}
        autoFocus
        onChange={(e) => setEditingTabName(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            e.stopPropagation();
            renameTab(editingTabKey, editingTabName);
            setEditingTabKey(null);
            setEditingTabName("");
          } else if (e.key === "Escape") {
            e.stopPropagation();
            setEditingTabKey(null);
            setEditingTabName("");
          }
        }}
        onBlur={() => {
          renameTab(editingTabKey, editingTabName);
          setEditingTabKey(null);
          setEditingTabName("");
        }}
        onClick={(e) => e.stopPropagation()}
      />
    );
  };

  const handleTagInputKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key !== "Enter") return;

    const tags = form.getFieldValue("tags");
    if (Array.isArray(tags) && tags.length >= MAX_SKILL_TAGS) {
      form.setFields([
        {
          name: "tags",
          errors: [t("skillManagement.form.tagsMaxCount")],
        },
      ]);
    }
  };

  return (
    <div
      className={`flex h-full min-h-0 flex-col gap-2 overflow-hidden ${className || ""}`}
    >
      <div className="shrink-0 rounded-2xl border border-slate-200 bg-white px-5 pb-2 pt-3 shadow-sm">
        <Form
          form={form}
          layout="vertical"
          className="skill-build-info-form"
          initialValues={{
            source: "custom",
            tags: [],
          }}
          disabled={readOnly}
        >
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                name="name"
                label={t("skillManagement.form.name")}
                style={{ marginBottom: 10 }}
                rules={[
                  {
                    required: true,
                    message: t("skillManagement.form.nameRequired"),
                  },
                ]}
              >
                <Input
                  onChange={onNameChange}
                  placeholder={t("skillManagement.form.namePlaceholder")}
                  allowClear={!readOnly}
                  readOnly={readOnly}
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
                  options={[
                    { label: t("skillPool.group.custom"), value: "custom" },
                  ]}
                />
              </Form.Item>
            </Col>
          </Row>

          <Form.Item
            name="description"
            label={t("skillManagement.form.description")}
            style={{ marginBottom: 10 }}
            rules={[
              {
                required: true,
                message: t("skillManagement.form.descriptionRequired"),
              },
            ]}
          >
            <TextArea
              rows={2}
              placeholder={t("skillManagement.form.descriptionPlaceholder")}
              readOnly={readOnly}
              style={{ resize: "none" }}
            />
          </Form.Item>

          <Form.Item
            name="tags"
            label={t("skillManagement.form.tags")}
            style={{ marginBottom: 8 }}
            rules={[
              {
                validator: (_, value?: string[]) => {
                  const tags = Array.isArray(value) ? value : [];
                  if (tags.length > MAX_SKILL_TAGS) {
                    return Promise.reject(
                      new Error(t("skillManagement.form.tagsMaxCount"))
                    );
                  }
                  if (tags.some((tag) => tag.length > MAX_SKILL_TAG_LENGTH)) {
                    return Promise.reject(
                      new Error(t("skillManagement.form.tagMaxLength"))
                    );
                  }
                  return Promise.resolve();
                },
              },
            ]}
          >
            <Select
              mode="tags"
              maxCount={MAX_SKILL_TAGS}
              suffixIcon={null}
              placeholder={t("skillManagement.form.tagsPlaceholder")}
              open={false}
              onInputKeyDown={handleTagInputKeyDown}
              onChange={() => {
                form.validateFields(["tags"]).catch(() => undefined);
              }}
              style={{ width: "100%" }}
              popupMatchSelectWidth={false}
            />
          </Form.Item>
        </Form>
      </div>

      <div
        className={`flex min-h-0 flex-1 flex-col ${readOnly ? "min-h-[300px]" : ""}`}
      >
        <div className="flex min-h-0 flex-1 overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
          <div className="flex w-[28%] min-w-[140px] shrink-0 flex-col border-r border-slate-200 bg-slate-50/60">
            <div className="flex h-11 items-center justify-between border-b border-slate-200 px-3">
              <span className="text-sm font-medium text-slate-700">
                {t("skillManagement.detail.file")}
              </span>
              {canEditFiles ? (
                <Button
                  type="text"
                  size="small"
                  icon={<Plus size={14} />}
                  onClick={() => {
                    const newPath = `file_${Date.now()}.md`;
                    setSkillTabs((prev) => [
                      ...prev,
                      { path: newPath, content: "" },
                    ]);
                    setActiveSkillTab(newPath);
                    if (shouldAutoScrollRef) {
                      shouldAutoScrollRef.current[newPath] = true;
                    }
                  }}
                />
              ) : null}
            </div>
            <div className="custom-scrollbar min-h-0 flex-1 overflow-y-auto py-2">
              {visibleSkillTabs
                .filter((tab) => !tab.path.includes("/"))
                .map((tab) => (
                  <div
                    key={tab.path}
                    role="button"
                    tabIndex={0}
                    className={`group/file mx-2 flex h-9 cursor-pointer items-center gap-2 rounded-lg px-2 text-xs transition-colors ${
                      activeSkillTab === tab.path
                        ? "bg-blue-50 text-blue-700"
                        : "text-slate-600 hover:bg-slate-100"
                    }`}
                    onClick={() => setActiveSkillTab(tab.path)}
                    onKeyDown={(event) => handleFileRowKeyDown(event, tab.path)}
                  >
                    <FileText size={15} className="shrink-0" />
                    {renderFileName(tab, tab.path)}
                    {renderFileActions(tab)}
                  </div>
                ))}
              {Array.from(
                new Set(
                  visibleSkillTabs
                    .filter((tab) => tab.path.includes("/"))
                    .map((tab) => tab.path.split("/")[0])
                )
              ).map((folderName) => (
                <div key={folderName}>
                  <div className="mx-2 mt-1 flex h-8 items-center gap-2 rounded-lg px-2 text-xs font-normal text-slate-500">
                    <Folder size={15} className="shrink-0 text-amber-500" />
                    <span className="min-w-0 flex-1 truncate">
                      {folderName}
                    </span>
                  </div>
                  {visibleSkillTabs
                    .filter((tab) => tab.path.startsWith(`${folderName}/`))
                    .map((tab) => (
                      <div
                        key={tab.path}
                        role="button"
                        tabIndex={0}
                        className={`group/file mx-2 flex h-9 cursor-pointer items-center gap-2 rounded-lg pl-7 pr-2 text-xs transition-colors ${
                          activeSkillTab === tab.path
                            ? "bg-blue-50 text-blue-700"
                            : "text-slate-600 hover:bg-slate-100"
                        }`}
                        onClick={() => setActiveSkillTab(tab.path)}
                        onKeyDown={(event) =>
                          handleFileRowKeyDown(event, tab.path)
                        }
                      >
                        <FileText size={15} className="shrink-0" />
                        {renderFileName(
                          tab,
                          tab.path.slice(folderName.length + 1)
                        )}
                        {renderFileActions(tab)}
                      </div>
                    ))}
                </div>
              ))}
            </div>
          </div>
          {activeFile ? (
            <div className="flex min-w-0 flex-1 flex-col">
              <div className="flex h-11 shrink-0 items-center justify-between border-b border-slate-200 px-4 text-sm font-medium text-slate-700">
                <span className="min-w-0 flex-1 truncate">
                  {activeFile.path}
                </span>
                <Tooltip title={t("skillManagement.detail.expand")}>
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
                readOnly={readOnly}
                style={{ resize: "none" }}
                ref={(el) => {
                  if (!textareaRefs) return;
                  textareaRefs.current[activeFile.path] = el;
                  if (
                    el &&
                    shouldAutoScrollRef &&
                    shouldAutoScrollRef.current[activeFile.path] === undefined
                  ) {
                    shouldAutoScrollRef.current[activeFile.path] = true;
                  }
                }}
                onScroll={() => onTextareaScroll?.(activeFile.path)}
                onChange={(e) => {
                  if (isStreaming || readOnly) return;
                  setSkillTabs((prev) =>
                    prev.map((tab) =>
                      tab.path === activeFile.path
                        ? { ...tab, content: e.target.value }
                        : tab
                    )
                  );
                }}
              />
            </div>
          ) : null}
        </div>
      </div>

      <Modal
        title={expandedEditorPath}
        open={Boolean(expandedEditorPath)}
        onCancel={() => {
          setExpandedEditorPath("");
          setExpandedEditorContent("");
        }}
        centered
        width={640}
        styles={{ body: { padding: 0 } }}
        footer={
          readOnly
            ? null
            : [
                <Button
                  key="cancel-expanded-editor"
                  onClick={() => {
                    setExpandedEditorPath("");
                    setExpandedEditorContent("");
                  }}
                >
                  {t("common.cancel")}
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
                  {t("common.save")}
                </Button>,
              ]
        }
      >
        <TextArea
          value={expandedEditorContent}
          disabled={isStreaming}
          readOnly={readOnly}
          onChange={(e) => {
            if (readOnly) return;
            setExpandedEditorContent(e.target.value);
          }}
          autoSize={{ minRows: 10, maxRows: 28 }}
          className="rounded-none border-0 font-mono text-sm shadow-none focus:border-0 focus:shadow-none"
          style={{ resize: "none" }}
        />
      </Modal>
    </div>
  );
}
