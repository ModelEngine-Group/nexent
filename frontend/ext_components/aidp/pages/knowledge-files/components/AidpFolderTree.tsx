// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";

import { Button, Dropdown, Spin, Tooltip, Tree } from "antd";
import type { DataNode } from "antd/es/tree";
import type { MenuProps } from "antd";
import {
  DeleteOutlined,
  EditOutlined,
  FolderAddOutlined,
  FolderOpenOutlined,
  FolderOutlined,
  MoreOutlined,
} from "@ant-design/icons";

import type { AidpFolderItem } from "@/ext_components/aidp/shared/types/management";
import aidpKnowledgeService from "@/ext_components/aidp/shared/services/aidpKnowledgeService";
import { getAidpErrorMessage } from "@/ext_components/aidp/shared/utils/aidpErrorUtils";
import {
  folderAncestorPaths,
  joinFolderPath,
} from "@/ext_components/aidp/pages/knowledge-files/utils/aidpFolderUtils";
import {
  collectDroppedFiles,
  type AidpDroppedFile,
} from "@/ext_components/aidp/pages/knowledge-files/utils/aidpDropFiles";
import {
  hasAidpFileMoveDrag,
  readAidpFileMoveDrag,
} from "@/ext_components/aidp/pages/knowledge-files/utils/aidpFileDrag";
import log from "@/lib/logger";

import styles from "./AidpFolderTree.module.css";

export interface AidpFolderNodeTarget {
  path: string;
  name: string;
  isEmpty: boolean;
}

interface AidpFolderTreeProps {
  knowledgeBaseId: string;
  rootLabel: string;
  selectedPath: string;
  onSelect: (path: string) => void;
  /** Bump to reload every already-expanded level after a folder/file write. */
  reloadToken?: number;
  disabled?: boolean;
  onDropFiles?: (path: string, files: AidpDroppedFile[]) => void;
  /** Move selected knowledge files onto a folder node. */
  onMoveFiles?: (path: string, fileUuids: string[]) => void;
  onCreateFolder?: (parentPath: string) => void;
  onRenameFolder?: (node: AidpFolderNodeTarget) => void;
  onMoveFolder?: (node: AidpFolderNodeTarget) => void;
  onDeleteFolder?: (node: AidpFolderNodeTarget) => void;
}

