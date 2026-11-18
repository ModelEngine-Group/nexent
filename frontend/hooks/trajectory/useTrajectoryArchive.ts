// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useCallback, useEffect, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { AUTH_EVENTS } from "@/const/auth";
import { trajectoryService } from "@/services/trajectoryService";
import type { ImportedTrajectory } from "@/types/trajectory";

/** The page instance owns all imported data and outstanding uploads. */
export function useTrajectoryArchive(scope: string) {
  const request = useRef<AbortController | null>(null);
  const [state, setState] = useState<{
    scope: string;
    data: ImportedTrajectory | null;
    loading: boolean;
    error: unknown;
  } | null>(null);
  const clear = useCallback(() => {
    request.current?.abort();
    request.current = null;
    setState(null);
  }, []);
  useEffect(() => {
    const leave = () => flushSync(clear);
    window.addEventListener("pagehide", leave);
    window.addEventListener(AUTH_EVENTS.LOGOUT, clear);
    window.addEventListener(AUTH_EVENTS.SESSION_EXPIRED, clear);
    return () => {
      clear();
      window.removeEventListener("pagehide", leave);
      window.removeEventListener(AUTH_EVENTS.LOGOUT, clear);
      window.removeEventListener(AUTH_EVENTS.SESSION_EXPIRED, clear);
    };
  }, [scope, clear]);
  const open = useCallback(
    async (file: File) => {
      request.current?.abort();
      const controller = new AbortController();
      request.current = controller;
      setState({ scope, data: null, loading: true, error: null });
      try {
        const data = await trajectoryService.importArchive(
          file,
          controller.signal
        );
        if (!controller.signal.aborted && request.current === controller)
          setState({ scope, data, loading: false, error: null });
      } catch (error) {
        if (!controller.signal.aborted && request.current === controller)
          setState({ scope, data: null, loading: false, error });
      } finally {
        if (request.current === controller) request.current = null;
      }
    },
    [scope]
  );
  const current = state?.scope === scope ? state : null;
  return {
    data: current?.data ?? null,
    loading: current?.loading ?? false,
    error: current?.error ?? null,
    open,
    clear,
  };
}
