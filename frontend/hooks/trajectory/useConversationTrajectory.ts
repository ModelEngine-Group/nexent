// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useInfiniteQuery } from "@tanstack/react-query";
import { trajectoryService } from "@/services/trajectoryService";
import { recordKey } from "@/lib/trajectory";
import type { TrajectoryExecution, TrajectoryRecord } from "@/types/trajectory";

interface Address {
  directoryCursor?: string;
  directorySnapshot?: string;
  run?: TrajectoryExecution;
  nodeCursor?: string;
  snapshotId?: string;
  nextDirectory?: string | null;
  previous?: Address;
}

/** One execution segment per read; React Query bounds retained segment previews. */
export function useConversationTrajectory(
  row: TrajectoryRecord,
  queryId?: string
) {
  return useInfiniteQuery({
    queryKey: ["trajectory-conversation", recordKey(row), queryId],
    initialPageParam: {} as Address,
    queryFn: async ({ pageParam: address, signal }) => {
      const directory = address.run
        ? undefined
        : await trajectoryService.conversation(
            row,
            {
              cursor: address.directoryCursor,
              snapshot_id: address.directoryCursor
                ? undefined
                : address.directorySnapshot,
              query_id: queryId,
              limit: 1,
            },
            signal
          );
      signal.throwIfAborted();
      const run = address.run ?? directory?.executions[0];
      const nextDirectory = address.run
        ? address.nextDirectory
        : directory?.next_cursor;
      const snapshot =
        run && ["available", "partial"].includes(run.availability)
          ? await trajectoryService.snapshot(
              { ...row, trajectory_id: run.trajectory_id },
              { cursor: address.nodeCursor, snapshot_id: address.snapshotId },
              signal
            )
          : undefined;
      const next: Address | undefined =
        snapshot?.next_cursor && run
          ? {
              run,
              nodeCursor: snapshot.next_cursor,
              snapshotId: snapshot.snapshot_id,
              nextDirectory,
            }
          : nextDirectory
            ? { directoryCursor: nextDirectory }
            : undefined;
      return {
        run,
        directory,
        snapshot,
        next,
        address: {
          ...address,
          directorySnapshot:
            directory?.snapshot_id ?? address.directorySnapshot,
        },
      };
    },
    getNextPageParam: (last) =>
      last.next ? { ...last.next, previous: last.address } : undefined,
    getPreviousPageParam: (first) => first.address.previous,
    maxPages: 4,
    // Cursor history is a linked chain; avoid recursive structural comparison.
    structuralSharing: false,
    retry: false,
    gcTime: 0,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
}
