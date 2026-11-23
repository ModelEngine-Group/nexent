// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useEffect, useState } from "react";
import { Alert, Button, Spin } from "antd";
import JSZip from "jszip";
import { useTranslation } from "react-i18next";
import type { SkillRepositoryListingDetail } from "@/types/skillRepository";
import type { SkillFileContent } from "@/types/skill";
import SkillReadOnlyDetail from "@/components/skill/SkillReadOnlyDetail";
import SkillPanelTitle from "@/components/skill/SkillPanelTitle";
import log from "@/lib/logger";
import ResourceDetail from "@/components/resource/ResourceDetail";
import panel from "@/components/resource/resource-panel.module.css";
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
  onInstall,
  installDisabled,
  installing,
  installed,
}: {
  open: boolean;
  detail?: SkillRepositoryListingDetail;
  isLoading: boolean;
  isError: boolean;
  isFetching: boolean;
  onClose: () => void;
  onRetry: () => void;
  onInstall?: () => void;
  installDisabled?: boolean;
  installing?: boolean;
  installed?: boolean;
}) {
  const { t, i18n } = useTranslation("common");
  const displayName = useUserDisplayName();
  const [files, setFiles] = useState<SkillFileContent[]>([]);
  const [loadingFiles, setLoadingFiles] = useState(false);
  const [fileError, setFileError] = useState(false);
  const [validatedArchive, setValidatedArchive] = useState<string>();
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- Reset the previous archive before reading the selected listing.
    setFiles([]);
    setFileError(false);
    setValidatedArchive(undefined);
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
          (firstFolder === detail.name ||
            entries.some(
              (entry) =>
                entry.name.toLowerCase() ===
                `${firstFolder}/skill.md`.toLowerCase()
            )) &&
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
        if (!cancelled) {
          setFiles(result);
          setValidatedArchive(detail.skill_zip_base64);
        }
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
        ? t("skillRepository.detail.official")
        : source || "—";
  const tags = detail?.tags ?? [];
  const archiveReady =
    !loadingFiles &&
    !fileError &&
    !!validatedArchive &&
    validatedArchive === detail?.skill_zip_base64;
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
        <div className="-mx-6 flex min-h-0 flex-1 flex-col text-body-2 leading-[22px] text-foreground">
          <header className="flex shrink-0 items-center gap-3 border-b border-border px-6 pb-4 pr-14">
            <SkillPanelTitle
              name={detail.name}
              tags={tags}
              icon={detail.icon}
              subtitle={
                <span className="rounded bg-primary/10 px-1.5 text-primary">
                  {sourceLabel}
                </span>
              }
            />
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
                    {t("skillRepository.detail.referencedBy")}
                  </dt>
                  <dd>
                    {detail.agent_reference_count == null
                      ? t("resourceCenter.notRecorded")
                      : t("skillRepository.detail.agentReferenceCount", {
                          count: detail.agent_reference_count,
                        })}
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
                  sourcePreview
                  source={sourceLabel}
                  tags={tags}
                  description={detail.description ?? ""}
                  files={files}
                />
              </Spin>
            </section>
          </div>
          <footer className={`${panel.detailFooter} ${panel.footerActions}`}>
            <Button className="min-w-[88px]" onClick={onClose}>
              {t("common.close")}
            </Button>
            {onInstall && (
              <Button
                type="primary"
                className="min-w-[88px] max-w-[200px]"
                onClick={onInstall}
                disabled={installed || installDisabled || !archiveReady}
                loading={installing}
              >
                {t(
                  installed
                    ? "resourceCenter.installed"
                    : "resourceCenter.install"
                )}
              </Button>
            )}
          </footer>
        </div>
      ) : null}
    </ResourceDetail>
  );
}
