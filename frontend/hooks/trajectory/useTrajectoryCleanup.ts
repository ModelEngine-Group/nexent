// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useEffect, useRef, useState } from "react";
import { trajectoryService } from "@/services/trajectoryService";
import type { CleanupResult } from "@/types/trajectory";

export function useTrajectoryCleanup(onComplete: () => void) {
  const controller = useRef<AbortController | null>(null);
  const continuation = useRef<{ days: number; cursor?: string } | null>(null);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<CleanupResult | null>(null);
  const [error, setError] = useState<unknown>(null);
  const complete = useRef(onComplete);
  useEffect(() => {
    complete.current = onComplete;
  }, [onComplete]);

  function cancel() {
    controller.current?.abort();
    controller.current = null;
    setRunning(false);
  }
  useEffect(() => () => controller.current?.abort(), []);

  async function start(days: number, resume = false) {
    if (controller.current) return;
    const request = new AbortController();
    controller.current = request;
    setRunning(true);
    setError(null);
    let cursor =
      resume && continuation.current?.days === days
        ? continuation.current.cursor
        : undefined;
    let accumulated = resume ? result : null;
    if (!resume) setResult(null);
    try {
      do {
        continuation.current = { days, cursor };
        const batch = await trajectoryService.cleanup(
          days,
          cursor,
          request.signal
        );
        if (request.signal.aborted) return;
        accumulated = {
          ...batch,
          scanned_runs: (accumulated?.scanned_runs ?? 0) + batch.scanned_runs,
          deleted_runs: (accumulated?.deleted_runs ?? 0) + batch.deleted_runs,
          deleted_bytes:
            (accumulated?.deleted_bytes ?? 0) + batch.deleted_bytes,
          skipped_active:
            (accumulated?.skipped_active ?? 0) + batch.skipped_active,
          pending_runs: (accumulated?.pending_runs ?? 0) + batch.pending_runs,
          failed_runs: (accumulated?.failed_runs ?? 0) + batch.failed_runs,
        };
        setResult(accumulated);
        cursor = batch.next_cursor ?? undefined;
        continuation.current = { days, cursor };
        if (batch.done) break;
        if (!cursor) throw new Error("cleanup_cursor_missing");
      } while (!request.signal.aborted);
      if (!request.signal.aborted) complete.current();
    } catch (cause) {
      if (!request.signal.aborted) setError(cause);
    } finally {
      if (controller.current === request) {
        controller.current = null;
        setRunning(false);
      }
    }
  }
  return { running, result, error, start, cancel };
}
