// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useEffect, useMemo, useState } from "react";
import { App, Button, Empty, Input, Modal, Tree } from "antd";
import { Copy, Download, Eye, FileText, Maximize2, Search } from "lucide-react";
import { useTranslation } from "react-i18next";
import { MarkdownRenderer } from "@/components/common/markdownRenderer";
import { buildSkillDetailTree } from "@/lib/skillDetailFiles";
import type { SkillFileContent } from "@/types/skill";
import SkillFileSource, { getSkillSourceLines } from "./SkillFileSource";
import SkillFileTreeTitle from "./SkillFileTreeTitle";
import panel from "./skill-panel.module.css";

export default function SkillReadOnlyDetail({
  source,
  tags,
  description,
  files,
  hideMetadata = false,
  sourcePreview = false,
  showFileActions = !sourcePreview,
}: {
  source: string;
  tags: string[];
  description: string;
  files: SkillFileContent[];
  /** Skip the label/value metadata block when the shell already renders it. */
  hideMetadata?: boolean;
  sourcePreview?: boolean;
  showFileActions?: boolean;
}) {
  const { t } = useTranslation("common");
  const { message } = App.useApp();
  const [expandedPreview, setExpandedPreview] = useState(false);
  const [markdownPreview, setMarkdownPreview] = useState(false);
  const [search, setSearch] = useState("");
  const [selectedPath, setSelectedPath] = useState("");
  const [expandedKeys, setExpandedKeys] = useState<string[]>([]);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- Reset per-archive selection state when the file list changes.
    setSearch("");
    setExpandedPreview(false);
    setMarkdownPreview(false);
    setSelectedPath(
      files.find((file) => /^SKILL\.md$/i.test(file.path))?.path ??
        files.find((file) => /\/SKILL\.md$/i.test(file.path))?.path ??
        files[0]?.path ??
        ""
    );
    setExpandedKeys(
      sourcePreview
        ? [
            ...new Set(
              files
                .filter((file) => file.path.includes("/"))
                .map((file) => file.path.split("/")[0])
            ),
          ]
        : []
    );
  }, [files, sourcePreview]);
  const tree = useMemo(
    () => buildSkillDetailTree(files, search),
    [files, search]
  );
  const active = files.find((file) => file.path === selectedPath);
  const readable =
    active && active.status !== "unsupported" && active.status !== "read_error";
  const lineCount =
    sourcePreview && readable && active.content
      ? getSkillSourceLines(active.content).length
      : 0;
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
  const renderPreview = () =>
    !active ? (
      <Empty description={t("skillManagement.detail.selectFile")} />
    ) : !readable ? (
      <p className="text-[#777777]">
        {t(
          active.status === "read_error"
            ? "skillManagement.detail.fileReadFailed"
            : "skillManagement.detail.filePreviewUnsupported"
        )}
      </p>
    ) : sourcePreview && !markdownPreview ? (
      <SkillFileSource content={active.content} />
    ) : active.path.toLowerCase().endsWith(".md") ? (
      <MarkdownRenderer
        content={active.content}
        enableSkillDirectives
        onSkillDirectiveClick={(path) => {
          if (files.some((file) => file.path === path)) setSelectedPath(path);
        }}
      />
    ) : (
      <pre className="whitespace-pre-wrap break-words font-mono text-xs leading-5">
        {active.content}
      </pre>
    );
  return (
    <div className="space-y-6 text-body-2 leading-[22px] text-foreground">
      {hideMetadata ? null : (
        <section className="space-y-3 border-b border-border pb-5">
          <h3 className="font-semibold">
            {t("resourceCenter.agentDetail.basicInfo")}
          </h3>
          <dl className="grid grid-cols-[minmax(5rem,max-content)_minmax(0,1fr)] gap-x-4 gap-y-3">
            <div className="contents">
              <dt className="text-muted-foreground">
                {t("skillManagement.form.source")}
              </dt>
              <dd className="break-words">{source || "—"}</dd>
            </div>
            <div className="contents">
              <dt className="text-muted-foreground">
                {t("skillManagement.form.tags")}
              </dt>
              <dd className="flex flex-wrap gap-2">
                {tags.length
                  ? tags.map((tag) => (
                      <span
                        key={tag}
                        className="rounded bg-muted px-2 text-body-1 leading-5 text-muted-foreground"
                      >
                        {tag}
                      </span>
                    ))
                  : "—"}
              </dd>
            </div>
            <div className="contents">
              <dt className="text-muted-foreground">
                {t("skillManagement.form.description")}
              </dt>
              <dd className="whitespace-pre-wrap break-words">
                {description || t("skillRepository.common.noDescription")}
              </dd>
            </div>
          </dl>
        </section>
      )}
      <section className="space-y-2">
        {hideMetadata ? null : (
          <h3 className="font-semibold">
            {t("skillRepository.detail.skillFiles")}
          </h3>
        )}
        <div className={`${panel.panel} h-[460px]`}>
          <aside className={panel.sidebar}>
            <h4 className={panel.toolbar}>
              {sourcePreview
                ? t("skillRepository.detail.fileCount", { count: files.length })
                : t("skillManagement.detail.files")}
            </h4>
            {showFileActions && (
              <Input
                className="!mx-2 !mt-2 !w-[calc(100%-1rem)]"
                allowClear
                prefix={<Search size={14} aria-hidden />}
                placeholder={t("resourceCenter.search")}
                aria-label={t("skillManagement.detail.files")}
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
            )}
            <div className="min-h-0 flex-1 overflow-auto">
              {tree.length ? (
                <Tree
                  blockNode
                  className={panel.tree}
                  treeData={tree}
                  selectedKeys={selectedPath ? [selectedPath] : []}
                  expandedKeys={
                    search.trim()
                      ? files.flatMap((file) =>
                          file.path
                            .split("/")
                            .slice(0, -1)
                            .map((_part, index) =>
                              file.path
                                .split("/")
                                .slice(0, index + 1)
                                .join("/")
                            )
                        )
                      : expandedKeys
                  }
                  onExpand={(keys) => setExpandedKeys(keys.map(String))}
                  onSelect={(_keys, info) => {
                    if (info.node.isLeaf) {
                      setSelectedPath(String(info.node.key));
                      setMarkdownPreview(false);
                    }
                  }}
                  titleRender={(node) => (
                    <SkillFileTreeTitle
                      name={node.title}
                      isFile={node.isLeaf}
                    />
                  )}
                />
              ) : (
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description={t("skillManagement.detail.noFiles")}
                />
              )}
            </div>
          </aside>
          <div className="flex min-h-0 min-w-0 flex-1 flex-col">
            <div className={panel.toolbar}>
              {sourcePreview && active && <FileText size={14} aria-hidden />}
              <span className="min-w-0 flex-1 truncate" title={active?.path}>
                {(sourcePreview
                  ? active?.path.split("/").pop()
                  : active?.path) || t("skillManagement.detail.selectFile")}
              </span>
              {sourcePreview && active?.path.toUpperCase() === "SKILL.MD" && (
                <span className="rounded bg-primary/10 px-1.5 text-primary">
                  {t("skillRepository.detail.entryFile")}
                </span>
              )}
              {sourcePreview && readable && !markdownPreview && (
                <span className="shrink-0 text-muted-foreground">
                  {t("skillRepository.detail.lineCount", { count: lineCount })}
                </span>
              )}
              {showFileActions && (
                <>
                  {sourcePreview &&
                    readable &&
                    active.path.toLowerCase().endsWith(".md") && (
                      <Button
                        type="text"
                        size="small"
                        icon={<Eye size={15} />}
                        aria-label={t("common.preview")}
                        title={t("common.preview")}
                        aria-pressed={markdownPreview}
                        onClick={() => setMarkdownPreview(!markdownPreview)}
                      />
                    )}
                  <Button
                    type="text"
                    size="small"
                    icon={<Maximize2 size={15} />}
                    aria-label={t("skillManagement.detail.expand")}
                    title={t("skillManagement.detail.expand")}
                    disabled={!readable}
                    onClick={() => setExpandedPreview(true)}
                  />
                  <Button
                    type="text"
                    size="small"
                    icon={<Copy size={15} />}
                    aria-label={t("common.copy")}
                    title={t("common.copy")}
                    disabled={!readable}
                    onClick={copy}
                  />
                  <Button
                    type="text"
                    size="small"
                    icon={<Download size={15} />}
                    aria-label={t("skillRepository.detail.downloadFile")}
                    title={t("skillRepository.detail.downloadFile")}
                    disabled={!readable}
                    onClick={download}
                  />
                </>
              )}
            </div>
            <div
              className={
                sourcePreview && !markdownPreview
                  ? "min-h-0 flex-1 overflow-auto"
                  : "min-h-0 flex-1 overflow-auto p-4"
              }
            >
              {renderPreview()}
            </div>
          </div>
        </div>
      </section>
      <Modal
        open={expandedPreview}
        onCancel={() => setExpandedPreview(false)}
        footer={null}
        title={active?.path}
        width="90vw"
        centered
        destroyOnHidden
      >
        <div className="max-h-[75vh] overflow-auto p-4">{renderPreview()}</div>
      </Modal>
    </div>
  );
}
