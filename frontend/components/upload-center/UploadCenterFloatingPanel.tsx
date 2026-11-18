// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { useTranslation } from "react-i18next";

import { Button, Input, Pagination, Progress } from "antd";
import {
  CheckCircleFilled,
  ClockCircleOutlined,
  CloseCircleFilled,
  CloseOutlined,
  FileTextOutlined,
  HolderOutlined,
  LoadingOutlined,
  MinusOutlined,
  ReloadOutlined,
  UploadOutlined,
} from "@ant-design/icons";

import {
  formatUploadBytes,
  summarizeUploadFiles,
} from "@/lib/uploadCenter/batching";
import type { UploadCenterStore } from "@/lib/uploadCenter/uploadCenterStore";
import type { UploadFileRecord, UploadFileStatus } from "@/types/uploadCenter";

import styles from "./UploadCenterFloatingPanel.module.css";

interface UploadCenterFloatingPanelProps {
  store: UploadCenterStore;
}

const STATUS_META: Record<
  UploadFileStatus,
  { labelKey: string; className: string }
> = {
  queued: {
    labelKey: "uploadCenter.statusQueued",
    className: "text-gray-500",
  },
  uploading: {
    labelKey: "uploadCenter.statusUploading",
    className: "text-blue-600",
  },
  success: {
    labelKey: "uploadCenter.statusSuccess",
    className: "text-green-600",
  },
  validation_failed: {
    labelKey: "uploadCenter.statusValidationFailed",
    className: "text-red-500",
  },
  upload_failed: {
    labelKey: "uploadCenter.statusUploadFailed",
    className: "text-red-500",
  },
};

const StatusIcon: React.FC<{ status: UploadFileStatus }> = ({ status }) => {
  if (status === "success") {
    return <CheckCircleFilled className="text-green-500" />;
  }
  if (status === "uploading") {
    return <LoadingOutlined className="text-blue-500" />;
  }
  if (status === "validation_failed" || status === "upload_failed") {
    return <CloseCircleFilled className="text-red-500" />;
  }
  return <ClockCircleOutlined className="text-gray-400" />;
};

const PAGE_SIZE_OPTIONS = [10, 20, 50];
const VIEWPORT_MARGIN = 8;
const DRAG_THRESHOLD = 4;

interface FloatingPosition {
  left: number;
  top: number;
}

interface DragState {
  pointerId: number;
  startX: number;
  startY: number;
  originLeft: number;
  originTop: number;
  moved: boolean;
}

