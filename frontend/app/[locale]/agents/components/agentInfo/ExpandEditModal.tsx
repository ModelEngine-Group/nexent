"use client";

import type { CSSProperties } from "react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Badge, Button, Input, Modal, Typography } from "antd";

type DiffStatus = "same" | "removed" | "added";

interface DiffLine {
  text: string;
  status: DiffStatus;
}

export interface ExpandEditModalProps {
  open: boolean;
  title: string;
  content: string;
  onClose: () => void;
  onSave: (content: string) => void;
  readOnly?: boolean;
  mode?: "edit" | "optimize";
  optimizeLoading?: boolean;
  optimizedContent?: string;
  onOptimize?: (feedback: string) => void;
  onApplyOptimized?: () => void;
}

function buildDiffLines(source: string, target: string): {
  leftLines: DiffLine[];
  rightLines: DiffLine[];
} {
  const left = source.split("\n");
  const right = target.split("\n");
  const dp = Array.from({ length: left.length + 1 }, () =>
    Array.from({ length: right.length + 1 }, () => 0)
  );

  for (let leftIndex = left.length - 1; leftIndex >= 0; leftIndex -= 1) {
    for (let rightIndex = right.length - 1; rightIndex >= 0; rightIndex -= 1) {
      if (left[leftIndex] === right[rightIndex]) {
        dp[leftIndex][rightIndex] = dp[leftIndex + 1][rightIndex + 1] + 1;
      } else {
        dp[leftIndex][rightIndex] = Math.max(
          dp[leftIndex + 1][rightIndex],
          dp[leftIndex][rightIndex + 1]
        );
      }
    }
  }

  const leftLines: DiffLine[] = [];
  const rightLines: DiffLine[] = [];
  let leftIndex = 0;
  let rightIndex = 0;

  while (leftIndex < left.length && rightIndex < right.length) {
    if (left[leftIndex] === right[rightIndex]) {
      leftLines.push({ text: left[leftIndex], status: "same" });
      rightLines.push({ text: right[rightIndex], status: "same" });
      leftIndex += 1;
      rightIndex += 1;
      continue;
    }

    if (dp[leftIndex + 1][rightIndex] >= dp[leftIndex][rightIndex + 1]) {
      leftLines.push({ text: left[leftIndex], status: "removed" });
      rightLines.push({ text: "", status: "same" });
      leftIndex += 1;
    } else {
      leftLines.push({ text: "", status: "same" });
      rightLines.push({ text: right[rightIndex], status: "added" });
      rightIndex += 1;
    }
  }

  while (leftIndex < left.length) {
    leftLines.push({ text: left[leftIndex], status: "removed" });
    rightLines.push({ text: "", status: "same" });
    leftIndex += 1;
  }

  while (rightIndex < right.length) {
    leftLines.push({ text: "", status: "same" });
    rightLines.push({ text: right[rightIndex], status: "added" });
    rightIndex += 1;
  }

  return { leftLines, rightLines };
}

function getDiffLineStyle(status: DiffStatus): CSSProperties {
  if (status === "removed") {
    return {
      backgroundColor: "#fff1f0",
      color: "#cf1322",
    };
  }

  if (status === "added") {
    return {
      backgroundColor: "#f6ffed",
      color: "#389e0d",
    };
  }

  return {
    backgroundColor: "transparent",
    color: "inherit",
  };
}

function DiffPanel({
  title,
  lines,
}: {
  title: string;
  lines: DiffLine[];
}) {
  return (
    <div className="flex-1 min-w-0 border rounded-md overflow-hidden">
      <div className="px-4 py-2 border-b bg-gray-50 text-sm font-medium">{title}</div>
      <div className="max-h-[420px] overflow-auto bg-white">
        <pre className="m-0 text-sm leading-6 font-mono whitespace-pre-wrap break-words">
          {lines.map((line, index) => (
            <div
              key={`${title}-${index}-${line.status}`}
              className="px-4"
              style={getDiffLineStyle(line.status)}
            >
              {line.text || " "}
            </div>
          ))}
        </pre>
      </div>
    </div>
  );
}

