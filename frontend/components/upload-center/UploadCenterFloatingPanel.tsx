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
import { useRouter } from "next/navigation";

import { Button } from "antd";
import {
  ArrowUpOutlined,
  CheckOutlined,
  CloseOutlined,
  DownOutlined,
  ReloadOutlined,
} from "@ant-design/icons";

import UploadFileIcon from "@/components/upload-center/UploadFileIcon";
import { summarizeUploadFiles } from "@/lib/uploadCenter/batching";
import type { UploadCenterStore } from "@/lib/uploadCenter/uploadCenterStore";
import type { UploadFileRecord, UploadFileStatus } from "@/types/uploadCenter";

import styles from "./UploadCenterFloatingPanel.module.css";

interface UploadCenterFloatingPanelProps {
  store: UploadCenterStore;
}

type PanelState = "active" | "success" | "failed" | "partial";
type FileTab = "all" | "failed" | "uploading" | "success";

const VIEWPORT_MARGIN = 8;
const DRAG_THRESHOLD = 4;
const BALL_SIZE = 44;
const ACTIVE_COLOR = "#1677ff";
const ACTIVE_TRACK = "#e8f1ff";
const SUCCESS_COLOR = "#12b76a";
const FAILED_COLOR = "#b42318";

const STATUS_LABEL_KEY: Record<UploadFileStatus, string> = {
  queued: "uploadCenter.statusQueued",
  uploading: "uploadCenter.statusUploading",
  success: "uploadCenter.statusSuccess",
  validation_failed: "uploadCenter.statusValidationFailed",
  upload_failed: "uploadCenter.statusUploadFailed",
  cancelled: "uploadCenter.statusCancelled",
};

const isFailedStatus = (status: UploadFileStatus): boolean =>
  status === "validation_failed" ||
  status === "upload_failed" ||
  status === "cancelled";

const isActiveStatus = (status: UploadFileStatus): boolean =>
  status === "queued" || status === "uploading";

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

interface ProgressSample {
  time: number;
  bytes: number;
}

