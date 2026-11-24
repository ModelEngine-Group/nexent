// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Alert, Button } from "antd";
import { useTranslation } from "react-i18next";
import { evolutionService as api } from "@/services/evolutionService";

type Version = Awaited<
  ReturnType<typeof api.releaseMonitoring>
>["versions"][number];
export default function ReleaseMonitoring({
  lock,
  tenant,
  viewer,
}: {
  lock: number;
  tenant?: string;
  viewer?: string;
}) {
  const { t, i18n } = useTranslation("common");
  const [open, setOpen] = useState(false);
  const query = useQuery({
    queryKey: ["release-monitoring", tenant, viewer, lock],
    queryFn: () => api.releaseMonitoring(lock),
    enabled: open,
    retry: false,
    staleTime: 0,
  });
  const data = query.error ? undefined : query.data;
  const format = (stamp: string) =>
    new Date(stamp).toLocaleString(i18n?.language);
  const rows: [string, (v: Version) => string | number][] = [
    ["sessions", (v) => v.sessions],
    ["executions", (v) => v.executions],
    ["unverified", (v) => v.unverified],
    ["binding", (v) => v.binding_mismatches],
    ["failed", (v) => v.failed],
    ["stopped", (v) => v.stopped],
    ["p90", (v) => (v.p90_ms == null ? "—" : Math.round(v.p90_ms) + " ms")],
    ["timed", (v) => v.timed + "/" + v.executions],
    [
      "tokens",
      (v) => (v.mean_tokens == null ? "—" : Math.round(v.mean_tokens)),
    ],
    ["metered", (v) => v.metered + "/" + v.executions],
    ["reviewed", (v) => v.reviewed + "/" + v.executions],
    ["tool_errors", (v) => (v.reviewed ? v.tool_errors : "—")],
    ["corrected", (v) => (v.reviewed ? v.corrected : "—")],
    ["missing_files", (v) => (v.reviewed ? v.missing_files : "—")],
    ["disliked", (v) => (v.reviewed ? v.disliked : "—")],
  ];
  return (
    <section>
      <Button aria-expanded={open} onClick={() => setOpen(!open)}>
        {t("evolution.monitor.open")}
      </Button>
      {open && (
        <>
          <Button loading={query.isFetching} onClick={() => query.refetch()}>
            {t("evolution.monitor.refresh")}
          </Button>
          {query.error && <Alert type="error" message={query.error.message} />}
          {data && (
            <>
              <p>
                {t("evolution.monitor.window", {
                  since: format(data.since),
                  until: format(data.until),
                })}
              </p>
              <table className="w-full text-left">
                <thead>
                  <tr>
                    <th>{t("evolution.monitor.metric")}</th>
                    {data.versions.map((v) => (
                      <th key={v.version_no}>V{v.version_no}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map(([key, value]) => (
                    <tr key={key}>
                      <th scope="row">{t("evolution.monitor." + key)}</th>
                      {data.versions.map((v) => (
                        <td key={v.version_no}>{value(v)}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
              <p>{t("evolution.monitor.coverage")}</p>
              <strong>{t("evolution.monitor.history")}</strong>
              <ul>
                {data.events.map((e) => (
                  <li key={e.action}>
                    {format(e.created_at)} ·{" "}
                    {t("evolution.monitor.event." + e.action)} · {e.actor} ·{" "}
                    {e.reason}
                  </li>
                ))}
              </ul>
            </>
          )}
        </>
      )}
    </section>
  );
}