const UploadCenterFloatingPanel: React.FC<UploadCenterFloatingPanelProps> = ({
  store,
}) => {
  const { t } = useTranslation();
  const snapshot = useSyncExternalStore(
    store.subscribe,
    store.getSnapshot,
    store.getSnapshot
  );
  const [minimized, setMinimized] = useState(false);
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [position, setPosition] = useState<FloatingPosition | null>(null);
  const [dragging, setDragging] = useState(false);
  const previousTotalRef = useRef(0);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const dragRef = useRef<DragState | null>(null);
  const suppressPillClickRef = useRef(false);

  const summary = useMemo(
    () =>
      summarizeUploadFiles(
        snapshot.files,
        snapshot.fileOrder,
        snapshot.batches
      ),
    [snapshot]
  );

  useEffect(() => {
    /* eslint-disable react-hooks/set-state-in-effect -- New uploads must reveal the panel; closing resets the previous search. */
    if (summary.total === 0) {
      setSearch("");
      setPage(1);
      setMinimized(false);
    } else if (summary.total > previousTotalRef.current) {
      setMinimized(false);
    }
    /* eslint-enable react-hooks/set-state-in-effect */
    previousTotalRef.current = summary.total;
  }, [summary.total]);

  const clampPosition = useCallback(
    (left: number, top: number): FloatingPosition => {
      const element = panelRef.current;
      if (!element) return { left, top };
      const rect = element.getBoundingClientRect();
      const maxLeft = Math.max(
        VIEWPORT_MARGIN,
        window.innerWidth - rect.width - VIEWPORT_MARGIN
      );
      const maxTop = Math.max(
        VIEWPORT_MARGIN,
        window.innerHeight - rect.height - VIEWPORT_MARGIN
      );
      return {
        left: Math.min(Math.max(VIEWPORT_MARGIN, left), maxLeft),
        top: Math.min(Math.max(VIEWPORT_MARGIN, top), maxTop),
      };
    },
    []
  );

  const beginDrag = useCallback(
    (event: ReactPointerEvent<HTMLElement>, suppressClickOnDrag = false) => {
      if (event.button !== 0) return;
      const target = event.target as HTMLElement;
      if (
        target.closest(
          "button, a, input, textarea, select, [contenteditable='true']"
        )
      ) {
        return;
      }
      const element = panelRef.current;
      if (!element) return;

      const rect = element.getBoundingClientRect();
      suppressPillClickRef.current = false;
      dragRef.current = {
        pointerId: event.pointerId,
        startX: event.clientX,
        startY: event.clientY,
        originLeft: rect.left,
        originTop: rect.top,
        moved: false,
      };
      setPosition({ left: rect.left, top: rect.top });
      setDragging(true);
      event.preventDefault();

      const previousUserSelect = document.body.style.userSelect;
      document.body.style.userSelect = "none";

      const handleMove = (moveEvent: PointerEvent) => {
        const drag = dragRef.current;
        if (!drag || moveEvent.pointerId !== drag.pointerId) return;
        const dx = moveEvent.clientX - drag.startX;
        const dy = moveEvent.clientY - drag.startY;
        if (!drag.moved && Math.hypot(dx, dy) >= DRAG_THRESHOLD) {
          drag.moved = true;
        }
        setPosition(clampPosition(drag.originLeft + dx, drag.originTop + dy));
      };

      const finish = () => {
        const drag = dragRef.current;
        dragRef.current = null;
        setDragging(false);
        document.body.style.userSelect = previousUserSelect;
        window.removeEventListener("pointermove", handleMove);
        window.removeEventListener("pointerup", finish);
        window.removeEventListener("pointercancel", finish);
        if (drag?.moved && suppressClickOnDrag) {
          suppressPillClickRef.current = true;
        }
      };

      window.addEventListener("pointermove", handleMove);
      window.addEventListener("pointerup", finish);
      window.addEventListener("pointercancel", finish);
    },
    [clampPosition]
  );

  useEffect(() => {
    const handleResize = () =>
      setPosition((current) =>
        current ? clampPosition(current.left, current.top) : current
      );
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, [clampPosition]);

  useEffect(() => {
    /* eslint-disable-next-line react-hooks/set-state-in-effect -- The panel size changes when minimizing/expanding; clamp the persisted position after layout. */
    setPosition((current) =>
      current ? clampPosition(current.left, current.top) : current
    );
  }, [minimized, clampPosition]);

  const filteredFiles = useMemo(() => {
    const term = search.trim().toLowerCase();
    const files = snapshot.fileOrder
      .map((id) => snapshot.files[id])
      .filter((file): file is UploadFileRecord => Boolean(file));
    if (!term) return files;
    return files.filter((file) =>
      `${file.relativePath} ${file.name} ${file.context.targetFolder ?? ""}`
        .toLowerCase()
        .includes(term)
    );
  }, [search, snapshot.files, snapshot.fileOrder]);

  const pageCount = Math.max(1, Math.ceil(filteredFiles.length / pageSize));
  const currentPage = Math.min(page, pageCount);
  const visibleFiles = filteredFiles.slice(
    (currentPage - 1) * pageSize,
    currentPage * pageSize
  );

  if (summary.total === 0) return null;

  const failedCount = summary.validationFailed + summary.uploadFailed;
  const errorText = (file: UploadFileRecord): string => {
    if (file.error) {
      return file.error.startsWith("uploadCenter.")
        ? t(file.error)
        : file.error;
    }
    if (file.errorKey) {
      return t(file.errorKey, file.errorParams);
    }
    return "";
  };

  const floatingStyle: React.CSSProperties | undefined = position
    ? {
        left: `${position.left}px`,
        top: `${position.top}px`,
        right: "auto",
        bottom: "auto",
      }
    : undefined;

  if (minimized) {
    return (
      <div
        ref={panelRef}
        role="button"
        tabIndex={0}
        className={`${styles.minimized} ${dragging ? styles.dragging : ""}`}
        style={floatingStyle}
        onPointerDown={(event) => beginDrag(event, true)}
        onClick={() => {
          if (suppressPillClickRef.current) {
            suppressPillClickRef.current = false;
            return;
          }
          setMinimized(false);
        }}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            setMinimized(false);
          }
        }}
        aria-label={t("uploadCenter.expand")}
      >
        <span className={styles.minimizedIcon}>
          <UploadOutlined />
        </span>
        <span className={styles.minimizedText}>
          <span>
            {summary.active > 0
              ? t("uploadCenter.uploadingCount", {
                  count: summary.active,
                })
              : t("uploadCenter.completed")}
          </span>
          <span className={styles.minimizedMeta}>
            {t("uploadCenter.successFailed", {
              success: summary.success,
              failed: failedCount,
            })}
          </span>
        </span>
        <Progress
          type="circle"
          size={32}
          percent={summary.percent}
          showInfo={false}
          strokeColor="#1677ff"
        />
      </div>
    );
  }

  return (
    <section
      ref={panelRef}
      className={styles.panel}
      style={floatingStyle}
      aria-label={t("uploadCenter.title")}
    >
      <header
        className={`${styles.header} ${dragging ? styles.dragging : ""}`}
        onPointerDown={beginDrag}
      >
        <div className={styles.headerTitle}>
          <HolderOutlined className="text-gray-400" aria-hidden="true" />
          <UploadOutlined className="text-blue-600" />
          <span>{t("uploadCenter.title")}</span>
        </div>
        <div className={styles.headerActions}>
          <Button
            type="text"
            size="small"
            icon={<MinusOutlined />}
            aria-label={t("uploadCenter.minimize")}
            onClick={() => setMinimized(true)}
          />
          {summary.canClose && (
            <Button
              type="text"
              size="small"
              icon={<CloseOutlined />}
              aria-label={t("uploadCenter.close")}
              onClick={() => store.close()}
            />
          )}
        </div>
      </header>

      <div className={styles.summary} aria-live="polite">
        {summary.active > 0 && (
          <span>
            {t("uploadCenter.uploadingCount", { count: summary.active })}
          </span>
        )}
        <span className="text-green-600">
          {t("uploadCenter.successCount", { count: summary.success })}
        </span>
        <span className="text-red-500">
          {t("uploadCenter.failedCount", { count: failedCount })}
        </span>
      </div>

      <div className={styles.progressRow}>
        <Progress
          percent={summary.percent}
          showInfo={false}
          size="small"
          strokeColor="#1677ff"
        />
        <span className={styles.percent}>{summary.percent}%</span>
      </div>

      <div className={styles.searchRow}>
        <Input
          allowClear
          size="small"
          value={search}
          onChange={(event) => {
            setSearch(event.target.value);
            setPage(1);
          }}
          placeholder={t("uploadCenter.searchPlaceholder")}
        />
        <span className={styles.filteredCount}>
          {t("uploadCenter.fileCount", {
            filtered: filteredFiles.length,
            total: summary.total,
          })}
        </span>
      </div>

      <div className={styles.fileList}>
        {visibleFiles.length === 0 ? (
          <div className={styles.empty}>{t("uploadCenter.noMatches")}</div>
        ) : (
          visibleFiles.map((file) => {
            const meta = STATUS_META[file.status];
            const error = errorText(file);
            return (
              <div className={styles.fileRow} key={file.id}>
                <FileTextOutlined className={styles.fileIcon} />
                <div className={styles.fileText}>
                  <div className={styles.fileName} title={file.relativePath}>
                    {file.relativePath}
                  </div>
                  <div className={styles.fileMeta}>
                    {file.context.targetFolder
                      ? t("uploadCenter.targetPath", {
                          path: file.context.targetFolder,
                        })
                      : file.context.knowledgeBaseName}
                    {" · "}
                    {formatUploadBytes(file.size)}
                  </div>
                  {error && (
                    <div className={styles.fileError} title={error}>
                      {file.status === "validation_failed"
                        ? t("uploadCenter.validationRetryHint", {
                            reason: error,
                          })
                        : error}
                    </div>
                  )}
                </div>
                <span className={`${styles.status} ${meta.className}`}>
                  <StatusIcon status={file.status} />
                  {t(meta.labelKey)}
                </span>
              </div>
            );
          })
        )}
      </div>

      <div className={styles.footer}>
        <Pagination
          size="small"
          current={currentPage}
          pageSize={pageSize}
          total={filteredFiles.length}
          showSizeChanger
          pageSizeOptions={PAGE_SIZE_OPTIONS}
          onChange={(nextPage, nextPageSize) => {
            setPage(nextPageSize !== pageSize ? 1 : nextPage);
            setPageSize(nextPageSize);
          }}
        />
        <div className={styles.footerActions}>
          {summary.retryableFailed > 0 && (
            <Button
              size="small"
              icon={<ReloadOutlined />}
              onClick={() => store.retryFailed()}
            >
              {t("uploadCenter.retryFailed", {
                count: summary.retryableFailed,
              })}
            </Button>
          )}
        </div>
      </div>

      <div className={styles.refreshHint}>{t("uploadCenter.refreshHint")}</div>
    </section>
  );
};

export default UploadCenterFloatingPanel;
