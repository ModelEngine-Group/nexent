// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useTranslation } from "react-i18next";
import { formatMetric } from "@/lib/trajectory";
import type {
  Percentiles,
  TrajectorySummary as Summary,
} from "@/types/trajectory";
import { CoverageNotice } from "./TrajectoryFeedback";

export function TrajectorySummary({ summary }: { summary?: Summary }) {
  const { t } = useTranslation();
  const valid = summary?.complete ? summary : undefined;
  const samples = (count?: number) =>
    count === undefined
      ? t("trajectory.samplesUnknown")
      : t("trajectory.samples", { count });
  const percentiles = (values?: Percentiles) => (
    <div className="trajectory-percentiles">
      {(["p50_ms", "p90_ms", "p99_ms"] as const).map((key) => (
        <div key={key}>
          <small>{key.slice(0, 3).toUpperCase()}</small>
          <strong>
            {formatMetric(values?.[key] == null ? null : values[key] / 1000)}{" "}
            <small>s</small>
          </strong>
        </div>
      ))}
    </div>
  );
  return (
    <>
      <div className="trajectory-summary">
        <section style={{ borderColor: "#0067D1", color: "#0067D1" }}>
          <header>{t("trajectory.conversationCount")}</header>
          <strong>{formatMetric(valid?.conversation_count, 0)}</strong>
        </section>
        <section style={{ borderColor: "#AD6800", color: "#AD6800" }}>
          <header>
            {t("trajectory.meanDuration")}
            <small>{samples(valid?.duration.sample_count)}</small>
          </header>
          <strong>
            {formatMetric(
              valid?.duration.mean_ms == null
                ? null
                : valid.duration.mean_ms / 1000
            )}{" "}
            <small>s</small>
          </strong>
        </section>
        <section style={{ borderColor: "#722ED1", color: "#722ED1" }}>
          <header>
            {t("trajectory.ttft")}
            <small>{samples(valid?.ttft.sample_count)}</small>
          </header>
          {percentiles(valid?.ttft)}
        </section>
        <section style={{ borderColor: "#08979C", color: "#08979C" }}>
          <header>
            {t("trajectory.runDuration")}
            <small>{samples(valid?.conversation_duration?.sample_count)}</small>
          </header>
          {percentiles(valid?.conversation_duration)}
        </section>
      </div>
      {summary && (
        <CoverageNotice
          coverage={summary.complete ? summary.coverage : { complete: false }}
        />
      )}
    </>
  );
}
