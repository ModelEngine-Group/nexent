// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useCallback, useEffect, useMemo, useState } from "react";
import { Alert, Spin, Button, Drawer } from "antd";
import { Clock3, Sparkles } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  BodyCache,
  invalidatesTrajectory,
  formatMetric,
} from "@/lib/trajectory";
import { useConversationTrajectory } from "@/hooks/trajectory/useConversationTrajectory";
import type { TrajectoryRecord } from "@/types/trajectory";
import { TrajectoryError } from "./TrajectoryFeedback";
import { TrajectoryTimeline } from "./TrajectoryTimeline";
import { TrajectoryNodeDetail } from "./TrajectoryNodeDetail";
import { CopyTraceId, nodeDuration } from "./TrajectoryPresentation";

export function TrajectoryDrawer({
  row,
  queryId,
  onClose,
  onReset,
}: {
  row: TrajectoryRecord;
  queryId?: string;
  onClose: () => void;
  onReset?: () => void;
}) {
  const { t } = useTranslation();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [invalidated, setInvalidated] = useState<unknown>(null);
  const [contentRevision, setContentRevision] = useState(0);
  const cache = useMemo(() => new BodyCache(), []);
  useEffect(() => () => cache.clear(), [cache]);
  const query = useConversationTrajectory(row, queryId);
  const pages = query.data?.pages;
  const nodes = useMemo(
    () => [
      ...new Map(
        (pages ?? [])
          .flatMap(({ run, snapshot }) => {
            if (!run || !snapshot) return [];
            const key = (id: string) => `${run.trajectory_id}/${id}`;
            return [...snapshot.context_nodes, ...snapshot.nodes].map(
              (node) => ({
                ...node,
                id: key(node.id),
                parent_id: node.parent_id ? key(node.parent_id) : null,
                execution_root_id: snapshot.root_node_id
                  ? key(snapshot.root_node_id)
                  : undefined,
                trajectory_id: run.trajectory_id,
                round_no: run.round_no,
                matches_filters: run.matches_filters,
              })
            );
          })
          .map((node) => [node.id, node])
      ).values(),
    ],
    [pages]
  );
  const selected = nodes.find((node) => node.id === selectedId) ?? nodes[0];
  const unavailable = useMemo(
    () =>
      (pages ?? [])
        .filter(({ run, snapshot }) => run && !snapshot)
        .map(({ run }) => run!),
    [pages]
  );
  const fatal =
    invalidated ?? (invalidatesTrajectory(query.error) ? query.error : null);
  useEffect(() => {
    if (fatal != null) cache.clear();
  }, [fatal, cache]);
  const retry = () => {
    if (fatal && onReset) {
      onReset();
      return;
    }
    if (fatal) {
      cache.clear();
      setSelectedId(null);
      void query.refetch().then((result) => {
        if (result.isSuccess) setInvalidated(null);
      });
      return;
    }
    if (query.isFetchNextPageError && !fatal) void query.fetchNextPage();
    else if (query.isFetchPreviousPageError && !fatal)
      void query.fetchPreviousPage();
    else void query.refetch();
  };
  const canLoad = query.hasNextPage && !query.isFetching && !query.isError;
  const { fetchNextPage } = query;
  const loadNext = useCallback(() => void fetchNextPage(), [fetchNextPage]);
  return (
    <Drawer
      open
      title={t("trajectory.conversationDetail")}
      closable={{ placement: "end", "aria-label": t("trajectory.close") }}
      onClose={onClose}
      size="min(1800px, 98vw)"
      mask={{ closable: true }}
      classNames={{
        section: "!p-6 !shadow-[-2px_0_12px_0_rgba(0,0,0,0.08)]",
        header: "!m-0 !h-[28px] !shrink-0 !border-0 !p-0",
        title: "!text-[20px] !leading-[28px]",
        body: "!flex !min-h-0 !flex-1 !overflow-y-auto !px-0 !pt-4 !pb-0",
      }}
      footer={null}
    >
      <div className="trajectory-drawer-content">
        <div className="trajectory-viewer">
          <header className="trajectory-viewer-heading">
            <div className="trajectory-viewer-title">
              <h1>{row.root_agent_name || t("trajectory.unknownAgent")}</h1>
              <span className="trajectory-round-label">
                {formatMetric(row.round_count, 0)} {t("trajectory.roundUnit")}
              </span>
              <span
                className="trajectory-task-name"
                title={row.conversation_title || undefined}
              >
                {row.conversation_title}
              </span>
            </div>
            <div className="trajectory-viewer-identity">
              <span>Trace ID</span>
              <code>{row.conversation_id}</code>
              <CopyTraceId value={row.conversation_id} />
              <i />
              <span>
                <Clock3 size={12} />
                {nodeDuration(row.duration_ms)}
              </span>
              <span>
                <Sparkles size={12} />
                {formatMetric(row.usage?.total, 0)} Tokens
              </span>
            </div>
          </header>
          {query.isPending && (
            <div className="p-6 text-center">
              <Spin />
            </div>
          )}
          {(query.isError || fatal != null) && (
            <TrajectoryError error={fatal ?? query.error} retry={retry} />
          )}
          {fatal == null && pages && (
            <>
              {!nodes.length && !unavailable.length && (
                <Alert
                  type="info"
                  showIcon
                  title={t(
                    `trajectory.availability.${pages[0]?.directory?.availability ?? row.availability}`
                  )}
                />
              )}
              {query.hasPreviousPage && (
                <Button
                  loading={query.isFetchingPreviousPage}
                  onClick={() => void query.fetchPreviousPage()}
                >
                  {t("trajectory.previousRounds")}
                </Button>
              )}
              <div className="trajectory-detail-grid">
                <TrajectoryTimeline
                  nodes={nodes}
                  unavailable={unavailable}
                  bodyRevision={contentRevision}
                  selected={selected?.id}
                  complete={!query.hasNextPage && !query.hasPreviousPage}
                  cache={cache}
                  onSelect={(node) => setSelectedId(node.id)}
                  onEndReached={canLoad ? loadNext : undefined}
                />
                {selected && (
                  <TrajectoryNodeDetail
                    key={selected.id}
                    node={selected}
                    conversationId={row.conversation_id}
                    cache={cache}
                    onLoaded={() => setContentRevision((value) => value + 1)}
                    onInvalidated={(error) => {
                      cache.clear();
                      setInvalidated(error);
                    }}
                    onParent={setSelectedId}
                  />
                )}
              </div>
              <footer className="trajectory-segment-navigation">
                <small>
                  {t("trajectory.loadedRange")} · {nodes.length}{" "}
                  {t("trajectory.nodes")}
                </small>
                {query.hasNextPage && (
                  <Button
                    disabled={!query.hasNextPage}
                    loading={query.isFetchingNextPage}
                    onClick={() => void query.fetchNextPage()}
                  >
                    {t("trajectory.loadMore")}
                  </Button>
                )}
              </footer>
            </>
          )}
        </div>
      </div>
    </Drawer>
  );
}
