// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useEffect, useMemo, useState } from "react";
import { App, Button, Input, Modal, Tree } from "antd";
import {
  Copy,
  Download,
  Eye,
  FileText,
  Folder,
  Pencil,
  Plus,
  Save,
  Search,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { MarkdownRenderer } from "@/components/common/markdownRenderer";
import { buildSkillDetailTree } from "@/lib/skillDetailFiles";
import { isValidSkillDraftPath } from "@/lib/skillCreationDraft";
import type { SkillFileContent } from "@/types/skill";

export default function SkillCreationFiles({
  files,
  onChange,
  disabled,
  selectedPath,
}: {
  files: SkillFileContent[];
  onChange: (files: SkillFileContent[]) => void;
  disabled: boolean;
  selectedPath?: string;
}) {
  const { t } = useTranslation("common");
  const { message } = App.useApp();
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState("SKILL.md");
  const [editing, setEditing] = useState(false);
  const [adding, setAdding] = useState(false);
  const [path, setPath] = useState("");
  const [pathError, setPathError] = useState(false);
  useEffect(() => {
    if (selectedPath) {
      setSelected(selectedPath);
      setSearch("");
      setEditing(false);
    }
  }, [selectedPath]);
  const tree = useMemo(
    () => buildSkillDetailTree(files, search),
    [files, search]
  );
  const active = files.find((file) => file.path === selected) ?? files[0];
  const readable =
    active && active.status !== "unsupported" && active.status !== "read_error";
  const addFile = () => {
    if (
      !isValidSkillDraftPath(path) ||
      files.some(
        (file) =>
          file.path.toLowerCase() === path.toLowerCase() ||
          file.path.toLowerCase().startsWith(`${path.toLowerCase()}/`) ||
          path.toLowerCase().startsWith(`${file.path.toLowerCase()}/`)
      )
    ) {
      setPathError(true);
      return;
    }
    onChange([...files, { path, content: "" }]);
    setSelected(path);
    setEditing(true);
    setAdding(false);
    setSearch("");
  };
  const copy = async () => {
    if (!readable) return;
    try {
      await navigator.clipboard.writeText(active.content);
      message.success(t("common.copied"));
    } catch {
      message.error(t("agentUsageGuide.copyFailed"));
    }
  };
  const download = () => {
    if (!readable) return;
    const url = URL.createObjectURL(
      new Blob([active.content], { type: "text/plain;charset=utf-8" })
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = active.path.split("/").pop() || "file.txt";
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 0);
  };
  return (
    <>
      <div className="flex h-[560px] min-h-[280px] overflow-hidden rounded border border-[#D9D9D9]">
        <aside className="flex w-[26%] min-w-[140px] max-w-[230px] shrink-0 flex-col gap-3 border-r p-3">
          <div className="flex items-center justify-between text-sm">
            <span>{t("skillManagement.detail.files")}</span>
            <Button
              type="link"
              size="small"
              disabled={disabled}
              icon={<Plus size={12} />}
              onClick={() => {
                setPath("");
                setPathError(false);
                setAdding(true);
              }}
            >
              {t("skillCreation.newFile")}
            </Button>
          </div>
          <Input
            allowClear
            prefix={<Search size={14} />}
            aria-label={t("skillManagement.detail.files")}
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder={t("resourceCenter.search")}
          />
          <div className="min-h-0 flex-1 overflow-auto">
            <Tree
              key={`${search}:${files.length}`}
              defaultExpandAll
              blockNode
              showIcon
              treeData={tree}
              selectedKeys={active ? [active.path] : []}
              icon={(node) =>
                node.isLeaf ? <FileText size={14} /> : <Folder size={14} />
              }
              onSelect={(_keys, info) => {
                if (info.node.isLeaf) {
                  setSelected(String(info.node.key));
                  setEditing(false);
                }
              }}
              titleRender={(node) => (
                <span title={node.title} className="block truncate">
                  {node.title}
                </span>
              )}
            />
          </div>
        </aside>
        <div className="flex min-w-0 flex-1 flex-col bg-[#FAFAFA]">
          <div className="flex h-11 shrink-0 items-center gap-1 border-b bg-white px-3">
            <span
              className="min-w-0 flex-1 truncate text-sm"
              title={active?.path}
            >
              {active?.path}
            </span>
            <Button
              type="text"
              size="small"
              disabled={disabled || !readable}
              icon={<Pencil size={14} />}
              aria-label={t("common.edit")}
              onClick={() => setEditing(true)}
            />
            <Button
              type="text"
              size="small"
              icon={<Eye size={14} />}
              aria-label={t("common.preview")}
              onClick={() => setEditing(false)}
            />
            <Button
              type="text"
              size="small"
              disabled={!readable}
              icon={<Copy size={14} />}
              aria-label={t("common.copy")}
              onClick={copy}
            />
            <Button
              type="text"
              size="small"
              disabled={!readable}
              icon={<Download size={14} />}
              aria-label={t("skillRepository.detail.downloadFile")}
              onClick={download}
            />
            <Button
              type="text"
              size="small"
              disabled={disabled || !readable}
              icon={<Save size={14} />}
              aria-label={t("common.save")}
              onClick={() => setEditing(false)}
            />
          </div>
          <div className="min-h-0 flex-1 overflow-auto p-4">
            {!readable ? (
              <p>
                {t(
                  active?.status === "read_error"
                    ? "skillManagement.detail.fileReadFailed"
                    : "skillManagement.detail.filePreviewUnsupported"
                )}
              </p>
            ) : editing ? (
              <Input.TextArea
                aria-label={t("skillCreation.fileContent")}
                disabled={disabled}
                value={active.content}
                onChange={(event) =>
                  onChange(
                    files.map((file) =>
                      file.path === active.path
                        ? { ...file, content: event.target.value }
                        : file
                    )
                  )
                }
                className="!h-full !resize-none font-mono"
              />
            ) : active.path.toLowerCase().endsWith(".md") ? (
              <MarkdownRenderer content={active.content} />
            ) : (
              <pre className="whitespace-pre-wrap break-words text-xs">
                {active.content}
              </pre>
            )}
          </div>
        </div>
      </div>
      <Modal
        open={adding}
        title={t("skillCreation.newFile")}
        onCancel={() => setAdding(false)}
        onOk={addFile}
        okText={t("common.confirm")}
        cancelText={t("common.cancel")}
        centered
      >
        <Input
          aria-label={t("skillCreation.filePath")}
          placeholder="scripts/helper.py"
          value={path}
          status={pathError ? "error" : undefined}
          onChange={(event) => {
            setPath(event.target.value);
            setPathError(false);
          }}
        />
        {pathError && (
          <p className="mt-2 text-red-600">{t("skillCreation.invalidPath")}</p>
        )}
      </Modal>
    </>
  );
}
