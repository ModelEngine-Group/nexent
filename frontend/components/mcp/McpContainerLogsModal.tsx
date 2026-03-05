import { Modal, Button, Spin } from "antd";
import { useTranslation } from "react-i18next";
import { useEffect, useRef, useState } from "react";
import { streamMcpContainerLogs } from "@/services/mcpService";
import log from "@/lib/logger";

interface McpContainerLogsModalProps {
  open: boolean;
  onCancel: () => void;
  containerId: string;
  tenantId?: string | null;
  tail?: number;
}

export default function McpContainerLogsModal({
  open,
  onCancel,
  containerId,
  tenantId,
  tail = 100,
}: McpContainerLogsModalProps) {
  const { t } = useTranslation("common");
  const [logs, setLogs] = useState<string>("");
  const [loading, setLoading] = useState<boolean>(false);
  const logsRef = useRef<HTMLPreElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  // Auto-scroll to bottom when new logs arrive
  useEffect(() => {
    if (logsRef.current) {
      logsRef.current.scrollTop = logsRef.current.scrollHeight;
    }
  }, [logs]);

  // Start streaming logs when modal opens
  useEffect(() => {
    if (open && containerId) {
      // Cancel any existing stream before starting a new one
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
        abortControllerRef.current = null;
      }

      setLogs("");
      setLoading(true);

      // Start new stream
      streamMcpContainerLogs(
        containerId,
        tail,
        true, // follow
        tenantId,
        (logLine: string) => {
          setLogs((prev) => {
            const newLogs = prev ? `${prev}\n${logLine}` : logLine;
            return newLogs;
          });
          setLoading(false);
        },
        (error: any) => {
          // Ignore abort errors
          if (error.name !== 'AbortError') {
            log.error("Failed to stream container logs", error);
            setLogs((prev) => 
              prev 
                ? `${prev}\nError: ${error.message}`
                : `Error: ${error.message}`
            );
            setLoading(false);
          }
        },
        () => {
          setLoading(false);
        }
      ).then((controller) => {
        abortControllerRef.current = controller;
      });
    }

    // Cleanup when modal closes or component unmounts
    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
        abortControllerRef.current = null;
      }
      if (!open) {
        setLogs("");
      }
    };
  }, [open, containerId, tail, tenantId, t]);

  return (
    <Modal
      title={`${t("mcpConfig.containerLogs.title")} - ${containerId?.substring(0, 12)}`}
      open={open}
      onCancel={onCancel}
      width={800}
      footer={[<Button key="close" onClick={onCancel}>{t("mcpConfig.modal.close")}</Button>]}
    >
      <Spin spinning={loading} tip={t("mcpConfig.containerLogs.loading")}>
        <pre
          ref={logsRef}
          className="bg-gray-100 p-4 rounded max-h-[500px] overflow-auto whitespace-pre-wrap text-xs font-mono"
        >
          {logs || t("mcpConfig.containerLogs.empty")}
        </pre>
      </Spin>
    </Modal>
  );
}

