// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useEffect, useState } from "react";
import { Alert, Button, Spin } from "antd";
import JSZip from "jszip";
import { useTranslation } from "react-i18next";
import { Modal } from "antd";
import type { SkillRepositoryListingDetail } from "@/types/skillRepository";
import type { SkillFileContent } from "@/types/skill";
import SkillReadOnlyDetail from "./SkillReadOnlyDetail";
import log from "@/lib/logger";

export default function RepositorySkillDetail({
  open,
  detail,
  isLoading,
  isError,
  isFetching,
  onClose,
  onRetry,
}: {
  open: boolean;
  detail?: SkillRepositoryListingDetail;
  isLoading: boolean;
  isError: boolean;
  isFetching: boolean;
  onClose: () => void;
  onRetry: () => void;
}) {
  const { t } = useTranslation("common");
  const [files, setFiles] = useState<SkillFileContent[]>([]);
  const [loadingFiles, setLoadingFiles] = useState(false);
  const [fileError, setFileError] = useState(false);
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- Reset the previous archive before reading the selected listing.
    setFiles([]);
    setFileError(false);
    setLoadingFiles(true);
    void (async () => {
      try {
        if (!detail?.skill_zip_base64) {
          const content = detail?.skill_info_json?.content;
          if (!cancelled && typeof content === "string")
            setFiles([{ path: "SKILL.md", content }]);
          return;
        }
        const zip = await JSZip.loadAsync(detail.skill_zip_base64, {
          base64: true,
        });
        const entries = Object.values(zip.files).filter((entry) => !entry.dir);
        const firstFolder = entries[0]?.name.split("/")[0];
        const stripRoot =
          firstFolder &&
          entries.every((entry) => entry.name.startsWith(`${firstFolder}/`));
        const prefix = stripRoot ? `${firstFolder}/` : "";
        const result = await Promise.all(
          entries.map(async (entry): Promise<SkillFileContent> => {
            const path = entry.name.slice(prefix.length);
            if (
              !/\.(md|txt|json|csv|html?|xml|ya?ml|toml|ini|py|js|jsx|ts|tsx|sh|css|sql)$/i.test(
                path
              )
            )
              return { path, content: "", status: "unsupported" };
            try {
              const bytes = await entry.async("uint8array");
              const content = new TextDecoder("utf-8", { fatal: true }).decode(
                bytes
              );
              return { path, content, status: "readable" };
            } catch {
              return { path, content: "", status: "read_error" };
            }
          })
        );
        if (!cancelled) setFiles(result);
      } catch (error) {
        log.error("Failed to read repository skill files", error);
        if (!cancelled) setFileError(true);
      } finally {
        if (!cancelled) setLoadingFiles(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, detail]);
  const source = detail?.source;
  return (
    <Modal
      centered
      open={open}
      closable={{ "aria-label": t("common.close") }}
      width={860}
      styles={{
        body: { maxHeight: "calc(100dvh - 200px)", overflowY: "auto" },
      }}
      title={t("skillManagement.detail.title")}
      cancelText={t("common.cancel")}
      okText={t("common.confirm")}
      onCancel={onClose}
      onOk={onClose}
    >
      {isLoading ? (
        <div className="flex min-h-64 items-center justify-center">
          <Spin />
        </div>
      ) : isError ? (
        <div className="space-y-3">
          <Alert type="error" title={t("skillRepository.detail.loadError")} />
          <Button onClick={onRetry} loading={isFetching}>
            {t("repository.common.retry")}
          </Button>
        </div>
      ) : detail ? (
        <Spin spinning={loadingFiles}>
          {fileError && (
            <Alert
              type="warning"
              title={t("skillManagement.detail.fileReadFailed")}
              className="mb-3"
            />
          )}
          <SkillReadOnlyDetail
            name={detail.name}
            source={
              source === "custom" || source === "repository"
                ? t(`skillRepository.source.${source}`)
                : source === "official"
                  ? t("skillPool.group.official")
                  : source || "—"
            }
            tags={detail.tags ?? []}
            description={detail.description ?? ""}
            files={files}
          />
        </Spin>
      ) : null}
    </Modal>
  );
}
