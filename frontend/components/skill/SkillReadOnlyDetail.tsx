// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useEffect, useMemo, useState } from "react";
import { App, Button, Empty, Input, Modal, Tree } from "antd";
import {
  Copy,
  Download,
  FileText,
  Folder,
  Maximize2,
  Search,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { MarkdownRenderer } from "@/components/common/markdownRenderer";
import { buildSkillDetailTree } from "@/lib/skillDetailFiles";
import type { SkillFileContent } from "@/types/skill";

export default function SkillReadOnlyDetail({
  name,
  source,
  tags,
  description,
  files,
}: {
  name: string;
  source: string;
  tags: string[];
  description: string;
  files: SkillFileContent[];
}) {
  const { t } = useTranslation("common");
  const { message } = App.useApp();
  const [expandedPreview, setExpandedPreview] = useState(false);
  const [search, setSearch] = useState("");
  const [selectedPath, setSelectedPath] = useState("");
  const [expandedKeys, setExpandedKeys] = useState<string[]>([]);
  useEffect(() => {
    setSearch("");
    setExpandedPreview(false);
    setSelectedPath(
      files.find((file) => /(^|\/)SKILL\.md$/i.test(file.path))?.path ??
        files[0]?.path ??
        ""
    );
    setExpandedKeys([]);
  }, [files]);
  const tree = useMemo(
    () => buildSkillDetailTree(files, search),
    [files, search]
  );
  const active = files.find((file) => file.path === selectedPath);
  const readable =
    active && active.status !== "unsupported" && active.status !== "read_error";
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
    <div className="space-y-6 text-sm leading-[22px] text-[#191919]">
      <dl className="space-y-6">
        {[
          ["name", name],
          ["source", source],
        ].map(([key, value]) => (
          <div key={key} className="space-y-2">
            <dt className="text-[#777777]">
              {t(`skillManagement.form.${key}`)}
            </dt>
            <dd className="break-words">{value || "—"}</dd>
          </div>
        ))}
        <div className="space-y-2">
          <dt className="text-[#777777]">{t("skillManagement.form.tags")}</dt>
          <dd className="flex flex-wrap gap-2">
            {tags.length
              ? tags.map((tag) => (
                  <span
                    key={tag}
                    className="rounded bg-[#191919]/5 px-2 text-xs leading-5 text-[#393939]"
                  >
                    {tag}
                  </span>
                ))
              : "—"}
          </dd>
        </div>
        <div className="space-y-2">
          <dt className="text-[#777777]">
            {t("skillManagement.form.description")}
          </dt>
          <dd className="whitespace-pre-wrap break-words">
            {description || t("skillRepository.common.noDescription")}
          </dd>
        </div>
      </dl>
      <section className="space-y-2">
        <h3 className="font-normal">
          {t("skillRepository.detail.skillFiles")}
        </h3>
        <div className="flex h-[min(560px,60vh)] min-h-[280px] flex-col overflow-hidden rounded border border-[#D9D9D9] sm:flex-row">
          <aside className="flex max-h-[180px] shrink-0 flex-col gap-3 border-b p-3 sm:max-h-none sm:w-[220px] sm:border-r sm:border-b-0">
            <h4 className="text-sm font-medium">
              {t("skillManagement.detail.files")}
            </h4>
            <Input
              allowClear
              prefix={<Search size={14} aria-hidden />}
              placeholder={t("resourceCenter.search")}
              aria-label={t("skillManagement.detail.files")}
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
            <div className="min-h-0 flex-1 overflow-auto">
              {tree.length ? (
                <Tree
                  blockNode
                  showIcon
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
                  icon={(node) =>
                    node.isLeaf ? (
                      <FileText
                        size={15}
                        className="text-blue-600"
                        aria-hidden
                      />
                    ) : (
                      <Folder size={15} aria-hidden />
                    )
                  }
                  onSelect={(_keys, info) => {
                    if (info.node.isLeaf)
                      setSelectedPath(String(info.node.key));
                  }}
                  titleRender={(node) => (
                    <span title={node.title} className="block truncate">
                      {node.title}
                    </span>
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
          <div className="flex min-h-0 min-w-0 flex-1 flex-col bg-[#FAFAFA]">
            <div className="flex h-11 shrink-0 items-center gap-2 border-b bg-white px-4">
              <span className="min-w-0 flex-1 truncate" title={active?.path}>
                {active?.path || t("skillManagement.detail.selectFile")}
              </span>
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
            </div>
            <div className="min-h-0 flex-1 overflow-auto p-5">
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
