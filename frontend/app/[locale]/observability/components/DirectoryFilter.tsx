// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useEffect, useMemo, useState } from "react";
import { useInfiniteQuery } from "@tanstack/react-query";
import { Select, Spin } from "antd";
import { useTranslation } from "react-i18next";
import { trajectoryService } from "@/services/trajectoryService";
import { StandardButton } from "@/components/common/StandardButton";
import type {
  DirectoryOption,
  TrajectoryFacet,
  TrajectoryFilters,
} from "@/types/trajectory";

export function DirectoryFilter({
  facet,
  filters,
  value,
  onChange,
}: {
  facet: TrajectoryFacet;
  filters: TrajectoryFilters;
  value?: string;
  onChange: (option?: DirectoryOption) => void;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [keyword, setKeyword] = useState("");
  const [recent, setRecent] = useState<DirectoryOption[]>([]);
  useEffect(() => {
    const timer = setTimeout(() => setKeyword(search.trim()), 300);
    return () => clearTimeout(timer);
  }, [search]);
  const query = useInfiniteQuery({
    queryKey: ["trajectory-facet", facet, filters, keyword],
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam, signal }) =>
      trajectoryService.facets(facet, filters, keyword, pageParam, signal),
    getNextPageParam: (page) => page.next_cursor ?? undefined,
    enabled: open && search.trim() === keyword,
    retry: false,
    gcTime: 0,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    maxPages: 10,
  });
  const options = useMemo(() => {
    const items = [
      ...(!keyword ? recent : []),
      ...(query.data?.pages.flatMap((page) => page.items) ?? []),
    ];
    return [
      ...new Map(
        items.map((option) => [
          JSON.stringify([option.tenant_id, option.id]),
          option,
        ])
      ).values(),
    ];
  }, [keyword, recent, query.data]);
  const selected = options.find((option) => option.id === value);
  const displayName = (option: DirectoryOption) =>
    facet === "models"
      ? option.name || option.id
      : option.name && option.name !== option.id
        ? option.name
        : t("trajectory.unnamedOption");
  const loading = query.isFetching || search.trim() !== keyword;
  return (
    <Select
      className="trajectory-directory"
      aria-label={t(`trajectory.${facet}`)}
      placeholder={t(`trajectory.all.${facet}`)}
      allowClear
      showSearch={{
        filterOption: false,
        onSearch: setSearch,
        searchValue: search,
      }}
      value={
        value
          ? {
              value: selected
                ? JSON.stringify([selected.tenant_id, selected.id])
                : value,
              label: selected
                ? displayName(selected)
                : t("trajectory.unnamedOption"),
            }
          : undefined
      }
      labelInValue
      onOpenChange={setOpen}
      onChange={(entry) => {
        const option = options.find(
          (item) => JSON.stringify([item.tenant_id, item.id]) === entry?.value
        );
        if (option)
          setRecent((previous) =>
            [
              option,
              ...previous.filter(
                (item) =>
                  item.id !== option.id || item.tenant_id !== option.tenant_id
              ),
            ].slice(0, 5)
          );
        setSearch("");
        setKeyword("");
        onChange(option);
      }}
      options={options.map((option) => ({
        value: JSON.stringify([option.tenant_id, option.id]),
        label: (
          <div className="py-1">
            <div>{displayName(option)}</div>
            {option.tenant_name && option.tenant_name !== option.tenant_id && (
              <div className="text-xs text-gray-500">{option.tenant_name}</div>
            )}
          </div>
        ),
      }))}
      notFoundContent={
        loading ? (
          <Spin size="small" />
        ) : query.isError ? (
          <StandardButton onClick={() => void query.refetch()}>
            {t("trajectory.retry")}
          </StandardButton>
        ) : (
          t("trajectory.noOptions")
        )
      }
      popupRender={(menu) => (
        <>
          {menu}
          {query.hasNextPage && (
            <StandardButton
              loading={query.isFetchingNextPage}
              onClick={() => void query.fetchNextPage()}
            >
              {t("trajectory.loadMore")}
            </StandardButton>
          )}
          {query.isError && options.length > 0 && (
            <StandardButton onClick={() => void query.refetch()}>
              {t("trajectory.retry")}
            </StandardButton>
          )}
        </>
      )}
      onPopupScroll={(event) => {
        const target = event.currentTarget;
        if (
          target.scrollTop + target.clientHeight >= target.scrollHeight - 24 &&
          query.hasNextPage &&
          !query.isFetching
        )
          void query.fetchNextPage();
      }}
      loading={loading && open}
    />
  );
}