export default function ExpandEditModal({
  open,
  title,
  content,
  onClose,
  onSave,
  readOnly = false,
  mode = "edit",
  optimizeLoading = false,
  optimizedContent = "",
  onOptimize,
  onApplyOptimized,
}: ExpandEditModalProps) {
  const { t } = useTranslation("common");
  const [editContent, setEditContent] = useState(content);
  const [feedback, setFeedback] = useState("");

  useEffect(() => {
    setEditContent(content);
  }, [content]);

  useEffect(() => {
    if (open) {
      setFeedback("");
    }
  }, [open, mode]);

  const handleSave = () => {
    if (!readOnly) {
      onSave(editContent);
    }
    onClose();
  };

  const handleOptimize = () => {
    if (!onOptimize) return;
    const trimmedFeedback = feedback.trim();
    if (!trimmedFeedback) {
      return;
    }
    onOptimize(trimmedFeedback);
  };

  const diffLines = buildDiffLines(content, optimizedContent);
  const showOptimizationResult = mode === "optimize" && Boolean(optimizedContent);

  return (
    <Modal
      title={
        <div className="flex justify-between items-center">
          <div className="flex items-center">
            <Badge className="mr-3" />
            <span className="text-base font-medium">{title}</span>
          </div>
        </div>
      }
      open={open}
      onCancel={onClose}
      width={1200}
      styles={{
        body: { padding: "20px" },
      }}
      footer={
        mode === "optimize" ? (
          <div className="flex justify-between items-center">
            <Typography.Text type="secondary">
              {t("promptOptimize.modal.tip")}
            </Typography.Text>
            <div className="flex gap-2 justify-end">
              <Button onClick={onClose}>{t("common.cancel")}</Button>
              <Button
                onClick={handleOptimize}
                loading={optimizeLoading}
                type="primary"
              >
                {t("promptOptimize.button.submit")}
              </Button>
              <Button
                type="primary"
                disabled={!optimizedContent}
                onClick={onApplyOptimized}
              >
                {t("promptOptimize.button.apply")}
              </Button>
            </div>
          </div>
        ) : readOnly ? (
          <Button onClick={onClose}>{t("common.cancel")}</Button>
        ) : (
          <div className="flex justify-end gap-2">
            <Button onClick={onClose}>{t("common.cancel")}</Button>
            <Button type="primary" onClick={handleSave}>
              {t("common.confirm")}
            </Button>
          </div>
        )
      }
    >
      {mode === "optimize" ? (
        <div className="flex flex-col gap-4">
          <div>
            <div className="mb-2 text-sm font-medium">
              {t("promptOptimize.feedbackLabel")}
            </div>
            <Input.TextArea
              value={feedback}
              onChange={(event) => setFeedback(event.target.value)}
              placeholder={t("promptOptimize.feedbackPlaceholder")}
              autoSize={{ minRows: 3, maxRows: 6 }}
              status={feedback.trim() ? undefined : "error"}
            />
            {!feedback.trim() ? (
              <div className="mt-1 text-xs text-red-500">
                {t("promptOptimize.feedbackRequired")}
              </div>
            ) : null}
          </div>
          <div className="flex gap-4 items-start">
            <DiffPanel
              title={t("promptOptimize.originalTitle")}
              lines={showOptimizationResult ? diffLines.leftLines : content.split("\n").map((line) => ({ text: line, status: "same" as const }))}
            />
            <DiffPanel
              title={t("promptOptimize.optimizedTitle")}
              lines={showOptimizationResult ? diffLines.rightLines : [{ text: t("promptOptimize.emptyOptimized"), status: "same" }]}
            />
          </div>
        </div>
      ) : (
        <div className="flex-1 min-h-0">
          <Input.TextArea
            value={editContent}
            onChange={(event) => {
              if (!readOnly) {
                setEditContent(event.target.value);
              }
            }}
            style={{
              width: "100%",
              minHeight: "400px",
              resize: "vertical",
            }}
            bordered
            readOnly={readOnly}
          />
        </div>
      )}
    </Modal>
  );
}
