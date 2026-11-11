// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useEffect, useMemo, useRef, useState } from "react";
import { Alert, Spin } from "antd";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { StandardDrawer } from "@/components/common/StandardDrawer";
import { StandardButton } from "@/components/common/StandardButton";
import { trajectoryService } from "@/services/trajectoryService";
import { BodyCache, recordKey } from "@/lib/trajectory";
import type { TrajectoryRecord } from "@/types/trajectory";
import { TrajectoryError, CoverageNotice } from "./TrajectoryFeedback";
import { TrajectoryTimeline } from "./TrajectoryTimeline";
import { TrajectoryNodeDetail } from "./TrajectoryNodeDetail";

interface Address {
  cursor?: string;
  node_id?: string;
}

export function TrajectoryDrawer({
  row,
  onClose,
}: {
  row: TrajectoryRecord;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const [address, setAddress] = useState<Address>({});
  const [history, setHistory] = useState<Address[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const [invalidated, setInvalidated] = useState<unknown>(null);
  const [, setContentRevision] = useState(0);
  const snapshotId = useRef<string | undefined>(undefined);
  const cache = useMemo(() => new BodyCache(), []);
  useEffect(() => () => cache.clear(), [cache]);
  const query = useQuery({
    queryKey: ["trajectory-snapshot", recordKey(row), address, revision],
    queryFn: async ({ signal }) => {
      const page = await trajectoryService.snapshot(
        row,
        { ...address, snapshot_id: snapshotId.current },
        signal
      );
      if (!signal.aborted) snapshotId.current = page.snapshot_id;
      return page;
    },
    enabled: !!row.trajectory_id,
    retry: false,
    gcTime: 0,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
  const page = query.data;
  const nodes = useMemo(
    () => [
      ...new Map(
        [...(page?.context_nodes ?? []), ...(page?.nodes ?? [])].map((node) => [
          node.id,
          node,
        ])
      ).values(),
    ],
    [page]
  );
  const root = nodes.find((node) => node.id === page?.root_node_id);
  const selected =
    nodes.find((node) => node.id === selectedId) ?? root ?? nodes[0];
  const retry = () => {
    cache.clear();
    snapshotId.current = undefined;
    setAddress({});
    setHistory([]);
    setSelectedId(null);
    setInvalidated(null);
    setRevision((value) => value + 1);
  };
  const navigate = (next: Address) => {
    cache.clear();
    setHistory((previous) => [...previous.slice(-199), address]);
    setAddress(next);
    setSelectedId(next.node_id ?? null);
  };
  return (
    <StandardDrawer
      open
      title={row.root_agent_name || t("trajectory.executionDetail")}
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
        {!row.trajectory_id && (
          <Alert
            type="info"
            showIcon
            title={t(`trajectory.availability.${row.availability}`, {
              defaultValue: row.availability,
            })}
          />
        )}
        {query.isPending && row.trajectory_id && (
          <div className="p-6 text-center">
            <Spin />
          </div>
        )}
        {(query.isError || invalidated != null) && (
          <TrajectoryError error={invalidated ?? query.error} retry={retry} />
        )}
        {page && invalidated == null && (
          <>
            <CoverageNotice coverage={page.coverage} />
            <div className="trajectory-detail-grid">
              <TrajectoryTimeline
                key={JSON.stringify(address)}
                nodes={nodes}
                root={root}
                selected={selected?.id}
                complete={page.scope.complete}
                cache={cache}
                onSelect={(node) => setSelectedId(node.id)}
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
                  onParent={(id) => {
                    if (nodes.some((node) => node.id === id)) setSelectedId(id);
                    else navigate({ node_id: id });
                  }}
                />
              )}
            </div>
            <div className="trajectory-segment-navigation">
              <small>
                {t(
                  page.scope.complete
                    ? "trajectory.currentExecution"
                    : "trajectory.loadedRange"
                )}
              </small>
              <StandardButton
                disabled={!history.length}
                onClick={() => {
                  const previous = history.at(-1);
                  if (previous) {
                    cache.clear();
                    setAddress(previous);
                    setHistory((items) => items.slice(0, -1));
                    setSelectedId(null);
                  }
                }}
              >
                {t("trajectory.previousSegment")}
              </StandardButton>
              <StandardButton
                disabled={!page.next_cursor}
                onClick={() => navigate({ cursor: page.next_cursor! })}
              >
                {t("trajectory.nextSegment")}
              </StandardButton>
            </div>
          </>
        )}
      </div>
    </StandardDrawer>
  );
}
