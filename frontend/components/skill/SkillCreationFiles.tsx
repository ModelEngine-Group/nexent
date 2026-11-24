// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useEffect, useMemo, useState } from "react";
import { App, Button, Input, Modal, Tree } from "antd";
import { Copy, Download, Eye, Pencil, Plus, Save, Search } from "lucide-react";
import { useTranslation } from "react-i18next";
import { MarkdownRenderer } from "@/components/common/markdownRenderer";
import { buildSkillDetailTree } from "@/lib/skillDetailFiles";
import { isValidSkillDraftPath } from "@/lib/skillCreationDraft";
import type { SkillFileContent } from "@/types/skill";
import SkillFileSource from "./SkillFileSource";
import SkillFileTreeTitle from "./SkillFileTreeTitle";
import panel from "./skill-panel.module.css";

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
  const [markdownPreview, setMarkdownPreview] = useState(false);
  const [adding, setAdding] = useState(false);
  const [path, setPath] = useState("");
  const [pathError, setPathError] = useState(false);
  useEffect(() => {
    if (selectedPath) {
      setSelected(selectedPath);
      setSearch("");
      setEditing(false);
      setMarkdownPreview(false);
    }
  }, [selectedPath]);
  const tree = useMemo(
    () => buildSkillDetailTree(files, search),
    [files, search]
  );
  const active = files.find((file) => file.path === selected) ?? files[0];
  const readable =
    active && active.status !== "unsupported" && active.status !== "read_error";
  const isMarkdown = active?.path.toLowerCase().endsWith(".md");
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
    setMarkdownPreview(false);
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
      <div className={`${panel.panel} h-[460px]`}>
        <aside className={panel.sidebar}>
          <div className={`${panel.toolbar} justify-between`}>
            <span>
              {t("skillRepository.detail.fileCount", { count: files.length })}
            </span>
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
              <span className="sr-only">{t("skillCreation.newFile")}</span>
            </Button>
          </div>
          <Input
            className="!mx-2 !mt-2 !w-[calc(100%-1rem)]"
            allowClear
            prefix={<Search size={14} />}
            aria-label={t("skillManagement.detail.files")}
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder={t("resourceCenter.search")}
          />
          <div className="min-h-0 flex-1 overflow-auto">
            <Tree
              className={panel.tree}
              key={`${search}:${files.length}`}
              defaultExpandAll
              blockNode
              treeData={tree}
              selectedKeys={active ? [active.path] : []}
              onSelect={(_keys, info) => {
                if (info.node.isLeaf) {
                  setSelected(String(info.node.key));
                  setEditing(false);
                  setMarkdownPreview(false);
                }
              }}
              titleRender={(node) => (
                <SkillFileTreeTitle name={node.title} isFile={node.isLeaf} />
              )}
            />
          </div>
        </aside>
        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
          <div className={`${panel.toolbar} flex-wrap !gap-1`}>
            <span className="min-w-0 flex-1 truncate" title={active?.path}>
              {active?.path}
            </span>
            {active?.path === "SKILL.md" && (
              <span className="rounded bg-primary/10 px-1.5 text-body-1 text-primary">
                {t("skillRepository.detail.entryFile")}
              </span>
            )}
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
              aria-pressed={!editing && markdownPreview}
              disabled={!readable}
              onClick={() => {
                setEditing(false);
                setMarkdownPreview(
                  isMarkdown ? editing || !markdownPreview : false
                );
              }}
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
              onClick={() => {
                setEditing(false);
                setMarkdownPreview(false);
              }}
            />
          </div>
          <div
            className={`min-h-0 flex-1 overflow-auto ${editing || markdownPreview ? "p-3" : ""}`}
          >
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
            ) : markdownPreview && isMarkdown ? (
              <MarkdownRenderer content={active.content} />
            ) : (
              <SkillFileSource content={active.content} />
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
