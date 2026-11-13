// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { Select } from "antd";
import { LayoutGrid, List } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useRepositoryPresentation } from "@/hooks/useRepositoryPresentation";

/** Keep repository display controls on the same row as search and filters. */
export default function RepositoryDisplayControls({
  showSort = true,
}: {
  showSort?: boolean;
}) {
  const presentation = useRepositoryPresentation();
  const { t } = useTranslation("common");
  if (!presentation) return null;
  return (
    <div className="ml-auto flex shrink-0 items-center gap-3">
      {showSort && presentation.query?.get("view") !== "mine" && (
        <Select
          aria-label={t("agentRepository.sort.label")}
          value={
            presentation.query?.get("sort") === "latest" ? "latest" : "default"
          }
          options={[
            { value: "default", label: t("resourceCenter.defaultSort") },
            { value: "latest", label: t("agentRepository.sort.latest") },
          ]}
          onChange={(value) =>
            presentation.updateQuery?.({ sort: value, page: "1" })
          }
          className="min-w-28"
        />
      )}
      <div
        role="group"
        aria-label={t("resourceCenter.layout")}
        className="inline-flex rounded-md border border-gray-200 bg-white"
      >
        {(
          [
            ["list", List, t("resourceCenter.list")],
            ["cards", LayoutGrid, t("resourceCenter.cards")],
          ] as const
        ).map(([layout, Icon, label]) => {
          const active = presentation.layout === layout;
          return (
            <button
              key={layout}
              type="button"
              title={label}
              aria-label={label}
              aria-pressed={active}
              className={`inline-flex size-[30px] cursor-pointer items-center justify-center first:rounded-l-[5px] last:rounded-r-[5px] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600 ${active ? "bg-[#0067d1] text-white" : "text-gray-600 hover:bg-gray-100"}`}
              onClick={() => {
                if (active) return;
                presentation.updateQuery?.({
                  layout,
                  page: "1",
                  page_size: null,
                });
              }}
            >
              <Icon size={16} aria-hidden />
            </button>
          );
        })}
      </div>
    </div>
  );
}

export function AgentRepositorySort() {
  const presentation = useRepositoryPresentation();
  const { t } = useTranslation("common");
  const sort = presentation?.query?.get("sort");
  return (
    <Select
      aria-label={t("agentRepository.sort.label")}
      className="w-[160px] max-w-full"
      value={sort === "latest" || sort === "downloads" ? sort : "default"}
      options={[
        { value: "default", label: t("resourceCenter.agentSortDefault") },
        { value: "latest", label: t("resourceCenter.agentSortTime") },
        { value: "downloads", label: t("resourceCenter.agentSortCopies") },
      ]}
      onChange={(sort) => presentation?.updateQuery?.({ sort, page: "1" })}
    />
  );
}
