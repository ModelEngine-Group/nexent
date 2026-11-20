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

import { Button, Input, Pagination } from "antd";
import {
  ArrowUpOutlined,
  CheckCircleFilled,
  ClockCircleOutlined,
  CloseCircleFilled,
  CloseOutlined,
  DownOutlined,
  FileTextOutlined,
  InfoCircleOutlined,
  LoadingOutlined,
  ReloadOutlined,
  SearchOutlined,
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
  { labelKey: string; tone: string }
> = {
  queued: {
    labelKey: "uploadCenter.statusQueued",
    tone: styles.statusQueued,
  },
  uploading: {
    labelKey: "uploadCenter.statusUploading",
    tone: styles.statusUploading,
  },
  success: {
    labelKey: "uploadCenter.statusSuccess",
    tone: styles.statusSuccess,
  },
  validation_failed: {
    labelKey: "uploadCenter.statusValidationFailed",
    tone: styles.statusFailed,
  },
  upload_failed: {
    labelKey: "uploadCenter.statusUploadFailed",
    tone: styles.statusFailed,
  },
};

const StatusIcon: React.FC<{ status: UploadFileStatus }> = ({ status }) => {
  if (status === "success") {
    return <CheckCircleFilled />;
  }
  if (status === "uploading") {
    return <LoadingOutlined />;
  }
  if (status === "validation_failed" || status === "upload_failed") {
    return <CloseCircleFilled />;
  }
  return <ClockCircleOutlined />;
};

const PAGE_SIZE_OPTIONS = [10, 20, 50];
const VIEWPORT_MARGIN = 8;
const DRAG_THRESHOLD = 4;
const RING_COLOR = "#087c56";
const RING_TRACK = "#dff6ec";

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
  const [failedOnly, setFailedOnly] = useState(false);
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
  const failedCount = summary.validationFailed + summary.uploadFailed;
  const showingFailed = failedOnly && failedCount > 0;

  useEffect(() => {
    /* eslint-disable react-hooks/set-state-in-effect -- New uploads must reveal the panel; closing resets the filters. */
    if (summary.total === 0) {
      setSearch("");
      setFailedOnly(false);
      setPage(1);
      setMinimized(false);
    } else if (summary.total > previousTotalRef.current) {
      setMinimized(false);
      setFailedOnly(false);
      setPage(1);
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
    let files = snapshot.fileOrder
      .map((id) => snapshot.files[id])
      .filter((file): file is UploadFileRecord => Boolean(file));
    if (showingFailed) {
      files = files.filter(
        (file) =>
          file.status === "validation_failed" || file.status === "upload_failed"
      );
    }
    if (!term) return files;
    return files.filter((file) =>
      `${file.relativePath} ${file.name} ${file.context.knowledgeBaseName} ${
        file.context.targetFolder ?? ""
      }`
        .toLowerCase()
        .includes(term)
    );
  }, [search, showingFailed, snapshot.files, snapshot.fileOrder]);

  const pageCount = Math.max(1, Math.ceil(filteredFiles.length / pageSize));
  const currentPage = Math.min(page, pageCount);
  const visibleFiles = filteredFiles.slice(
    (currentPage - 1) * pageSize,
    currentPage * pageSize
  );

  if (summary.total === 0) return null;

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

  const processedCount = Math.max(0, summary.total - summary.active);
  const loadedBytes = Math.min(summary.processedBytes, summary.totalBytes);
  const headline =
    summary.active > 0
      ? t("uploadCenter.uploadingHeadline", {
          processed: processedCount,
          total: summary.total,
        })
      : t("uploadCenter.finishedHeadline", {
          processed: processedCount,
          total: summary.total,
        });
  const ringBackground = `conic-gradient(${RING_COLOR} ${summary.percent}%, ${RING_TRACK} 0)`;
  const floatingStyle: React.CSSProperties | undefined = position
    ? {
        left: `${position.left}px`,
        top: `${position.top}px`,
        right: "auto",
        bottom: "auto",
      }
    : undefined;
  const expandedLabel =
    failedCount > 0
      ? t("uploadCenter.expandProgressFailed", {
          percent: summary.percent,
          count: failedCount,
        })
      : t("uploadCenter.expandProgress", { percent: summary.percent });

  if (minimized) {
    return (
      <div
        ref={panelRef}
        role="button"
        tabIndex={0}
        className={`${styles.ball} ${dragging ? styles.dragging : ""}`}
        style={{ ...floatingStyle, background: ringBackground }}
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
        aria-label={expandedLabel}
      >
        <span className={styles.ballInner} aria-hidden="true">
          <ArrowUpOutlined />
        </span>
        {failedCount > 0 && (
          <span className={styles.failureDot} aria-hidden="true" />
        )}
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
        <span
          className={styles.ring}
          style={{ background: ringBackground }}
          aria-hidden="true"
        >
          <span className={styles.ringInner}>
            <ArrowUpOutlined />
          </span>
        </span>
        <div className={styles.heading}>
          <strong>{headline}</strong>
          <span className={styles.headingMeta}>
            {formatUploadBytes(loadedBytes)} /{" "}
            {formatUploadBytes(summary.totalBytes)}
          </span>
        </div>
        <div className={styles.headerActions}>
          <Button
            type="text"
            size="small"
            icon={<DownOutlined />}
            aria-label={t("uploadCenter.collapse")}
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

      <div className={styles.summary}>
        <div
          className={styles.track}
          role="progressbar"
          aria-label={t("uploadCenter.progressLabel")}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={summary.percent}
        >
          <span
            className={styles.trackFill}
            style={{ width: `${summary.percent}%` }}
          />
        </div>
        <div className={styles.counts}>
          <span className={`${styles.count} ${styles.statusSuccess}`}>
            <i className={styles.dot} aria-hidden="true" />
            {t("uploadCenter.successCount", { count: summary.success })}
          </span>
          <span className={`${styles.count} ${styles.statusUploading}`}>
            <i className={styles.dot} aria-hidden="true" />
            {t("uploadCenter.uploadingCount", { count: summary.uploading })}
          </span>
          <span className={`${styles.count} ${styles.statusQueued}`}>
            <i className={styles.dot} aria-hidden="true" />
            {t("uploadCenter.queuedCount", { count: summary.queued })}
          </span>
          <span className={`${styles.count} ${styles.statusFailed}`}>
            <i className={styles.dot} aria-hidden="true" />
            {t("uploadCenter.failedCount", { count: failedCount })}
          </span>
        </div>
      </div>

      <div className={styles.body}>
        {summary.active > 0 && (
          <div className={styles.note}>
            <InfoCircleOutlined aria-hidden="true" />
            <span>{t("uploadCenter.refreshHintShort")}</span>
          </div>
        )}

        <div className={styles.tabs}>
          <button
            type="button"
            className={`${styles.tab} ${!showingFailed ? styles.tabActive : ""}`}
            aria-pressed={!showingFailed}
            onClick={() => {
              setFailedOnly(false);
              setPage(1);
            }}
          >
            {t("uploadCenter.filterAll", { count: summary.total })}
          </button>
          <button
            type="button"
            className={`${styles.tab} ${showingFailed ? styles.tabActive : ""}`}
            aria-pressed={showingFailed}
            disabled={failedCount === 0}
            onClick={() => {
              setFailedOnly(true);
              setPage(1);
            }}
          >
            {t("uploadCenter.filterUnsuccessful", { count: failedCount })}
          </button>
        </div>

        <div className={styles.searchRow}>
          <Input
            allowClear
            size="small"
            prefix={<SearchOutlined className="text-gray-400" />}
            value={search}
            onChange={(event) => {
              setSearch(event.target.value);
              setPage(1);
            }}
            placeholder={t("uploadCenter.searchPlaceholder")}
          />
        </div>

        <div className={styles.fileList}>
          {visibleFiles.length === 0 ? (
            <div className={styles.empty}>{t("uploadCenter.noMatches")}</div>
          ) : (
            visibleFiles.map((file) => {
              const meta = STATUS_META[file.status];
              const error = errorText(file);
              const statusLabel = t(meta.labelKey);
              return (
                <div className={styles.fileRow} key={file.id}>
                  <span className={styles.fileIcon} aria-hidden="true">
                    <FileTextOutlined />
                  </span>
                  <div className={styles.fileText}>
                    <div className={styles.fileName} title={file.relativePath}>
                      {file.relativePath}
                    </div>
                    <div
                      className={styles.fileMeta}
                      title={`${statusLabel} · ${file.context.knowledgeBaseName}${
                        file.context.targetFolder
                          ? ` · ${t("uploadCenter.targetPath", {
                              path: file.context.targetFolder,
                            })}`
                          : ""
                      } · ${formatUploadBytes(file.size)}`}
                    >
                      <span className={`${styles.fileStatus} ${meta.tone}`}>
                        {statusLabel}
                      </span>
                      {" · "}
                      {file.context.knowledgeBaseName}
                      {file.context.targetFolder && (
                        <>
                          {" · "}
                          {t("uploadCenter.targetPath", {
                            path: file.context.targetFolder,
                          })}
                        </>
                      )}
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
                  <span
                    className={`${styles.fileStatusIcon} ${meta.tone}`}
                    title={statusLabel}
                    aria-label={statusLabel}
                  >
                    <StatusIcon status={file.status} />
                  </span>
                </div>
              );
            })
          )}
        </div>

        {filteredFiles.length > pageSize && (
          <div className={styles.pagerRow}>
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
          </div>
        )}
      </div>

      {summary.retryableFailed > 0 && (
        <div className={styles.footer}>
          <Button
            type="text"
            size="small"
            className={styles.retry}
            icon={<ReloadOutlined />}
            onClick={() => {
              setFailedOnly(false);
              setPage(1);
              store.retryFailed();
            }}
          >
            {t("uploadCenter.retryFailed", {
              count: summary.retryableFailed,
            })}
          </Button>
        </div>
      )}
    </section>
  );
};

export default UploadCenterFloatingPanel;
