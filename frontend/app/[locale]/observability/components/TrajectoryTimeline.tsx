// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useEffect, useRef, useState } from "react";
import { Empty, Select } from "antd";
import {
  ChevronDown,
  ChevronRight,
  ChevronsDownUp,
  ChevronsUpDown,
  Search,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { StandardButton } from "@/components/common/StandardButton";
import { StandardInput } from "@/components/common/StandardInput";
import {
  BodyCache,
  filterTree,
  formatMetric,
  formatTraceTime,
} from "@/lib/trajectory";
import type { TrajectoryExecution, TrajectoryNode } from "@/types/trajectory";
import { AgentVersion } from "./AgentVersion";
import {
  NodeIcon,
  TrajectoryStatus,
  nodeDuration,
  userInputPreview,
} from "./TrajectoryPresentation";

export function TrajectoryTimeline({
  nodes,
  root,
  selected,
  complete,
  cache,
  onSelect,
  onEndReached,
  unavailable = [],
}: {
  nodes: TrajectoryNode[];
  root?: TrajectoryNode;
  selected?: string;
  complete: boolean;
  cache: BodyCache;
  onSelect: (node: TrajectoryNode) => void;
  onEndReached?: () => void;
  unavailable?: TrajectoryExecution[];
}) {
  const { t } = useTranslation();
  const container = useRef<HTMLDivElement>(null);
  const end = useRef<HTMLDivElement>(null);
  const [viewport, setViewport] = useState({ top: 0, height: 800 });
  useEffect(() => {
    if (
      !onEndReached ||
      !end.current ||
      typeof IntersectionObserver === "undefined"
    )
      return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) onEndReached();
      },
      { root: container.current, rootMargin: "80px" }
    );
    observer.observe(end.current);
    return () => observer.disconnect();
  }, [onEndReached]);
  const [search, setSearch] = useState("");
  const [kind, setKind] = useState("");
  const [collapsed, setCollapsed] = useState(new Set<string>());
  const visible = filterTree(nodes, search, kind, undefined, (id, query) =>
    cache.matches(`${id}:`, query)
  );
  const filtering = !!search.trim() || !!kind;
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const children = new Map<string, TrajectoryNode[]>();
  for (const node of nodes) {
    const key =
      node.parent_id && byId.has(node.parent_id) ? node.parent_id : "";
    const siblings = children.get(key) ?? [];
    siblings.push(node);
    children.set(key, siblings);
  }
  const treeRows: { node: TrajectoryNode; depth: number }[] = [];
  const visited = new Set<string>();
  function walk(node: TrajectoryNode, depth: number) {
    if (visited.has(node.id)) return;
    visited.add(node.id);
    if (!visible.has(node.id)) return;
    treeRows.push({ node, depth });
    if (filtering || !collapsed.has(node.id))
      for (const child of children.get(node.id) ?? []) walk(child, depth + 1);
  }
  for (const node of children.get("") ?? []) walk(node, 0);
  // Broken historical ancestry stays visible rather than silently disappearing.
  for (const node of nodes) {
    if (visited.has(node.id)) continue;
    const ancestors = new Set<string>();
    let parent = node.parent_id;
    let hidden = false;
    while (parent && !ancestors.has(parent)) {
      if (visited.has(parent)) {
        hidden = true;
        break;
      }
      ancestors.add(parent);
      parent = byId.get(parent)?.parent_id ?? null;
    }
    if (!hidden) walk(node, 0);
  }
  const rows: (
    | { node: TrajectoryNode; depth: number }
    | { execution: TrajectoryExecution; depth: number }
    | { heading: TrajectoryNode; depth: number }
    | { axis: TrajectoryNode; depth: number }
  )[] = treeRows.flatMap((entry) =>
    entry.node.parent_id === null
      ? [
          ...(entry.node.round_no != null
            ? [{ heading: entry.node, depth: 0 }]
            : []),
          { axis: entry.node, depth: 0 },
          entry,
        ]
      : [entry]
  );
  if (!filtering) {
    for (const execution of unavailable) {
      const index = rows.findIndex(
        (entry) =>
          ("node" in entry
            ? (entry.node.round_no ?? 0)
            : "execution" in entry
              ? entry.execution.round_no
              : "heading" in entry
                ? (entry.heading.round_no ?? 0)
                : (entry.axis.round_no ?? 0)) > execution.round_no
      );
      rows.splice(index < 0 ? rows.length : index, 0, { execution, depth: 0 });
    }
  }
  const originNode = (node: TrajectoryNode) =>
    byId.get(node.execution_root_id ?? "") ??
    root ??
    (node.parent_id === null ? node : undefined);
  const roots = nodes.filter((node) => node.parent_id === null);
  const modelCalls =
    roots.length && roots.every((node) => node.model_call_count != null)
      ? roots.reduce((sum, node) => sum + node.model_call_count!, 0)
      : null;
  const start = Math.min(
    Math.max(0, rows.length - 1),
    Math.max(0, Math.floor((viewport.top - 150) / 44) - 10)
  );
  const finish = Math.min(
    rows.length,
    Math.ceil((viewport.top + viewport.height) / 44) + 10
  );
  const geometry = (node: TrajectoryNode) => {
    const base = originNode(node);
    const origin = base?.started_at ? Date.parse(base.started_at) : NaN;
    const duration = base?.duration_ms;
    if (
      !Number.isFinite(origin) ||
      duration == null ||
      duration <= 0 ||
      !node.started_at ||
      node.duration_ms == null
    )
      return null;
    const left = Math.min(
      100,
      Math.max(0, ((Date.parse(node.started_at) - origin) / duration) * 100)
    );
    return {
      left,
      width: Math.max(
        0.5,
        Math.min(100 - left, (node.duration_ms / duration) * 100)
      ),
    };
  };
  return (
    <div
      className="trajectory-timeline"
      ref={container}
      onScroll={(event) => {
        const target = event.currentTarget;
        setViewport({
          top: target.scrollTop,
          height: target.clientHeight || 800,
        });
      }}
    >
      <div className="trajectory-timeline-controls">
        <StandardInput
          prefix={<Search size={14} />}
          aria-label={t("trajectory.nodeSearch")}
          placeholder={t("trajectory.nodeSearch")}
          value={search}
          onChange={(event) => {
            setSearch(event.target.value);
            container.current?.scrollTo?.(0, 0);
            setViewport((previous) => ({ ...previous, top: 0 }));
          }}
        />
        <div className="trajectory-tree-toolbar">
          <span>{t("trajectory.timeline")}</span>
          <StandardButton
            className="trajectory-collapse-all !h-[22px] !w-[22px] !border-0 !p-0 !text-[#777]"
            aria-label={t(
              collapsed.size ? "trajectory.expandAll" : "trajectory.collapseAll"
            )}
            title={t(
              collapsed.size ? "trajectory.expandAll" : "trajectory.collapseAll"
            )}
            aria-expanded={collapsed.size === 0}
            onClick={() =>
              setCollapsed((previous) =>
                previous.size
                  ? new Set()
                  : new Set(
                      nodes
                        .filter(
                          (node) => (children.get(node.id)?.length ?? 0) > 0
                        )
                        .map((node) => node.id)
                    )
              )
            }
          >
            {collapsed.size ? (
              <ChevronsUpDown size={14} aria-hidden />
            ) : (
              <ChevronsDownUp size={14} aria-hidden />
            )}
          </StandardButton>
        </div>
        <div className="trajectory-tree-filter">
          <span>
            {nodes.length} {t("trajectory.nodes")}
          </span>
          <Select
            variant="borderless"
            aria-label={t("trajectory.nodeType")}
            value={kind}
            onChange={(value) => {
              setKind(value);
              container.current?.scrollTo?.(0, 0);
              setViewport((previous) => ({ ...previous, top: 0 }));
            }}
            options={[
              { value: "", label: t("trajectory.allTypes") },
              ...["agent", "model", "tool"].map((value) => ({
                value,
                label: t(`trajectory.kinds.${value}`),
              })),
            ]}
          />
        </div>
      </div>
      <p
        className="trajectory-tree-hint"
        title={`${t("trajectory.searchScope")}: ${t(complete && !nodes.some((node) => node.round_no != null) && nodes.every((node) => node.input?.complete && node.output?.complete) ? "trajectory.currentExecution" : "trajectory.loadedRange")}`}
      >
        {t("trajectory.timelineHint")} · {t("trajectory.loadedRange")}
      </p>
      <div
        className="trajectory-timeline-rows"
        role="tree"
        aria-label={t("trajectory.timeline")}
      >
        {rows.length === 0 && <Empty description={t("trajectory.noNodes")} />}
        <div
          style={{ height: Math.min(start, rows.length) * 44 }}
          aria-hidden
        />
        {rows.slice(start, finish).map((entry, localIndex) => {
          if ("execution" in entry)
            return (
              <div
                className="trajectory-timeline-row items-center px-3 text-xs text-gray-500"
                key={entry.execution.trajectory_id}
              >
                <span>
                  {t("trajectory.round", { number: entry.execution.round_no })}
                </span>
                <span>
                  {t(`trajectory.availability.${entry.execution.availability}`)}
                </span>
              </div>
            );
          if ("heading" in entry) {
            const node = entry.heading;
            const userInput = userInputPreview(node.input?.text);
            return (
              <div
                key={`heading:${node.id}`}
                className="trajectory-round-heading"
                data-round={node.round_no}
              >
                <strong>
                  {t("trajectory.round", { number: node.round_no })}
                </strong>
                <time>
                  {formatTraceTime(node.started_at).split(" ")[1] || "—"}
                </time>
                <TrajectoryStatus status={node.status} />
                <span title={userInput}>{userInput || "—"}</span>
              </div>
            );
          }
          if ("axis" in entry)
            return (
              <div
                key={`axis:${entry.axis.id}`}
                className="trajectory-time-axis"
              >
                <span>{t("trajectory.callNode")}</span>
                <div>
                  <span>0 s</span>
                  <span>{nodeDuration(entry.axis.duration_ms)}</span>
                </div>
                <span>{t("trajectory.duration")}</span>
              </div>
            );
          const { node, depth } = entry;
          const index = start + localIndex;
          const hasChildren = (children.get(node.id)?.length ?? 0) > 0;
          const open = filtering || !collapsed.has(node.id);
          const bar = geometry(node);
          let descendants = 0;
          for (
            let next = index + 1;
            next < rows.length && rows[next].depth > depth;
            next++
          )
            descendants++;
          const color =
            node.kind === "agent"
              ? "#7d99d8"
              : node.kind === "model"
                ? "#b29acf"
                : "#82b4b5";
          return (
            <div
              key={node.id}
              className={`trajectory-timeline-row ${node.id === selected ? "is-selected" : ""} ${hasChildren ? "is-parent" : ""}`}
            >
              <div
                className="trajectory-tree-label"
                style={{ paddingLeft: Math.min(depth, 10) * 16 + 8 }}
              >
                {depth > 0 && (
                  <span
                    aria-hidden
                    className="trajectory-tree-connector"
                    style={{ left: Math.min(depth, 10) * 16 }}
                  />
                )}
                <button
                  className="trajectory-toggle"
                  aria-label={t(
                    open ? "trajectory.collapseNode" : "trajectory.expandNode",
                    { name: node.name }
                  )}
                  disabled={!hasChildren}
                  aria-expanded={hasChildren ? open : undefined}
                  onClick={() =>
                    setCollapsed((previous) => {
                      const next = new Set(previous);
                      if (next.has(node.id)) next.delete(node.id);
                      else next.add(node.id);
                      return next;
                    })
                  }
                >
                  {hasChildren ? (
                    open ? (
                      <ChevronDown size={12} />
                    ) : (
                      <ChevronRight size={12} />
                    )
                  ) : null}
                </button>
                <button
                  role="treeitem"
                  aria-level={depth + 1}
                  aria-selected={node.id === selected}
                  className="trajectory-node-name flex min-w-0 items-center"
                  title={[
                    node.name,
                    node.parent_id === null ? node.input?.text : null,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                  onClick={() => onSelect(node)}
                >
                  <NodeIcon kind={node.kind} />
                  <span className="truncate">{node.name}</span>
                  {node.kind === "agent" && (
                    <span className="trajectory-tree-version">
                      <AgentVersion
                        version={node.agent_version_no}
                        name={node.agent_version_name}
                      />
                    </span>
                  )}
                </button>
                {node.direct_child_count > 0 && (
                  <small>{node.direct_child_count}</small>
                )}
              </div>
              <button
                data-round={node.round_no}
                className="trajectory-time-cell"
                aria-label={`${node.name}: ${formatMetric(node.duration_ms)} ms`}
                onClick={() => onSelect(node)}
              >
                {bar && (
                  <>
                    <span
                      className="trajectory-time-bar"
                      style={{
                        left: `${bar.left}%`,
                        width: `${bar.width}%`,
                        background: color,
                        height: hasChildren ? 10 : 7,
                      }}
                    />
                    {hasChildren && open && descendants > 0 && (
                      <>
                        <span
                          className="trajectory-range-guide"
                          style={{
                            left: `${bar.left}%`,
                            height: descendants * 44 + 22,
                            color,
                          }}
                        />
                        <span
                          className="trajectory-range-guide"
                          style={{
                            left: `${bar.left + bar.width}%`,
                            height: descendants * 44 + 22,
                            color,
                          }}
                        />
                      </>
                    )}
                  </>
                )}
              </button>
              <span className="trajectory-row-duration">
                {nodeDuration(node.duration_ms)}
              </span>
            </div>
          );
        })}
        <div
          style={{ height: Math.max(0, rows.length - finish) * 44 }}
          aria-hidden
        />
        <div ref={end} />
      </div>
      <footer
        className="trajectory-tree-footer"
        title={t("trajectory.loadedRange")}
      >
        <span aria-hidden />
        {t("trajectory.loadedModelCalls", {
          count: formatMetric(modelCalls, 0),
        })}
      </footer>
    </div>
  );
}
