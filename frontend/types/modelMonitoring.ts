// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import type { MonitoringPublication } from "./operations";

export interface ModelMonitoringTrends extends MonitoringPublication {
  data: { statistic_date: string; request_count: number | null }[];
}