const UploadCenterFloatingPanel: React.FC<UploadCenterFloatingPanelProps> = ({
  store,
}) => {
  const { t } = useTranslation();
  const router = useRouter();
  const snapshot = useSyncExternalStore(
    store.subscribe,
    store.getSnapshot,
    store.getSnapshot
  );
  const [minimized, setMinimized] = useState(false);
  const [tab, setTab] = useState<FileTab>("all");
  const [warningDismissed, setWarningDismissed] = useState(false);
  const [finishedDismissed, setFinishedDismissed] = useState(false);
  const [etaMinutes, setEtaMinutes] = useState<number | null>(null);
  const [expandedPosition, setExpandedPosition] =
    useState<FloatingPosition | null>(null);
  const [collapsedPosition, setCollapsedPosition] =
    useState<FloatingPosition | null>(null);
  const [dragging, setDragging] = useState(false);
  const previousTotalRef = useRef(0);
  const progressSamplesRef = useRef<ProgressSample[]>([]);
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
  const failedCount =
    summary.validationFailed + summary.uploadFailed + summary.cancelled;
  const activeCount = summary.uploading + summary.queued;
  const processedCount = Math.max(0, summary.total - activeCount);
  const allFinished = activeCount === 0;
  const panelState: PanelState =
    allFinished && summary.total > 0 && summary.success === summary.total
      ? "success"
      : allFinished &&
          summary.total > 0 &&
          summary.success === 0 &&
          failedCount === summary.total
        ? "failed"
        : allFinished && summary.success > 0 && failedCount > 0
          ? "partial"
          : "active";

  useEffect(() => {
    /* eslint-disable react-hooks/set-state-in-effect -- New uploads must reveal the panel and reset its view state. */
    if (summary.total === 0) {
      setTab("all");
      setWarningDismissed(false);
      setFinishedDismissed(false);
      setMinimized(false);
      progressSamplesRef.current = [];
      setEtaMinutes(null);
    } else if (summary.total > previousTotalRef.current) {
      setMinimized(false);
      setTab("all");
      setWarningDismissed(false);
      setFinishedDismissed(false);
      progressSamplesRef.current = [];
      setEtaMinutes(null);
    }
    /* eslint-enable react-hooks/set-state-in-effect */
    previousTotalRef.current = summary.total;
  }, [summary.total]);

  useEffect(() => {
    /* eslint-disable react-hooks/set-state-in-effect -- ETA samples are updated only when progress changes. */
    if (activeCount === 0) {
      progressSamplesRef.current = [];
      setEtaMinutes(null);
      return;
    }

    const now = Date.now();
    const samples = progressSamplesRef.current;
    samples.push({ time: now, bytes: summary.processedBytes });
    while (samples.length > 2 && now - samples[0].time > 10_000) {
      samples.shift();
    }

    const first = samples[0];
    const last = samples[samples.length - 1];
    const elapsedSeconds = (last.time - first.time) / 1000;
    if (samples.length < 2 || elapsedSeconds < 3) return;

    const bytesPerSecond = (last.bytes - first.bytes) / elapsedSeconds;
    const remainingBytes = Math.max(
      0,
      summary.totalBytes - summary.processedBytes
    );
    if (remainingBytes <= 0) {
      setEtaMinutes(0);
      return;
    }
    if (bytesPerSecond <= 0) return;
    setEtaMinutes(Math.max(1, Math.ceil(remainingBytes / bytesPerSecond / 60)));
    /* eslint-enable react-hooks/set-state-in-effect */
  }, [activeCount, summary.processedBytes, summary.totalBytes]);

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
    (
      event: ReactPointerEvent<HTMLElement>,
      setPosition: React.Dispatch<
        React.SetStateAction<FloatingPosition | null>
      >,
      suppressClickOnDrag = false
    ) => {
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
        if (drag.moved) {
          setPosition(clampPosition(drag.originLeft + dx, drag.originTop + dy));
        }
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
    const setPosition = minimized ? setCollapsedPosition : setExpandedPosition;
    const handleResize = () =>
      setPosition((current) =>
        current ? clampPosition(current.left, current.top) : current
      );
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, [clampPosition, minimized]);

  useEffect(() => {
    const setPosition = minimized ? setCollapsedPosition : setExpandedPosition;
    /* eslint-disable-next-line react-hooks/set-state-in-effect -- The panel size changes when minimizing/expanding; clamp the active position after layout. */
    setPosition((current) =>
      current ? clampPosition(current.left, current.top) : current
    );
  }, [minimized, clampPosition]);

  const collapsePanel = useCallback(() => {
    const element = panelRef.current;
    if (element && !collapsedPosition) {
      const rect = element.getBoundingClientRect();
      const maxLeft = Math.max(
        VIEWPORT_MARGIN,
        window.innerWidth - BALL_SIZE - VIEWPORT_MARGIN
      );
      const maxTop = Math.max(
        VIEWPORT_MARGIN,
        window.innerHeight - BALL_SIZE - VIEWPORT_MARGIN
      );
      setCollapsedPosition({
        left: Math.min(
          Math.max(VIEWPORT_MARGIN, rect.right - BALL_SIZE),
          maxLeft
        ),
        top: Math.min(
          Math.max(VIEWPORT_MARGIN, rect.bottom - BALL_SIZE),
          maxTop
        ),
      });
    }
    setMinimized(true);
  }, [collapsedPosition]);

  const filteredFiles = useMemo(() => {
    const files = snapshot.fileOrder
      .map((id) => snapshot.files[id])
      .filter((file): file is UploadFileRecord => Boolean(file));
    if (tab === "failed")
      return files.filter((file) => isFailedStatus(file.status));
    if (tab === "uploading") {
      return files.filter((file) => isActiveStatus(file.status));
    }
    if (tab === "success") {
      return files.filter((file) => file.status === "success");
    }
    return files;
  }, [snapshot.files, snapshot.fileOrder, tab]);

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

  const etaText =
    etaMinutes === null
      ? t("uploadCenter.etaCalculating")
      : etaMinutes <= 0
        ? t("uploadCenter.etaAlmostDone")
        : etaMinutes <= 1
          ? t("uploadCenter.etaLessThanMinute")
          : t("uploadCenter.etaMinutes", { minutes: etaMinutes });
  const headline =
    panelState === "active"
      ? t("uploadCenter.importingHeadline", {
          processed: processedCount,
          total: summary.total,
          eta: etaText,
        })
      : panelState === "success"
        ? t("uploadCenter.successHeadline", {
            success: summary.success,
            total: summary.total,
          })
        : panelState === "failed"
          ? summary.cancelled === summary.total
            ? t("uploadCenter.cancelledHeadline", { total: summary.total })
            : t("uploadCenter.failedHeadline", {
                success: summary.success,
                total: summary.total,
              })
          : t("uploadCenter.partialHeadline", {
              success: summary.success,
              total: summary.total,
            });

  const successPercent = summary.total
    ? (summary.success / summary.total) * 100
    : 0;
  const ringBackground =
    panelState === "active"
      ? `conic-gradient(${ACTIVE_COLOR} ${summary.percent}%, ${ACTIVE_TRACK} 0)`
      : panelState === "partial"
        ? `conic-gradient(${SUCCESS_COLOR} 0 ${successPercent}%, ${FAILED_COLOR} ${successPercent}% 100%)`
        : panelState === "success"
          ? SUCCESS_COLOR
          : FAILED_COLOR;
  const activePosition = minimized ? collapsedPosition : expandedPosition;
  const floatingStyle: React.CSSProperties | undefined = activePosition
    ? {
        left: `${activePosition.left}px`,
        top: `${activePosition.top}px`,
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

  const barSegments = [
    {
      key: "success",
      count: summary.success,
      className: styles.segmentSuccess,
    },
    { key: "failed", count: failedCount, className: styles.segmentFailed },
    {
      key: "uploading",
      count: summary.uploading,
      className: styles.segmentUploading,
    },
    { key: "queued", count: summary.queued, className: styles.segmentQueued },
  ].filter((segment) => segment.count > 0);

  const tabs: Array<{ key: FileTab; label: string; count: number }> = [
    { key: "all", label: t("uploadCenter.tabAll"), count: summary.total },
    { key: "failed", label: t("uploadCenter.tabFailed"), count: failedCount },
    {
      key: "uploading",
      label: t("uploadCenter.tabUploading"),
      count: activeCount,
    },
    {
      key: "success",
      label: t("uploadCenter.tabSuccess"),
      count: summary.success,
    },
  ];

  const openUploadTasks = () => {
    const currentKb = new URLSearchParams(window.location.search).get("kb");
    const latestFile = [...snapshot.fileOrder]
      .reverse()
      .map((id) => snapshot.files[id])
      .find((file): file is UploadFileRecord => Boolean(file));
    const kbId = currentKb || latestFile?.context.knowledgeBaseId;
    if (!kbId) return;
    const locale = window.location.pathname.split("/")[1] || "zh";
    router.push(
      `/${locale}/knowledges/detail?kb=${encodeURIComponent(kbId)}&tab=tasks`
    );
  };

  if (minimized) {
    return (
      <div
        ref={panelRef}
        role="button"
        tabIndex={0}
        className={`${styles.ball} ${dragging ? styles.dragging : ""}`}
        style={{ ...floatingStyle, background: ringBackground }}
        onPointerDown={(event) => beginDrag(event, setCollapsedPosition, true)}
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
        onPointerDown={(event) => beginDrag(event, setExpandedPosition)}
      >
        <div className={styles.overview}>
          <span
            className={`${styles.stateRing} ${
              panelState === "success"
                ? styles.stateRingSuccess
                : panelState === "failed"
                  ? styles.stateRingFailed
                  : panelState === "partial"
                    ? styles.stateRingPartial
                    : styles.stateRingActive
            }`}
            style={{ background: ringBackground }}
            aria-hidden="true"
          >
            <span className={styles.stateRingInner}>
              {panelState === "active" && (
                <span className={styles.ringPercent}>{summary.percent}%</span>
              )}
              {panelState === "success" && (
                <CheckOutlined className={styles.ringSuccessIcon} />
              )}
              {panelState === "failed" && (
                <CloseOutlined className={styles.ringFailedIcon} />
              )}
            </span>
          </span>

          <div className={styles.heading}>
            <strong className={styles.headline}>{headline}</strong>
            <div className={styles.headerLinks}>
              {panelState === "active" && (
                <button
                  type="button"
                  className={styles.actionLink}
                  disabled={snapshot.cancelling}
                  onClick={() => store.cancelAll()}
                >
                  {snapshot.cancelling
                    ? t("uploadCenter.cancelling")
                    : t("uploadCenter.cancelTask")}
                </button>
              )}
              {(panelState === "active" ||
                panelState === "failed" ||
                panelState === "partial") &&
                failedCount > 0 && (
                  <button
                    type="button"
                    className={styles.actionLink}
                    disabled={summary.retryableFailed === 0}
                    aria-label={t("uploadCenter.retryFailed", {
                      count: summary.retryableFailed,
                    })}
                    onClick={() => store.retryFailed()}
                  >
                    {t("uploadCenter.retryAction")}
                  </button>
                )}
            </div>
          </div>

          <div className={styles.headerActions}>
            <Button
              type="text"
              size="small"
              icon={<DownOutlined />}
              aria-label={t("uploadCenter.collapse")}
              onClick={collapsePanel}
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
        </div>

        <div
          className={styles.stateBar}
          role="img"
          aria-label={t("uploadCenter.stateBarLabel")}
        >
          {barSegments.map((segment) => (
            <span
              key={segment.key}
              className={`${styles.stateSegment} ${segment.className}`}
              style={{ width: `${(segment.count / summary.total) * 100}%` }}
            />
          ))}
        </div>
      </header>

      <div className={styles.body}>
        {panelState === "active" && !warningDismissed && (
          <div className={styles.warningBanner}>
            <span>{t("uploadCenter.activeWarning")}</span>
            <button
              type="button"
              className={styles.bannerClose}
              aria-label={t("uploadCenter.dismissHint")}
              onClick={() => setWarningDismissed(true)}
            >
              <CloseOutlined />
            </button>
          </div>
        )}
        {panelState !== "active" && !finishedDismissed && (
          <div className={styles.infoBanner}>
            <span>
              {t("uploadCenter.finishedHintBefore")}
              <button
                type="button"
                className={styles.bannerLink}
                onClick={openUploadTasks}
              >
                {t("uploadCenter.uploadTasks")}
              </button>
              {t("uploadCenter.finishedHintAfter")}
            </span>
            <button
              type="button"
              className={styles.bannerClose}
              aria-label={t("uploadCenter.dismissHint")}
              onClick={() => setFinishedDismissed(true)}
            >
              <CloseOutlined />
            </button>
          </div>
        )}

        <div className={styles.tabs} role="tablist">
          {tabs.map((item) => (
            <button
              key={item.key}
              type="button"
              role="tab"
              aria-selected={tab === item.key}
              className={`${styles.tab} ${
                tab === item.key ? styles.tabActive : ""
              }`}
              onClick={() => setTab(item.key)}
            >
              <span>{item.label}</span>
              <span className={styles.tabCount}>{item.count}</span>
            </button>
          ))}
        </div>

        <div className={styles.fileList}>
          {filteredFiles.length === 0 ? (
            <div className={styles.empty}>{t("uploadCenter.tabEmpty")}</div>
          ) : (
            filteredFiles.map((file) => {
              const failed = isFailedStatus(file.status);
              const retryable = file.retryable !== false;
              const error = errorText(file);
              const statusLabel = t(STATUS_LABEL_KEY[file.status]);
              return (
                <div className={styles.fileRow} key={file.id}>
                  <UploadFileIcon />
                  <div className={styles.fileText}>
                    <div
                      className={styles.fileName}
                      title={`${file.relativePath} · ${file.context.knowledgeBaseName}${
                        file.context.targetFolder
                          ? ` · ${file.context.targetFolder}`
                          : ""
                      }`}
                    >
                      {file.name}
                    </div>
                    {error && (
                      <div className={styles.fileError} title={error}>
                        {error}
                      </div>
                    )}
                    <span className={styles.srOnly}>{statusLabel}</span>
                  </div>
                  <div className={styles.fileAction}>
                    {failed ? (
                      <>
                        <span
                          className={styles.failureDotInline}
                          aria-hidden="true"
                        />
                        <button
                          type="button"
                          className={styles.rowRetry}
                          disabled={!retryable}
                          aria-label={t("uploadCenter.retryFile", {
                            name: file.name,
                          })}
                          title={
                            retryable
                              ? t("uploadCenter.retryFile", {
                                  name: file.name,
                                })
                              : t("uploadCenter.retryUnavailable")
                          }
                          onClick={() => store.retryFailed([file.id])}
                        >
                          <ReloadOutlined />
                        </button>
                      </>
                    ) : file.status === "uploading" ? (
                      <span
                        className={styles.spinner}
                        role="status"
                        aria-label={statusLabel}
                      />
                    ) : file.status === "success" ? (
                      <span
                        className={styles.successDot}
                        role="img"
                        aria-label={statusLabel}
                      />
                    ) : (
                      <span
                        className={styles.queuedDot}
                        role="img"
                        aria-label={statusLabel}
                      />
                    )}
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>
    </section>
  );
};

export default UploadCenterFloatingPanel;
