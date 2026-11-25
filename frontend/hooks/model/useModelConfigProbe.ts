// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useCallback, useEffect, useRef, useState } from "react";
import { modelCheckFailure, type ModelCheckIssue } from "@/lib/modelCheckIssues";
import { modelService } from "@/services/modelService";

export function useModelConfigProbe() {
  const [status, setStatus] = useState<
    "idle" | "checking" | "available" | "unavailable"
  >("idle");
  const [issue, setIssue] = useState<ModelCheckIssue | null>(null);
  const active = useRef<AbortController | null>(null);

  useEffect(() => () => active.current?.abort(), []);

  const reset = useCallback(() => {
    active.current?.abort();
    active.current = null;
    setStatus("idle");
    setIssue(null);
  }, []);

  async function check(
    config: Parameters<typeof modelService.verifyModelConfigConnectivity>[0]
  ) {
    if (active.current) return;
    const controller = new AbortController();
    active.current = controller;
    setStatus("checking");
    setIssue(null);
    try {
      const result = await modelService.verifyModelConfigConnectivity(
        config,
        controller.signal
      );
      if (controller.signal.aborted) return;
      setStatus(result.connectivity ? "available" : "unavailable");
      if (!result.connectivity) {
        setIssue(
          result.diagnostic ?? { category: "MODEL_PROBE_FAILED", scope: "model" }
        );
      }
    } catch (error) {
      if (controller.signal.aborted) return;
      setStatus("unavailable");
      setIssue(modelCheckFailure(error));
    } finally {
      if (active.current === controller) active.current = null;
    }
  }

  return { status, issue, check, reset };
}
