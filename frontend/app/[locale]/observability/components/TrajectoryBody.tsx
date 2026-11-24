// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { App, Button, Segmented, Spin } from "antd";
import {
  ChevronDown,
  ChevronRight,
  Copy,
  Maximize2,
  Minimize2,
  WrapText,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { trajectoryService } from "@/services/trajectoryService";
import { BodyCache, invalidatesTrajectory } from "@/lib/trajectory";
import type { ContentReference } from "@/types/trajectory";
import { TrajectoryError } from "./TrajectoryFeedback";
import { TrajectoryMarkdown } from "./TrajectoryMarkdown";
import { modelInputRows, TrajectoryModelInput } from "./TrajectoryModelInput";
import {
  outputMarkdown,
  type MarkdownOutputKind,
} from "./trajectoryOutputMarkdown";

type BodyMode = "text" | "json" | "markdown" | "table";

interface TrajectoryBodyProps {
  reference: ContentReference;
  slot: string;
  previewKind?: MarkdownOutputKind | "modelInput";
  conversationId: string;
  nodeId: string;
  cache: BodyCache;
  onLoaded: () => void;
  onInvalidated?: (error: unknown) => void;
}

export function TrajectoryBody(props: TrajectoryBodyProps) {
  return (
    <TrajectoryBodyContent
      key={JSON.stringify([
        props.conversationId,
        props.nodeId,
        props.slot,
        props.previewKind,
        props.reference.content_id,
        props.reference.availability,
        props.reference.complete,
      ])}
      {...props}
    />
  );
}

function TrajectoryBodyContent({
  reference,
  slot,
  previewKind,
  conversationId,
  nodeId,
  cache,
  onLoaded,
  onInvalidated,
}: TrajectoryBodyProps) {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const [collapsed, setCollapsed] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [preferredMode, setMode] = useState<BodyMode>(
    previewKind === "modelInput" ? "table" : previewKind ? "markdown" : "json"
  );
  const [wordWrap, setWordWrap] = useState(false);
  const [chunk, setChunk] = useState<{
    offset: number;
    next: number;
    complete: boolean;
    text: string;
  } | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const request = useRef<AbortController | null>(null);
  const retryOffset = useRef(0);
  const progress = useRef<typeof chunk>(null);
  const failed = useRef(false);
  const callbacks = useRef({ onLoaded, onInvalidated });
  useEffect(() => {
    callbacks.current = { onLoaded, onInvalidated };
  }, [onLoaded, onInvalidated]);
  const awaitingFirstChunk =
    reference.availability === "available" &&
    !reference.complete &&
    !!reference.content_id &&
    chunk === null;
  const showLoading = loading || (awaitingFirstChunk && error === null);
  const text = chunk?.text ?? reference.text ?? reference.preview ?? "";
  const complete = chunk?.complete ?? reference.complete;
  const offset = chunk?.offset ?? 0;
  const markdown = useMemo(() => {
    if (
      !previewKind ||
      previewKind === "modelInput" ||
      !complete ||
      reference.availability !== "available"
    )
      return "";
    return outputMarkdown(text, previewKind, {
      field: t("trajectory.markdownField"),
      value: t("trajectory.markdownValue"),
      index: t("trajectory.markdownIndex"),
      logs: t("trajectory.markdownLogs"),
    });
  }, [complete, previewKind, reference.availability, t, text]);
  const modelRows = useMemo(
    () =>
      previewKind === "modelInput" &&
      complete &&
      reference.availability === "available"
        ? modelInputRows(text)
        : null,
    [complete, previewKind, reference.availability, text]
  );
  const mode =
    (preferredMode === "markdown" && !markdown) ||
    (preferredMode === "table" && !modelRows)
      ? "json"
      : preferredMode;
  const tableRows = mode === "table" ? modelRows : null;
  const isMarkdown = mode === "markdown";
  const formatted = useMemo(() => {
    if (mode === "markdown") return markdown;
    if (mode !== "json") return text;
    try {
      return JSON.stringify(JSON.parse(text), null, 2);
    } catch {
      return JSON.stringify({ content: text }, null, 2);
    }
  }, [text, mode, markdown]);
  const lineNumbers = useMemo(
    () =>
      isMarkdown || tableRows
        ? ""
        : Array.from(
            { length: Math.min(formatted.split("\n").length, 10000) },
            (_, index) => index + 1
          ).join("\n"),
    [formatted, isMarkdown, tableRows]
  );
  const load = useCallback(
    async (offset: number) => {
      if (!reference.content_id || request.current) return;
      const controller = new AbortController();
      request.current = controller;
      retryOffset.current = offset;
      setLoading(true);
      setError(null);
      try {
        const key = `${nodeId}:${slot}:0`;
        // Each chunk is authorized by the server; the bounded cache supports local search only.
        const value = await trajectoryService.content(
          conversationId,
          reference.content_id,
          offset,
          controller.signal
        );
        if (controller.signal.aborted) return;
        if (
          value.offset !== offset ||
          !Number.isSafeInteger(value.next_offset) ||
          value.next_offset < offset ||
          (!value.complete && value.next_offset === offset)
        )
          throw { code: "invalid_parameters" };
        const accumulated =
          offset === 0
            ? value.text
            : (progress.current?.text ?? "") + value.text;
        if (
          Math.max(
            accumulated.length * 2,
            new TextEncoder().encode(accumulated).length
          ) > cache.limit
        )
          throw { code: "body_budget_exceeded" };
        cache.set(key, accumulated);
        const next = {
          offset: 0,
          next: value.next_offset,
          text: accumulated,
          complete: value.complete,
        };
        progress.current = next;
        failed.current = false;
        setChunk(next);
        callbacks.current.onLoaded();
      } catch (cause) {
        if (!controller.signal.aborted) {
          if (invalidatesTrajectory(cause)) {
            cache.clear();
            callbacks.current.onInvalidated?.(cause);
          }
          failed.current = true;
          setError(cause);
        }
      } finally {
        if (request.current === controller && !controller.signal.aborted) {
          request.current = null;
          setLoading(false);
        }
      }
    },
    [reference.content_id, conversationId, nodeId, slot, cache]
  );
  useEffect(() => {
    if (reference.availability === "available" && !reference.complete)
      void load(0);
    return () => {
      request.current?.abort();
      request.current = null;
    };
  }, [load, reference.availability, reference.complete]);
  const loadAtBottom = (element: HTMLElement) => {
    const current = progress.current;
    if (
      current &&
      !current.complete &&
      !failed.current &&
      element.scrollTop + element.clientHeight >= element.scrollHeight - 24
    )
      void load(current.next);
  };
  const copyButton = (
    <button
      className="trajectory-icon-button"
      aria-label={t("trajectory.copy")}
      disabled={
        awaitingFirstChunk || (!text && reference.availability !== "available")
      }
      onClick={() => {
        void navigator.clipboard.writeText(formatted).then(
          () => message.success(t("trajectory.copied")),
          () => message.error(t("trajectory.copyFailed"))
        );
      }}
    >
      <Copy size={14} />
    </button>
  );
  return (
    <section className="trajectory-body" aria-busy={showLoading}>
      <header>
        <button
          aria-expanded={!collapsed}
          onClick={() => setCollapsed((value) => !value)}
        >
          {collapsed ? <ChevronRight size={12} /> : <ChevronDown size={12} />}{" "}
          {t(`trajectory.${slot}`)}
        </button>
        <div className="flex flex-wrap items-center gap-1">
          <Segmented<BodyMode>
            size="small"
            value={mode}
            onChange={setMode}
            options={[
              { label: t("trajectory.text"), value: "text" },
              { label: "JSON", value: "json" },
              ...(markdown
                ? [{ label: "Markdown", value: "markdown" as const }]
                : []),
              ...(modelRows
                ? [{ label: t("trajectory.table"), value: "table" as const }]
                : []),
            ]}
          />
          {!collapsed && tableRows && copyButton}
        </div>
      </header>
      {!collapsed && tableRows && <TrajectoryModelInput rows={tableRows} />}
      {!collapsed && !tableRows && (
        <>
          {reference.availability !== "available" ? (
            <p className="p-3 text-xs text-gray-500">
              {t(`trajectory.bodyAvailability.${reference.availability}`, {
                defaultValue: t("trajectory.bodyUnavailable"),
              })}
            </p>
          ) : (
            <>
              {!awaitingFirstChunk && (
                <div className="trajectory-code-card">
                  <div className="trajectory-code-toolbar">
                    <span>{isMarkdown ? "Markdown" : mode.toUpperCase()}</span>
                    <span
                      className="trajectory-code-meta"
                      title={t(
                        offset === 0 && complete
                          ? "trajectory.fullContent"
                          : "trajectory.contentRange",
                        {
                          start: offset,
                          end:
                            chunk?.next ??
                            new TextEncoder().encode(text).length,
                          total: reference.byte_count ?? "—",
                        }
                      )}
                    >
                      {t("trajectory.characters", {
                        count: reference.char_count ?? Array.from(text).length,
                      })}
                      <span className="trajectory-code-actions">
                        {!isMarkdown && (
                          <Button
                            type={wordWrap ? "primary" : "text"}
                            size="small"
                            icon={<WrapText size={14} />}
                            aria-label={t(
                              wordWrap
                                ? "trajectory.unwrapLines"
                                : "trajectory.wrapLines"
                            )}
                            title={t(
                              wordWrap
                                ? "trajectory.unwrapLines"
                                : "trajectory.wrapLines"
                            )}
                            aria-pressed={wordWrap}
                            disabled={reference.availability !== "available"}
                            onClick={() => setWordWrap((value) => !value)}
                          />
                        )}
                        {copyButton}
                        <button
                          className="trajectory-icon-button"
                          aria-label={t(
                            expanded
                              ? "trajectory.collapseContent"
                              : "trajectory.expandContent"
                          )}
                          onClick={() => setExpanded((value) => !value)}
                        >
                          {expanded ? (
                            <Minimize2 size={13} />
                          ) : (
                            <Maximize2 size={13} />
                          )}
                        </button>
                      </span>
                    </span>
                  </div>
                  {isMarkdown ? (
                    <div
                      className={`markdown-body trajectory-markdown-body ${expanded ? "trajectory-body-full" : "trajectory-body-preview"}`}
                      role="region"
                      aria-label={t(`trajectory.${slot}`)}
                      tabIndex={0}
                    >
                      <TrajectoryMarkdown text={markdown} />
                    </div>
                  ) : (
                    <div className="trajectory-code-scroll">
                      <pre
                        tabIndex={0}
                        onScroll={(event) => loadAtBottom(event.currentTarget)}
                        onWheel={(event) => {
                          if (event.deltaY > 0)
                            loadAtBottom(event.currentTarget);
                        }}
                        className={[
                          expanded
                            ? "trajectory-body-full"
                            : "trajectory-body-preview",
                          wordWrap ? "is-wrapped" : "",
                        ].join(" ")}
                      >
                        <span className="trajectory-line-numbers" aria-hidden>
                          {lineNumbers}
                        </span>
                        <code>{formatted || t("trajectory.emptyBody")}</code>
                      </pre>
                    </div>
                  )}
                </div>
              )}
              {showLoading && (
                <div
                  role="status"
                  className="flex items-center gap-2 p-2 text-xs text-gray-500"
                >
                  <Spin size="small" />
                  {t("trajectory.loadingContent")}
                </div>
              )}
            </>
          )}
          {error != null && (
            <TrajectoryError
              error={error}
              retry={() => void load(retryOffset.current)}
            />
          )}
        </>
      )}
    </section>
  );
}
