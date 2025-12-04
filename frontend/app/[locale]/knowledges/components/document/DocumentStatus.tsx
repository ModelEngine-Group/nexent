import React, { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Popover, Progress } from "antd";
import { QuestionCircleOutlined } from "@ant-design/icons";
import { DOCUMENT_STATUS } from "@/const/knowledgeBase";
import knowledgeBaseService from "@/services/knowledgeBaseService";
import log from "@/lib/logger";

interface DocumentStatusProps {
  status: string;
  showIcon?: boolean;
  errorReason?: string;
  suggestion?: string;
  kbId?: string;
  docId?: string;
  // Optional ingestion progress metrics
  processedChunkNum?: number | null;
  totalChunkNum?: number | null;
}

export const DocumentStatus: React.FC<DocumentStatusProps> = ({
  status,
  showIcon = false,
  errorReason,
  suggestion,
  kbId,
  docId,
  processedChunkNum,
  totalChunkNum,
}) => {
  const { t } = useTranslation();
  const [reasonState, setReasonState] = useState<string | null>(
    errorReason ?? null
  );
  const [suggestionState, setSuggestionState] = useState<string | null>(
    suggestion ?? null
  );
  const [isPopoverOpen, setIsPopoverOpen] = useState(false);
  const [isFetching, setIsFetching] = useState(false);
  const [hasFetched, setHasFetched] = useState(false);

  useEffect(() => {
    // If parent props change (e.g. list refreshed), sync initial values
    setReasonState(errorReason ?? null);
    setSuggestionState(suggestion ?? null);
    setHasFetched(false);
  }, [errorReason, suggestion, kbId, docId]);

  // Map API status to display status
  const getDisplayStatus = (apiStatus: string): string => {
    switch (apiStatus) {
      case DOCUMENT_STATUS.WAIT_FOR_PROCESSING:
        return t("document.status.waitForProcessing");
      case DOCUMENT_STATUS.WAIT_FOR_FORWARDING:
        return t("document.status.waitForForwarding");
      case DOCUMENT_STATUS.PROCESSING:
        return t("document.status.processing");
      case DOCUMENT_STATUS.FORWARDING:
        return t("document.status.forwarding");
      case DOCUMENT_STATUS.COMPLETED:
        return t("document.status.completed");
      case DOCUMENT_STATUS.PROCESS_FAILED:
        return t("document.status.processFailed");
      case DOCUMENT_STATUS.FORWARD_FAILED:
        return t("document.status.forwardFailed");
      default:
        return apiStatus;
    }
  };

  // Get status type and corresponding styles
  const getStatusStyles = (): {
    bgColor: string;
    textColor: string;
    borderColor: string;
  } => {
    switch (status) {
      case DOCUMENT_STATUS.COMPLETED:
        return {
          bgColor: "bg-green-100",
          textColor: "text-green-800",
          borderColor: "border-green-200",
        };
      case DOCUMENT_STATUS.PROCESSING:
      case DOCUMENT_STATUS.FORWARDING:
        return {
          bgColor: "bg-blue-100",
          textColor: "text-blue-800",
          borderColor: "border-blue-200",
        };
      case DOCUMENT_STATUS.PROCESS_FAILED:
      case DOCUMENT_STATUS.FORWARD_FAILED:
        return {
          bgColor: "bg-red-100",
          textColor: "text-red-800",
          borderColor: "border-red-200",
        };
      case DOCUMENT_STATUS.WAIT_FOR_PROCESSING:
      case DOCUMENT_STATUS.WAIT_FOR_FORWARDING:
        return {
          bgColor: "bg-yellow-100",
          textColor: "text-yellow-800",
          borderColor: "border-yellow-200",
        };
      default:
        return {
          bgColor: "bg-gray-100",
          textColor: "text-gray-800",
          borderColor: "border-gray-200",
        };
    }
  };

  // Get status icon
  const getStatusIcon = () => {
    if (!showIcon) return null;

    switch (status) {
      case DOCUMENT_STATUS.COMPLETED:
        return "✓";
      case DOCUMENT_STATUS.PROCESSING:
      case DOCUMENT_STATUS.FORWARDING:
        return "⟳";
      case DOCUMENT_STATUS.PROCESS_FAILED:
      case DOCUMENT_STATUS.FORWARD_FAILED:
        return "✗";
      case DOCUMENT_STATUS.WAIT_FOR_PROCESSING:
      case DOCUMENT_STATUS.WAIT_FOR_FORWARDING:
        return "⏱";
      default:
        return null;
    }
  };

  const { bgColor, textColor, borderColor } = getStatusStyles();
  const displayStatus = getDisplayStatus(status);

  const isFailedStatus =
    status === DOCUMENT_STATUS.PROCESS_FAILED ||
    status === DOCUMENT_STATUS.FORWARD_FAILED;

  const hasValidProgress =
    typeof processedChunkNum === "number" &&
    typeof totalChunkNum === "number" &&
    totalChunkNum > 0;

  // Show progress for processing or forwarding status (入库中 corresponds to FORWARDING)
  const shouldShowProgress =
    (status === DOCUMENT_STATUS.PROCESSING ||
      status === DOCUMENT_STATUS.FORWARDING) &&
    hasValidProgress;

  const progressPercent = hasValidProgress
    ? Math.min(
        100,
        Math.max(0, Math.round((processedChunkNum / totalChunkNum) * 100))
      )
    : 0;

  const fetchErrorInfo = async () => {
    if (!kbId || !docId) return;
    setIsFetching(true);
    try {
      const result = await knowledgeBaseService.getDocumentErrorInfo(
        kbId,
        docId
      );
      setReasonState(result.reason ?? null);
      setSuggestionState(result.suggestion ?? null);
    } catch (error) {
      log.error("Failed to fetch document error info:", error);
    } finally {
      setIsFetching(false);
      setHasFetched(true);
    }
  };

  const handlePopoverVisibleChange = (visible: boolean) => {
    setIsPopoverOpen(visible);
    if (
      visible &&
      kbId &&
      docId &&
      !isFetching &&
      !hasFetched &&
      !reasonState
    ) {
      fetchErrorInfo();
    }
  };

  const popoverContent = (
    <div className="max-w-md">
      {isFetching ? (
        <div className="text-sm text-gray-500">{t("common.loading")}</div>
      ) : reasonState ? (
        <div>
          <div className="mb-2">
            <div className="text-sm text-gray-700">{reasonState}</div>
          </div>
          {suggestionState && (
            <div className="mt-1">
              <div className="text-sm font-medium mb-1">
                {t("document.error.suggestion")}
              </div>
              <div className="text-sm text-gray-700">{suggestionState}</div>
            </div>
          )}
        </div>
      ) : (
        <div className="text-sm text-gray-500">
          {t("document.error.noReason")}
        </div>
      )}
    </div>
  );

  return (
    <span
      className={`inline-flex items-center px-1.5 py-0.5 rounded-md text-xs font-medium ${bgColor} ${textColor} border ${borderColor} whitespace-nowrap`}
    >
      {showIcon && <span className="mr-1">{getStatusIcon()}</span>}
      {displayStatus}
      {shouldShowProgress && hasValidProgress && (
        <Popover
          content={
            <div className="text-xs text-gray-700">
              {t("document.progress.chunksProcessed", {
                processed: processedChunkNum,
                total: totalChunkNum,
                percent: progressPercent,
              })}
            </div>
          }
          placement="top"
        >
          <span className="ml-2 inline-flex items-center">
            <Progress
              type="circle"
              percent={progressPercent}
              size={14}
              strokeWidth={10}
              showInfo={false}
            />
          </span>
        </Popover>
      )}
      {isFailedStatus && (
        <Popover
          content={popoverContent}
          title={t("document.error.reason")}
          trigger={["hover", "click"]}
          placement="top"
          open={isPopoverOpen}
          onOpenChange={handlePopoverVisibleChange}
        >
          <QuestionCircleOutlined
            className="ml-1.5 cursor-help text-gray-500 hover:text-gray-700"
            style={{ fontSize: "12px" }}
          />
        </Popover>
      )}
    </span>
  );
};

export default DocumentStatus;
