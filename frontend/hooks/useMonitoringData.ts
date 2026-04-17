"use client";

import { useState, useCallback } from "react";
import { monitoringService } from "@/services/monitoringService";
import type { ModelMonitoringItem } from "@/types/monitoring";

export function useMonitoringData() {
  const [models, setModels] = useState<ModelMonitoringItem[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const modelsData = await monitoringService.fetchModels({ time_range: "24h" });
      setModels(modelsData);
    } finally {
      setLoading(false);
    }
  }, []);

  const refresh = useCallback(async () => {
    await fetchData();
  }, [fetchData]);

  useState(() => {
    fetchData();
  });

  return { models, loading, refresh };
}
