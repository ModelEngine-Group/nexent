"use client";

import { useState, useCallback, useEffect } from "react";
import { monitoringService } from "@/services/monitoringService";
import type { ModelMonitoringItem } from "@/types/monitoring";

export type TimeRange = "24h" | "7d" | "30d";

export function useMonitoringData(initialTimeRange: TimeRange = "24h") {
  const [models, setModels] = useState<ModelMonitoringItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [timeRange, setTimeRange] = useState<TimeRange>(initialTimeRange);

  const fetchData = useCallback(async (range: TimeRange) => {
    setLoading(true);
    try {
      const modelsData = await monitoringService.fetchModels({ time_range: range });
      setModels(modelsData);
    } finally {
      setLoading(false);
    }
  }, []);

  const refresh = useCallback(async () => {
    await fetchData(timeRange);
  }, [fetchData, timeRange]);

  useEffect(() => {
    fetchData(timeRange);
  }, [fetchData, timeRange]);

  return { models, loading, refresh, timeRange, setTimeRange };
}
