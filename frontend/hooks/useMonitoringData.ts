"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { monitoringService } from "@/services/monitoringService";
import type {
  ModelMonitoringItem,
  ModelSummaryResponse,
  TrendPoint,
  FailureDetail,
  AlertRecord,
  PaginatedData,
  AlertFilter,
} from "@/types/monitoring";

const EMPTY_PAGINATED = <T,>(): PaginatedData<T> => ({
  items: [],
  total: 0,
  page: 1,
  page_size: 20,
  total_pages: 0,
});

export function useMonitoringData() {
  const [models, setModels] = useState<ModelMonitoringItem[]>([]);
  const [trend, setTrend] = useState<TrendPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [timeRange, setTimeRange] = useState("24h");
  const [trendModelId, setTrendModelId] = useState<string | undefined>(undefined);
  const intervalRef = useRef<NodeJS.Timeout | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [modelsData, trendData] = await Promise.all([
        monitoringService.fetchModels({ time_range: timeRange }),
        monitoringService.fetchAggregatedTrend({
          time_range: timeRange,
          interval: "1h",
          model_id: trendModelId,
        }),
      ]);
      setModels(modelsData);
      setTrend(trendData);
    } finally {
      setLoading(false);
    }
  }, [timeRange, trendModelId]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  useEffect(() => {
    intervalRef.current = setInterval(fetchData, 30000);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [fetchData]);

  return { models, trend, loading, timeRange, setTimeRange, trendModelId, setTrendModelId, refresh: fetchData };
}

export function useModelDetail(modelId: string) {
  const [summary, setSummary] = useState<ModelSummaryResponse | null>(null);
  const [trend, setTrend] = useState<TrendPoint[]>([]);
  const [failures, setFailures] = useState<PaginatedData<FailureDetail>>(EMPTY_PAGINATED());
  const [loading, setLoading] = useState(true);
  const [trendInterval, setTrendInterval] = useState("1h");

  useEffect(() => {
    if (!modelId) return;

    setLoading(true);
    Promise.all([
      monitoringService.fetchModelSummary(modelId),
      monitoringService.fetchModelTrend(modelId, { interval: trendInterval }),
      monitoringService.fetchModelFailures(modelId, { page: 1, page_size: 10 }),
    ])
      .then(([summaryData, trendData, failuresData]) => {
        setSummary(summaryData);
        setTrend(trendData);
        setFailures(failuresData);
      })
      .finally(() => setLoading(false));
  }, [modelId, trendInterval]);

  return { summary, trend, failures, loading, trendInterval, setTrendInterval };
}

export function useAlerts() {
  const [alerts, setAlerts] = useState<PaginatedData<AlertRecord>>(EMPTY_PAGINATED());
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<AlertFilter>({});
  const intervalRef = useRef<NodeJS.Timeout | null>(null);

  const fetchAlerts = useCallback(async () => {
    setLoading(true);
    try {
      const data = await monitoringService.fetchAlerts(filter);
      setAlerts(data);
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => {
    fetchAlerts();
  }, [fetchAlerts]);

  useEffect(() => {
    intervalRef.current = setInterval(fetchAlerts, 15000);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [fetchAlerts]);

  const acknowledge = useCallback(async (alertId: string) => {
    const success = await monitoringService.acknowledgeAlert(alertId);
    if (success) fetchAlerts();
    return success;
  }, [fetchAlerts]);

  const resolve = useCallback(async (alertId: string) => {
    const success = await monitoringService.resolveAlert(alertId);
    if (success) fetchAlerts();
    return success;
  }, [fetchAlerts]);

  return { alerts, loading, filter, setFilter, acknowledge, resolve };
}