const AidpFolderTree: React.FC<AidpFolderTreeProps> = ({
  knowledgeBaseId,
  rootLabel,
  selectedPath,
  onSelect,
  reloadToken = 0,
  disabled = false,
  onDropFiles,
  onMoveFiles,
  onCreateFolder,
  onRenameFolder,
  onMoveFolder,
  onDeleteFolder,
}) => {
  const { t } = useTranslation();
  const [childrenMap, setChildrenMap] = useState<
    Record<string, AidpFolderItem[]>
  >({});
  const [expandedKeys, setExpandedKeys] = useState<React.Key[]>(["/"]);
  const [loadingPaths, setLoadingPaths] = useState<Set<string>>(new Set());
  const [rootLoading, setRootLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [dropPath, setDropPath] = useState<string | null>(null);

  const childrenMapRef = useRef<Record<string, AidpFolderItem[]>>({});
  const expandedKeysRef = useRef<React.Key[]>(["/"]);
  const loadingRef = useRef(new Set<string>());
  const controllersRef = useRef(new Map<string, AbortController>());
  const requestIdRef = useRef(0);

  useEffect(() => {
    expandedKeysRef.current = expandedKeys;
  }, [expandedKeys]);

  const fetchChildren = useCallback(
    async (path: string) => {
      if (loadingRef.current.has(path)) return;
      loadingRef.current.add(path);
      setLoadingPaths((current) => new Set(current).add(path));
      const controller = new AbortController();
      controllersRef.current.set(path, controller);
      try {
        const result = await aidpKnowledgeService.getFolderTree(
          knowledgeBaseId,
          path,
          1,
          1,
          "",
          controller.signal
        );
        if (controller.signal.aborted) return;
        childrenMapRef.current = {
          ...childrenMapRef.current,
          [path]: result.folders,
        };
        setChildrenMap(childrenMapRef.current);
        setError(null);
      } catch (requestError) {
        if (controller.signal.aborted) return;
        log.error("Failed to load AIDP folder children:", {
          id: knowledgeBaseId,
          path,
          error: requestError,
        });
        setError(
          getAidpErrorMessage(
            requestError,
            t,
            t("aidpKnowledge.folderTreeLoadFailed")
          )
        );
      } finally {
        controllersRef.current.delete(path);
        loadingRef.current.delete(path);
        setLoadingPaths((current) => {
          const next = new Set(current);
          next.delete(path);
          return next;
        });
      }
    },
    [knowledgeBaseId, t]
  );

  // Reload on KB switch or after a write. Expanded levels are re-fetched so a
  // rename/move does not leave stale child paths in the tree.
  useEffect(() => {
    /* eslint-disable react-hooks/set-state-in-effect -- Reloading an external folder tree must clear the previous KB's cached levels. */
    const requestId = ++requestIdRef.current;
    controllersRef.current.forEach((controller) => controller.abort());
    controllersRef.current.clear();
    loadingRef.current.clear();
    childrenMapRef.current = {};
    setChildrenMap({});
    setError(null);
    setRootLoading(true);
    /* eslint-enable react-hooks/set-state-in-effect */
    const expanded = expandedKeysRef.current.filter((key) => key !== "/");

    void (async () => {
      await fetchChildren("/");
      if (requestId !== requestIdRef.current) return;
      setRootLoading(false);
      for (const path of expanded) {
        if (requestId !== requestIdRef.current) return;
        await fetchChildren(String(path));
      }
    })();
  }, [fetchChildren, knowledgeBaseId, reloadToken]);

  // Selecting a deep path from the table/breadcrumb must expand and load its
  // ancestors, otherwise the highlighted node is not reachable in the tree.
  useEffect(() => {
    const ancestors = folderAncestorPaths(selectedPath);
    if (ancestors.length === 0) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- Selecting a deep path expands its ancestors so the node is visible.
    setExpandedKeys((current) =>
      Array.from(new Set([...current, ...ancestors]))
    );
    void (async () => {
      for (const path of ancestors) {
        if (!(path in childrenMapRef.current)) {
          await fetchChildren(path);
        }
      }
    })();
  }, [fetchChildren, selectedPath]);

  useEffect(
    () => () => {
      requestIdRef.current += 1;
      controllersRef.current.forEach((controller) => controller.abort());
      controllersRef.current.clear();
    },
    []
  );

  const handleDrop = useCallback(
    async (event: React.DragEvent<HTMLSpanElement>, path: string) => {
      event.preventDefault();
      event.stopPropagation();
      setDropPath(null);
      const movedFileUuids = readAidpFileMoveDrag(event.dataTransfer);
      if (movedFileUuids.length > 0 && onMoveFiles) {
        onMoveFiles(path, movedFileUuids);
        return;
      }
      if (!onDropFiles) return;
      const files = await collectDroppedFiles(event.dataTransfer);
      if (files.length > 0) onDropFiles(path, files);
    },
    [onDropFiles, onMoveFiles]
  );

  const handleDragOver = useCallback(
    (event: React.DragEvent<HTMLSpanElement>, path: string) => {
      const internalMove = hasAidpFileMoveDrag(event.dataTransfer);
      if (
        !internalMove &&
        !Array.from(event.dataTransfer.types).includes("Files")
      ) {
        return;
      }
      if (internalMove && !onMoveFiles) return;
      if (!internalMove && !onDropFiles) return;
      event.preventDefault();
      event.stopPropagation();
      event.dataTransfer.dropEffect = internalMove ? "move" : "copy";
      setDropPath(path);
    },
    [onDropFiles, onMoveFiles]
  );

  const handleAction = useCallback(
    (key: string, target: AidpFolderNodeTarget) => {
      if (key === "create") onCreateFolder?.(target.path);
      if (key === "rename") onRenameFolder?.(target);
      if (key === "move") onMoveFolder?.(target);
      if (key === "delete") onDeleteFolder?.(target);
    },
    [onCreateFolder, onDeleteFolder, onMoveFolder, onRenameFolder]
  );

  const renderTitle = useCallback(
    (target: AidpFolderNodeTarget, isRoot: boolean) => {
      const menuItems: MenuProps["items"] = [];
      if (!disabled && onCreateFolder) {
        menuItems.push({
          key: "create",
          icon: <FolderAddOutlined />,
          label: t("aidpKnowledge.folderCreate"),
        });
      }
      if (!disabled && !isRoot && onRenameFolder) {
        menuItems.push({
          key: "rename",
          icon: <EditOutlined />,
          label: t("aidpKnowledge.folderRename"),
        });
      }
      if (!disabled && !isRoot && onMoveFolder) {
        menuItems.push({
          key: "move",
          icon: <FolderOpenOutlined />,
          label: t("aidpKnowledge.folderMove"),
        });
      }
      if (!disabled && !isRoot && onDeleteFolder) {
        menuItems.push({
          key: "delete",
          icon: <DeleteOutlined />,
          danger: true,
          label: t("aidpKnowledge.folderDelete"),
        });
      }

      return (
        <span
          className={`${styles.nodeTitle} ${
            dropPath === target.path ? styles.dropTarget : ""
          }`}
          data-folder-path={target.path}
          onDragOver={(event) => handleDragOver(event, target.path)}
          onDragLeave={(event) => {
            if (
              !event.currentTarget.contains(event.relatedTarget as Node | null)
            ) {
              setDropPath(null);
            }
          }}
          onDrop={(event) => void handleDrop(event, target.path)}
        >
          <Tooltip title={target.name} mouseEnterDelay={0.4}>
            <span className={styles.nodeName}>{target.name}</span>
          </Tooltip>
          {menuItems.length > 0 && (
            <Dropdown
              trigger={["click"]}
              menu={{
                items: menuItems,
                onClick: ({ key, domEvent }) => {
                  domEvent.stopPropagation();
                  handleAction(key, target);
                },
              }}
            >
              <Button
                type="text"
                size="small"
                className={styles.nodeActions}
                icon={<MoreOutlined />}
                aria-label={`${t("aidpKnowledge.moreOperations")} ${target.name}`}
                onClick={(event) => event.stopPropagation()}
              />
            </Dropdown>
          )}
        </span>
      );
    },
    [
      disabled,
      dropPath,
      handleAction,
      handleDragOver,
      handleDrop,
      onCreateFolder,
      onDeleteFolder,
      onMoveFolder,
      onRenameFolder,
      t,
    ]
  );

  const treeData = useMemo<DataNode[]>(() => {
    const renderNodes = (parentPath: string): DataNode[] => {
      const folders = childrenMap[parentPath];
      if (!folders) return [];
      return folders.map((folder) => {
        const path = joinFolderPath(parentPath, folder.folder_name);
        const target: AidpFolderNodeTarget = {
          path,
          name: folder.folder_name,
          isEmpty: folder.is_empty !== false,
        };
        const children = renderNodes(path);
        const loaded = Array.isArray(childrenMap[path]);
        return {
          key: path,
          icon: <FolderOutlined />,
          title: renderTitle(target, false),
          isLeaf: loaded ? children.length === 0 : target.isEmpty,
          children: children.length > 0 ? children : undefined,
        } satisfies DataNode;
      });
    };

    return [
      {
        key: "/",
        icon: <FolderOpenOutlined />,
        title: renderTitle(
          { path: "/", name: rootLabel, isEmpty: false },
          true
        ),
        isLeaf: false,
        children: renderNodes("/"),
      },
    ];
  }, [childrenMap, renderTitle, rootLabel]);

  // Keep normal shallow trees inside the 240px rail, but let deep levels and
  // long folder names grow the tree so the aside's horizontal scrollbar can
  // reveal them instead of squeezing the label to a few characters.
  const treeMinWidth = useMemo(() => {
    let maxDepth = 0;
    let maxNameLength = rootLabel.length;
    const walk = (parentPath: string, depth: number) => {
      for (const folder of childrenMap[parentPath] ?? []) {
        maxDepth = Math.max(maxDepth, depth + 1);
        maxNameLength = Math.max(maxNameLength, folder.folder_name.length);
        walk(joinFolderPath(parentPath, folder.folder_name), depth + 1);
      }
    };
    walk("/", 0);
    const estimatedLabelWidth = Math.min(maxNameLength, 40) * 13;
    return Math.min(
      560,
      Math.max(240, 44 + maxDepth * 24 + estimatedLabelWidth)
    );
  }, [childrenMap, rootLabel]);

  return (
    <div className={styles.container}>
      {error && (
        <div className={styles.error}>
          <span>{error}</span>
          <Button
            size="small"
            type="link"
            onClick={() => {
              setError(null);
              setRootLoading(true);
              void fetchChildren("/").finally(() => setRootLoading(false));
            }}
          >
            {t("aidpKnowledge.retry")}
          </Button>
        </div>
      )}
      {rootLoading && Object.keys(childrenMap).length === 0 ? (
        <div className={styles.loading}>
          <Spin size="small" />
        </div>
      ) : (
        <Tree
          blockNode
          showIcon
          disabled={disabled}
          treeData={treeData}
          expandedKeys={expandedKeys}
          selectedKeys={[selectedPath]}
          onExpand={(keys) => setExpandedKeys(keys)}
          onSelect={(keys) => {
            if (disabled) return;
            const path = keys[0];
            if (typeof path === "string") onSelect(path);
          }}
          loadData={(node) =>
            loadingPaths.has(String(node.key))
              ? Promise.resolve()
              : fetchChildren(String(node.key))
          }
          className={styles.tree}
          style={{ minWidth: treeMinWidth }}
        />
      )}
    </div>
  );
};

export default AidpFolderTree;
