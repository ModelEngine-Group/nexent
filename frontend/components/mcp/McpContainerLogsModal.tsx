// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { Modal, Button, Spin } from "antd";
import { useTranslation } from "react-i18next";
import { useEffect, useRef, useState } from "react";
import { streamMcpContainerLogs } from "@/services/mcpService";
import log from "@/lib/logger";

interface McpContainerLogsModalProps {
  open: boolean;
  onCancel: () => void;
  containerId?: string | null;
  tenantId?: string | null;
  tail?: number;
}

export function McpContainerLogOutput({
  open,
  containerId,
  tenantId,
  tail = 100,
  className = "bg-gray-100 p-4 rounded max-h-[500px] overflow-auto whitespace-pre-wrap text-xs font-mono",
}: Omit<McpContainerLogsModalProps, "onCancel"> & { className?: string }) {
  const { t } = useTranslation("common");
  const [logs, setLogs] = useState("");
  const [loading, setLoading] = useState(false);
  const logsRef = useRef<HTMLPreElement>(null);

  useEffect(() => {
    if (logsRef.current)
      logsRef.current.scrollTop = logsRef.current.scrollHeight;
  }, [logs]);

  useEffect(() => {
    if (!open || !containerId) return;
    const controller = new AbortController();
    setLogs("");
    setLoading(true);
    const stopLoading = () => {
      if (!controller.signal.aborted) setLoading(false);
    };
    void streamMcpContainerLogs(
      containerId,
      tail,
      true,
      tenantId,
      (line) => {
        if (controller.signal.aborted) return;
        setLogs((previous) => (previous ? `${previous}\n${line}` : line));
        stopLoading();
      },
      (error: Error) => {
        if (controller.signal.aborted || error.name === "AbortError") return;
        log.error("Failed to stream container logs", error);
        setLogs((previous) =>
          previous
            ? `${previous}\nError: ${error.message}`
            : `Error: ${error.message}`
        );
        stopLoading();
      },
      stopLoading,
      controller.signal,
      stopLoading
    );
    return () => controller.abort();
  }, [open, containerId, tail, tenantId]);

  if (!open) return null;
  return (
    <Spin
      spinning={loading && Boolean(containerId)}
      description={t("mcpConfig.containerLogs.loading")}
    >
      <pre ref={logsRef} className={className}>
        {logs || t("mcpConfig.containerLogs.empty")}
      </pre>
    </Spin>
  );
}

export default function McpContainerLogsModal({
  open,
  onCancel,
  containerId,
  tenantId,
  tail,
}: McpContainerLogsModalProps) {
  const { t } = useTranslation("common");
  return (
    <Modal
      title={`${t("mcpConfig.containerLogs.title")}${containerId ? ` - ${containerId.substring(0, 12)}` : ""}`}
      open={open}
      onCancel={onCancel}
      width={800}
      footer={[
        <Button key="close" onClick={onCancel}>
          {t("mcpConfig.modal.close")}
        </Button>,
      ]}
    >
      <McpContainerLogOutput
        open={open}
        containerId={containerId}
        tenantId={tenantId}
        tail={tail}
      />
    </Modal>
  );
}
