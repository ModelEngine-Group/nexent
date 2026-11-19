// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useEffect, useRef, useState } from "react";
import { App, Button } from "antd";
import { Download } from "lucide-react";
import { useTranslation } from "react-i18next";
import { trajectoryService } from "@/services/trajectoryService";
import type { TrajectoryRecord } from "@/types/trajectory";

export function TrajectoryExportButton({ row }: { row: TrajectoryRecord }) {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const [loading, setLoading] = useState(false);
  const request = useRef<AbortController | null>(null);
  const download = useRef<{
    url: string;
    timer: ReturnType<typeof setTimeout>;
  } | null>(null);
  useEffect(() => {
    const release = () => {
      request.current?.abort();
      request.current = null;
      setLoading(false);
      if (download.current) {
        clearTimeout(download.current.timer);
        URL.revokeObjectURL(download.current.url);
        download.current = null;
      }
    };
    window.addEventListener("pagehide", release);
    return () => {
      release();
      window.removeEventListener("pagehide", release);
    };
  }, []);
  const save = async () => {
    if (request.current) return;
    const controller = new AbortController();
    request.current = controller;
    setLoading(true);
    try {
      const blob = await trajectoryService.exportArchive(
        row,
        controller.signal
      );
      if (controller.signal.aborted) return;
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `trajectory-${row.conversation_id}.zip`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      if (download.current) {
        clearTimeout(download.current.timer);
        URL.revokeObjectURL(download.current.url);
      }
      download.current = {
        url,
        timer: setTimeout(() => {
          URL.revokeObjectURL(url);
          download.current = null;
        }, 1000),
      };
    } catch (error) {
      if (!controller.signal.aborted) {
        const code = (error as { code?: string })?.code;
        void message.error(
          t(`trajectory.errors.${code}`, {
            defaultValue: t("trajectory.exportFailed"),
          })
        );
      }
    } finally {
      if (request.current === controller) request.current = null;
      if (!controller.signal.aborted) setLoading(false);
    }
  };
  return (
    <Button
      icon={<Download size={14} />}
      loading={loading}
      onClick={() => void save()}
    >
      {t("trajectory.export")}
    </Button>
  );
}
