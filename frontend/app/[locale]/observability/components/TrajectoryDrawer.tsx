// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useEffect, useMemo, useState } from "react";
import { Alert, Spin } from "antd";
import { useTranslation } from "react-i18next";
import { StandardDrawer } from "@/components/common/StandardDrawer";
import { StandardButton } from "@/components/common/StandardButton";
import { BodyCache, invalidatesTrajectory } from "@/lib/trajectory";
import { useConversationTrajectory } from "@/hooks/trajectory/useConversationTrajectory";
import type { TrajectoryRecord } from "@/types/trajectory";
import { TrajectoryError, CoverageNotice } from "./TrajectoryFeedback";
import { TrajectoryTimeline } from "./TrajectoryTimeline";
import { TrajectoryNodeDetail } from "./TrajectoryNodeDetail";

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
  const [, setContentRevision] = useState(0);
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
  const unavailable = (pages ?? []).filter(
    ({ run, snapshot }) => run && !snapshot
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
  return (
    <StandardDrawer
      open
      title={row.conversation_title || t("trajectory.executionDetail")}
      closeLabel={t("trajectory.close")}
      closeText={t("trajectory.close")}
      onClose={onClose}
      width="min(1400px, 94vw)"
      maskClosable
      footer={null}
    >
      <div className="trajectory-drawer-content">
        <div className="trajectory-drawer-heading">
          <span>{row.conversation_title || row.conversation_id}</span>
          <code>{row.conversation_id}</code>
          <span>{t("trajectory.shanghai")}</span>
        </div>
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
            <CoverageNotice
              coverage={pages[0]?.directory?.coverage ?? row.coverage}
            />
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
              <StandardButton
                loading={query.isFetchingPreviousPage}
                onClick={() => void query.fetchPreviousPage()}
              >
                {t("trajectory.previousRounds")}
              </StandardButton>
            )}
            <div className="trajectory-detail-grid">
              <TrajectoryTimeline
                nodes={nodes}
                unavailable={unavailable.map(({ run }) => run!)}
                selected={selected?.id}
                complete={!query.hasNextPage && !query.hasPreviousPage}
                cache={cache}
                onSelect={(node) => setSelectedId(node.id)}
                onEndReached={
                  canLoad ? () => void query.fetchNextPage() : undefined
                }
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
            <div className="trajectory-segment-navigation">
              <small>
                {t("trajectory.loadedRange")} · {nodes.length}{" "}
                {t("trajectory.nodes")}
              </small>
              <StandardButton
                disabled={!query.hasNextPage}
                loading={query.isFetchingNextPage}
                onClick={() => void query.fetchNextPage()}
              >
                {t("trajectory.loadMore")}
              </StandardButton>
            </div>
          </>
        )}
      </div>
    </StandardDrawer>
  );
}
