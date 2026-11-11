// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useState } from "react";
import { Empty, Select } from "antd";
import { useTranslation } from "react-i18next";
import { StandardButton } from "@/components/common/StandardButton";
import { StandardInput } from "@/components/common/StandardInput";
import { BodyCache, filterTree, formatMetric } from "@/lib/trajectory";
import type { TrajectoryNode } from "@/types/trajectory";

export function TrajectoryTimeline({
  nodes,
  root,
  selected,
  complete,
  cache,
  onSelect,
}: {
  nodes: TrajectoryNode[];
  root?: TrajectoryNode;
  selected?: string;
  complete: boolean;
  cache: BodyCache;
  onSelect: (node: TrajectoryNode) => void;
}) {
  const { t } = useTranslation();
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
  const rows: { node: TrajectoryNode; depth: number }[] = [];
  const visited = new Set<string>();
  function walk(node: TrajectoryNode, depth: number) {
    if (visited.has(node.id)) return;
    visited.add(node.id);
    if (!visible.has(node.id)) return;
    rows.push({ node, depth });
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
  const origin = root?.started_at ? Date.parse(root.started_at) : NaN;
  const duration = root?.duration_ms;
  const geometry = (node: TrajectoryNode) => {
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
    <div className="trajectory-timeline">
      <div className="flex flex-wrap gap-2 p-3">
        <StandardInput
          className="!min-w-28 !flex-1"
          aria-label={t("trajectory.nodeSearch")}
          placeholder={t("trajectory.nodeSearch")}
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        <Select
          aria-label={t("trajectory.nodeType")}
          value={kind}
          onChange={setKind}
          options={[
            { value: "", label: t("trajectory.allTypes") },
            ...["agent", "model", "tool"].map((value) => ({
              value,
              label: t(`trajectory.kinds.${value}`),
            })),
          ]}
        />
        <StandardButton
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
          {t(
            collapsed.size ? "trajectory.expandAll" : "trajectory.collapseAll"
          )}
        </StandardButton>
      </div>
      <p className="px-3 text-xs text-gray-500">
        {t("trajectory.searchScope")}:{" "}
        {t(
          complete &&
            nodes.every((node) => node.input?.complete && node.output?.complete)
            ? "trajectory.currentExecution"
            : "trajectory.loadedRange"
        )}{" "}
        · {rows.length} {t("trajectory.nodes")}
      </p>
      <div className="trajectory-time-axis">
        <span>{t("trajectory.timeline")}</span>
        <div>
          <span>0 s</span>
          <span>
            {formatMetric(duration == null ? null : duration / 1000)} s
          </span>
        </div>
      </div>
      <div
        className="trajectory-timeline-rows"
        role="tree"
        aria-label={t("trajectory.timeline")}
      >
        {rows.length === 0 && <Empty description={t("trajectory.noNodes")} />}
        {rows.map(({ node, depth }, index) => {
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
              ? "#722ed1"
              : node.kind === "model"
                ? "#1677ff"
                : "#08979c";
          return (
            <div
              key={node.id}
              className={`trajectory-timeline-row ${node.id === selected ? "is-selected" : ""} ${hasChildren ? "is-parent" : ""}`}
            >
              <div
                className="trajectory-tree-label"
                style={{ paddingLeft: Math.min(depth, 10) * 16 + 8 }}
              >
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
                  {hasChildren ? (open ? "▾" : "▸") : "·"}
                </button>
                <button
                  role="treeitem"
                  aria-level={depth + 1}
                  aria-selected={node.id === selected}
                  className="trajectory-node-name"
                  title={node.name}
                  onClick={() => onSelect(node)}
                >
                  <span style={{ color }}>●</span> {node.name}
                </button>
                {node.direct_child_count > 0 && (
                  <small>{node.direct_child_count}</small>
                )}
              </div>
              <button
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
                <small>
                  {formatMetric(
                    node.duration_ms == null ? null : node.duration_ms / 1000
                  )}{" "}
                  s
                </small>
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}
