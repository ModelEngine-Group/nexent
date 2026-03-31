"use client";

import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Modal, Descriptions, Tag, Tree } from "antd";
import type { TreeProps } from "antd/es/tree";
import { Skill } from "@/types/agentConfig";
import { fetchSkillFiles, fetchSkillFileContent } from "@/services/agentConfigService";
import { MarkdownRenderer } from "@/components/ui/markdownRenderer";
import {
  buildTreeData,
  collectDirKeys,
  findNodeByKey,
  normalizeSkillFiles,
  resetNodeIdCounter,
  isMarkdownFile,
  isSkillMdFile,
  stripFrontmatter,
} from "@/lib/skillFileUtils";
import type { ExtendedSkillFileNode } from "@/types/skill";
import { SKILL_DETAIL_CONTENT_HEIGHT } from "@/types/skill";

interface SkillDetailModalProps {
  skill: Skill | null;
  open: boolean;
  onClose: () => void;
}

export default function SkillDetailModal({ skill, open, onClose }: SkillDetailModalProps) {
  const { t } = useTranslation("common");

  const [treeData, setTreeData] = useState<ExtendedSkillFileNode[]>([]);
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [fileContent, setFileContent] = useState<string>("");
  const [loadingContent, setLoadingContent] = useState(false);
  const [loadingTree, setLoadingTree] = useState(false);
  const [expandedKeys, setExpandedKeys] = useState<React.Key[]>([]);

  useEffect(() => {
    if (skill && open) {
      loadSkillFiles();
    }
  }, [skill, open]);

  useEffect(() => {
    if (selectedFile && skill) {
      loadFileContent(selectedFile);
    }
  }, [selectedFile, skill]);

  const loadSkillFiles = async () => {
    if (!skill) return;
    setLoadingTree(true);
    try {
      const files = await fetchSkillFiles(skill.name);
      const normalizedFiles = normalizeSkillFiles(files);
      resetNodeIdCounter();
      const built = buildTreeData(normalizedFiles);
      setTreeData(built);
      setExpandedKeys(collectDirKeys(built));
    } catch (error) {
      console.error("Failed to load skill files:", error);
      setTreeData([]);
    } finally {
      setLoadingTree(false);
    }
  };

  const loadFileContent = async (filePath: string) => {
    if (!skill) return;
    setLoadingContent(true);
    try {
      const relativePath = filePath.startsWith(`${skill.name}/`)
        ? filePath.slice(skill.name.length + 1)
        : filePath;
      const content = await fetchSkillFileContent(skill.name, relativePath);
      setFileContent(content || "");
    } catch (error) {
      console.error("Failed to load file content:", error);
      setFileContent("");
    } finally {
      setLoadingContent(false);
    }
  };

  const handleClose = () => {
    setSelectedFile(null);
    setFileContent("");
    setTreeData([]);
    setExpandedKeys([]);
    onClose();
  };

  const handleTreeSelect: TreeProps["onSelect"] = (selectedKeys) => {
    if (selectedKeys.length > 0) {
      const key = selectedKeys[0] as string;
      const node = findNodeByKey(treeData, key);
      if (node?.data?.type === "file" && node.fullPath) {
        setSelectedFile(node.fullPath);
      }
    }
  };

  const handleTreeExpand: TreeProps["onExpand"] = (keys) => {
    setExpandedKeys(keys);
  };

  const handleTreeNodeClick: TreeProps["onClick"] = (e) => {
    const target = e.target as HTMLElement;
    const nodeEle = target.closest('.ant-tree-treenode') as HTMLElement;
    if (!nodeEle) return;

    const nodeKey = nodeEle.getAttribute('data-node-key');
    if (!nodeKey) return;

    const node = findNodeByKey(treeData, nodeKey);
    if (node?.data?.type === "directory") {
      if (expandedKeys.includes(nodeKey)) {
        setExpandedKeys(expandedKeys.filter(k => k !== nodeKey));
      } else {
        setExpandedKeys([...expandedKeys, nodeKey]);
      }
    }
  };

  const renderDescription = (text: string) => {
    if (!text) return <span className="text-gray-400">-</span>;
    return (
      <div
        className="whitespace-pre-wrap overflow-y-auto"
        style={{
          maxHeight: "120px",
        }}
      >
        {text}
      </div>
    );
  };

  const renderTags = (tags?: string[]) => {
    if (!tags || tags.length === 0) {
      return <span className="text-gray-400">-</span>;
    }
    return (
      <div className="flex flex-wrap gap-2">
        {tags.map((tag, index) => (
          <Tag key={index} color="blue" className="mr-2">
            {tag}
          </Tag>
        ))}
      </div>
    );
  };

  const descriptionColumn = {
    labelStyle: {
      fontWeight: 600,
      width: "140px",
      whiteSpace: "nowrap" as const,
    },
    contentStyle: { width: "auto" },
  };

  const renderFileContent = () => {
    if (!fileContent) return null;

    const isMd = isMarkdownFile(selectedFile || "");
    const isSk = isSkillMdFile(selectedFile);

    if (isMd) {
      const contentToRender = isSk ? stripFrontmatter(fileContent) : fileContent;
      return (
        <MarkdownRenderer
          content={contentToRender}
          className="skill-file-preview"
        />
      );
    }

    return (
      <pre className="whitespace-pre-wrap break-words text-sm font-mono">
        {fileContent}
      </pre>
    );
  };

  return (
    <Modal
      title={t("skillManagement.detail.title")}
      open={open}
      onCancel={handleClose}
      footer={null}
      width={1000}
      className="skill-detail-modal"
    >
      {skill && (
        <>
          <Descriptions
            column={1}
            bordered
            className="skill-detail-descriptions"
          >
            <Descriptions.Item
              label={t("skillManagement.form.name")}
              {...descriptionColumn}
            >
              <span className="font-medium">{skill.name}</span>
            </Descriptions.Item>
            <Descriptions.Item
              label={t("skillManagement.form.source")}
              {...descriptionColumn}
            >
              {skill.source || <span className="text-gray-400">-</span>}
            </Descriptions.Item>
            <Descriptions.Item
              label={t("skillManagement.form.description")}
              {...descriptionColumn}
            >
              {renderDescription(skill.description)}
            </Descriptions.Item>
            <Descriptions.Item
              label={t("skillManagement.form.tags")}
              {...descriptionColumn}
            >
              {renderTags(skill.tags)}
            </Descriptions.Item>
            <Descriptions.Item
              label={t("skillManagement.form.content")}
              {...descriptionColumn}
            >
              <div className="flex gap-3 w-full" style={{ minHeight: SKILL_DETAIL_CONTENT_HEIGHT }}>
                {/* Left: File Tree */}
                <div
                  className="border border-gray-200 rounded-md flex-shrink-0"
                  style={{
                    width: "25%",
                    minWidth: "150px",
                    height: SKILL_DETAIL_CONTENT_HEIGHT,
                  }}
                >
                  <div className="p-2 bg-gray-50 border-b border-gray-200 text-sm font-medium text-gray-600 text-ellipsis overflow-hidden whitespace-nowrap">
                    {t("skillManagement.detail.files")}
                  </div>
                  <div
                    className="skill-tree-container"
                    style={{ height: SKILL_DETAIL_CONTENT_HEIGHT - 41 }}
                  >
                    {loadingTree ? (
                      <div className="text-center text-gray-400 py-4">
                        {t("common.loading")}
                      </div>
                    ) : treeData.length > 0 ? (
                      <Tree
                        showIcon
                        showLine={{ showLeafIcon: false }}
                        expandedKeys={expandedKeys}
                        onExpand={handleTreeExpand}
                        onSelect={handleTreeSelect}
                        onClick={handleTreeNodeClick}
                        treeData={treeData}
                        className="skill-file-tree"
                      />
                    ) : (
                      <div className="text-center text-gray-400 text-sm py-2">
                        {t("skillManagement.detail.noFiles")}
                      </div>
                    )}
                  </div>
                </div>

                {/* Right: File Content Preview */}
                <div
                  className="border border-gray-200 rounded-md flex-1 flex flex-col min-w-0"
                  style={{ height: SKILL_DETAIL_CONTENT_HEIGHT }}
                >
                  <div className="p-2 bg-gray-50 border-b border-gray-200 text-sm font-medium text-gray-600 text-ellipsis overflow-hidden whitespace-nowrap flex-shrink-0">
                    {selectedFile || t("skillManagement.detail.preview")}
                  </div>
                  <div className="skill-content-scroll flex-1 overflow-auto">
                    <div className="p-3">
                      {loadingContent ? (
                        <div className="text-center text-gray-400 py-4">
                          {t("common.loading")}
                        </div>
                      ) : fileContent ? (
                        renderFileContent()
                      ) : (
                        <div className="text-center text-gray-400 py-4">
                          {t("skillManagement.detail.selectFile")}
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            </Descriptions.Item>
          </Descriptions>
        </>
      )}

      <style jsx global>{`
        .skill-detail-descriptions .ant-descriptions-item-label {
          font-weight: 600 !important;
          width: 140px;
          white-space: nowrap;
        }
        .skill-detail-descriptions .ant-descriptions-item-content {
          min-height: auto;
          vertical-align: top;
        }

        /* Tree container: scrolling within fixed height */
        .skill-tree-container {
          overflow: auto;
        }
        .skill-tree-container::-webkit-scrollbar {
          width: 6px;
          height: 6px;
        }
        .skill-tree-container::-webkit-scrollbar-track {
          background: #f1f1f1;
        }
        .skill-tree-container::-webkit-scrollbar-thumb {
          background: #c1c1c1;
          border-radius: 3px;
        }
        .skill-tree-container::-webkit-scrollbar-thumb:hover {
          background: #a1a1a1;
        }

        /* Tree nodes */
        .skill-file-tree .ant-tree-treenode {
          padding: 2px 0;
          white-space: nowrap;
        }
        .skill-file-tree .ant-tree-indent-unit {
          width: 16px;
        }
        .skill-file-tree .ant-tree-switcher {
          display: inline-flex !important;
          align-items: center;
          justify-content: center;
          flex-shrink: 0;
        }
        .skill-file-tree .ant-tree-iconEle {
          display: inline-flex !important;
          align-items: center;
          justify-content: center;
          flex-shrink: 0;
          vertical-align: middle;
        }
        .skill-file-tree .ant-tree-iconEle svg {
          vertical-align: middle;
        }
        .skill-file-tree .ant-tree-node-content-wrapper {
          display: inline-flex !important;
          align-items: center;
          gap: 4px;
          white-space: nowrap;
          flex-shrink: 0;
          min-width: 0;
        }
        .skill-file-tree .ant-tree-title {
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }

        /* Content scroll area: fixed height, scrolls internally */
        .skill-content-scroll {
          height: calc(${SKILL_DETAIL_CONTENT_HEIGHT}px - 41px);
          overflow: auto;
        }
        .skill-content-scroll::-webkit-scrollbar {
          width: 6px;
          height: 6px;
        }
        .skill-content-scroll::-webkit-scrollbar-track {
          background: #f1f1f1;
        }
        .skill-content-scroll::-webkit-scrollbar-thumb {
          background: #c1c1c1;
          border-radius: 3px;
        }
        .skill-content-scroll::-webkit-scrollbar-thumb:hover {
          background: #a1a1a1;
        }

        /* Markdown preview: let content flow naturally, scroll at container level */
        .skill-file-preview {
          max-height: none;
          overflow: visible;
        }
        .skill-file-preview .markdown-body {
          overflow: visible;
          max-height: none;
        }
        .skill-file-preview .markdown-body pre {
          overflow: auto;
          max-height: none;
        }

        .skill-detail-modal .ant-modal-body {
          padding: 16px;
        }
        .skill-detail-modal .ant-descriptions-view {
          table-layout: fixed;
        }
      `}</style>
    </Modal>
  );
}
