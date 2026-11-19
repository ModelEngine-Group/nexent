// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useEffect, useState } from "react";
import { Alert, Button, Spin } from "antd";
import JSZip from "jszip";
import { useTranslation } from "react-i18next";
import type { SkillRepositoryListingDetail } from "@/types/skillRepository";
import type { SkillFileContent } from "@/types/skill";
import SkillReadOnlyDetail from "./SkillReadOnlyDetail";
import SkillTypeIcon from "./SkillTypeIcon";
import log from "@/lib/logger";
import ResourceDetail from "@/components/resource/ResourceDetail";
import { useUserDisplayName } from "@/hooks/auth/useUserDisplayName";
import { formatDateTimeLocale } from "@/lib/date";

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
  const { t, i18n } = useTranslation("common");
  const displayName = useUserDisplayName();
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
  const sourceLabel =
    source === "custom" || source === "repository"
      ? t(`skillRepository.source.${source}`)
      : source === "official"
        ? t("skillPool.group.official")
        : source || "—";
  const tags = detail?.tags ?? [];
  return (
    <ResourceDetail
      open={open}
      onClose={onClose}
      width={560}
      className="skill-detail-modal [&_.ant-modal-close]:!z-20 [&_.ant-modal-content]:!overflow-hidden [&_.ant-modal-content]:!rounded-2xl [&_.ant-modal-content]:!p-0"
      bodyStyle={{ padding: 0 }}
    >
      {isLoading ? (
        <div className="flex min-h-64 items-center justify-center">
          <Spin size="large" />
        </div>
      ) : isError ? (
        <div className="flex min-h-64 flex-col items-center justify-center gap-3 text-center">
          <p className="text-sm text-muted-foreground">
            {t("skillRepository.detail.loadError")}
          </p>
          <Button type="primary" onClick={onRetry} loading={isFetching}>
            {t("repository.common.retry")}
          </Button>
        </div>
      ) : detail ? (
        <div className="-mx-6 flex min-h-0 flex-1 flex-col text-sm leading-[22px] text-foreground">
          <header className="flex shrink-0 items-center gap-3 border-b border-border px-6 pb-4 pr-14">
            <div className="shrink-0">
              <SkillTypeIcon
                className="rounded"
                name={detail.name}
                tags={tags}
                icon={detail.icon}
              />
            </div>
            <div className="min-w-0 flex-1">
              <h2 className="break-words text-xl font-medium leading-7">
                {detail.name}
              </h2>
              <span className="mt-1 inline-block rounded bg-primary/10 px-1.5 text-xs text-primary">
                {sourceLabel}
              </span>
            </div>
          </header>
          <div className="repository-detail-body min-h-0 flex-1 overflow-y-auto">
            <section className="space-y-3 border-b border-border px-6 py-5">
              <h3 className="font-semibold">
                {t("resourceCenter.agentDetail.basicInfo")}
              </h3>
              <p
                className={`whitespace-pre-wrap break-words ${detail.description ? "" : "text-muted-foreground"}`}
              >
                {detail.description ||
                  t("skillRepository.common.noDescription")}
              </p>
              {tags.length > 0 ? (
                <ul
                  aria-label={t("agentRepository.mine.detail.tags")}
                  className="flex flex-wrap gap-1.5"
                >
                  {tags.map((tag) => (
                    <li
                      key={tag}
                      className="max-w-full break-words rounded bg-primary/5 px-2 text-xs leading-5 text-muted-foreground"
                    >
                      {tag}
                    </li>
                  ))}
                </ul>
              ) : null}
              <dl className="grid grid-cols-[minmax(5rem,max-content)_minmax(0,1fr)] gap-x-3 gap-y-1">
                <div className="contents">
                  <dt className="text-muted-foreground">
                    {t("agentRepository.mine.detail.author")}
                  </dt>
                  <dd className="min-w-0 [overflow-wrap:anywhere]">
                    {displayName(
                      detail.author_cas_username,
                      detail.author ?? ""
                    ) || t("resourceCenter.notRecorded")}
                  </dd>
                </div>
                <div className="contents">
                  <dt className="text-muted-foreground">
                    {t("resourceCenter.publishedAt")}
                  </dt>
                  <dd className="min-w-0 [overflow-wrap:anywhere]">
                    {detail.published_at ? (
                      <time dateTime={detail.published_at}>
                        {formatDateTimeLocale(
                          detail.published_at,
                          i18n?.language
                        )}
                      </time>
                    ) : (
                      t("resourceCenter.notRecorded")
                    )}
                  </dd>
                </div>
                <div className="contents">
                  <dt className="text-muted-foreground">
                    {t("skillRepository.detail.downloads")}
                  </dt>
                  <dd className="min-w-0 [overflow-wrap:anywhere]">
                    {(detail.downloads ?? 0).toLocaleString()}
                  </dd>
                </div>
              </dl>
            </section>
            <section className="space-y-3 px-6 py-5">
              <h3 className="font-semibold">
                {t("skillRepository.detail.skillFiles")}
              </h3>
              <Spin spinning={loadingFiles}>
                {fileError && (
                  <Alert
                    type="warning"
                    title={t("skillManagement.detail.fileReadFailed")}
                    className="mb-3"
                  />
                )}
                <SkillReadOnlyDetail
                  hideMetadata
                  name={detail.name}
                  source={sourceLabel}
                  tags={tags}
                  description={detail.description ?? ""}
                  files={files}
                />
              </Spin>
            </section>
          </div>
          <footer className="-mx-6 flex shrink-0 items-center justify-end gap-2 border-t border-border bg-background px-6 py-3">
            <Button onClick={onClose}>{t("common.close")}</Button>
          </footer>
        </div>
      ) : null}
    </ResourceDetail>
  );
}
