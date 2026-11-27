// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { hasRole } from "@/lib/roles";

import React, {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";

import {
  Alert,
  Button,
  Card,
  Checkbox,
  Dropdown,
  InputNumber,
  Popover,
  Select,
  Spin,
  Tag,
  Tooltip,
  Input,
  Pagination,
} from "antd";
import {
  SyncOutlined,
  SettingOutlined,
  FilterOutlined,
} from "@ant-design/icons";
import {
  ChevronDown,
  PencilRuler,
  Eye,
  Glasses,
  CircleOff,
  Search,
  Clock3,
  FolderOpen,
  ListChecks,
  Plus,
  Tag as TagIcon,
  Trash2,
  X,
} from "lucide-react";
import { Can } from "@/components/permission/Can";
import { usePermission } from "@/hooks/permission/usePermission";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { useGroupList } from "@/hooks/group/useGroupList";
import KnowledgeBaseBatchDeleteDialog from "./KnowledgeBaseBatchDeleteDialog";
import PersonalKnowledgeBaseCapacityBar from "./PersonalKnowledgeBaseCapacityBar";
import TagFilterControls from "@/components/tag/TagFilterControls";
import ResourceTagChips from "@/components/tag/ResourceTagChips";
import { useTagDefinitions, useTagLibraries } from "@/hooks/useTagManagement";
import { tagManagementApi } from "@/services/tagManagementService";
import type { TagResourcePredicate } from "@/types/tagManagement";

import { KnowledgeBase } from "@/types/knowledgeBase";
import { KB_TAG_VARIANTS } from "@/const/knowledgeBaseLayout";
import knowledgeBaseService from "@/services/knowledgeBaseService";
import { formatDateOrFallback } from "@/lib/date";
import { formatFileSize } from "@/lib/utils";
import { getKnowledgeBaseQuotaDisplay } from "@/lib/knowledgeBaseQuota";
import {
  getTagDefinitionDisplayName,
  getTagValueDisplayName,
} from "@/lib/systemTagLabels";

import log from "@/lib/logger";
import type { KBQuotaStatus, QuotaUsageResponse } from "@/types/quota";

function KnowledgeTagRow({ children }: { children: React.ReactNode }) {
  const { t } = useTranslation("common");
  const rowRef = useRef<HTMLDivElement>(null);
  const moreRef = useRef<HTMLButtonElement>(null);
  const [layout, setLayout] = useState<{
    visibleCount: number | null;
    reservedWidth: number;
  }>({ visibleCount: null, reservedWidth: 0 });
  useLayoutEffect(() => {
    const row = rowRef.current;
    if (!row) return;
    const measure = () => {
      const content = row.firstElementChild as HTMLElement;
      if (!content || row.clientWidth === 0) return;
      const candidates = Array.from(content.children).flatMap((item) => {
        const nestedTags = Array.from(
          item.querySelectorAll<HTMLElement>(".ant-tag")
        );
        return nestedTags.length > 0 ? nestedTags : [item as HTMLElement];
      });
      candidates.forEach((item) => item.style.removeProperty("display"));
      const widths = candidates.map(
        (item) => item.getBoundingClientRect().width
      );
      const gap = 4;
      const totalWidth =
        widths.reduce((sum, width) => sum + width, 0) +
        Math.max(0, widths.length - 1) * gap;
      if (totalWidth <= row.clientWidth) {
        candidates.forEach((item) => item.style.removeProperty("display"));
        setLayout((current) =>
          current.visibleCount === candidates.length &&
          current.reservedWidth === 0
            ? current
            : { visibleCount: candidates.length, reservedWidth: 0 }
        );
        return;
      }
      const moreWidth = moreRef.current?.getBoundingClientRect().width || 40;
      const reservedWidth = moreWidth + gap;
      const availableWidth = Math.max(0, row.clientWidth - reservedWidth);
      let usedWidth = 0;
      let count = 0;
      for (const width of widths) {
        const nextWidth = usedWidth + (count > 0 ? gap : 0) + width;
        if (nextWidth > availableWidth) break;
        usedWidth = nextWidth;
        count += 1;
      }
      candidates.forEach((item, index) => {
        if (index >= count)
          item.style.setProperty("display", "none", "important");
      });
      setLayout((current) =>
        current.visibleCount === count &&
        current.reservedWidth === reservedWidth
          ? current
          : { visibleCount: count, reservedWidth }
      );
    };
    const resize = new ResizeObserver(measure);
    const mutation = new MutationObserver(measure);
    resize.observe(row);
    mutation.observe(row.firstElementChild!, {
      childList: true,
      subtree: true,
    });
    measure();
    return () => {
      resize.disconnect();
      mutation.disconnect();
    };
  }, [children]);
  const totalCount = (() => {
    const content = rowRef.current?.firstElementChild;
    if (!content) return 0;
    return Array.from(content.children).reduce((count, item) => {
      const nestedTags = item.querySelectorAll(".ant-tag").length;
      return count + (nestedTags > 0 ? nestedTags : 1);
    }, 0);
  })();
  const hasOverflow =
    layout.visibleCount !== null && layout.visibleCount < totalCount;
  return (
    <div
      ref={rowRef}
      data-testid="knowledge-tags"
      className="flex h-6 min-w-0 items-center gap-1"
    >
      <div
        className="flex w-max min-w-0 flex-none flex-nowrap items-center gap-1 overflow-hidden [&>*]:shrink-0"
        style={{
          maxWidth: hasOverflow
            ? `calc(100% - ${layout.reservedWidth}px)`
            : "100%",
        }}
      >
        {children}
      </div>
      <Popover
        open={hasOverflow ? undefined : false}
        trigger="hover"
        placement="topRight"
        content={
          <div
            className="flex max-w-[360px] flex-wrap items-center gap-1 [&_.knowledge-tag-more-wrap]:!contents"
            onClick={(event) => event.stopPropagation()}
          >
            {children}
          </div>
        }
      >
        <button
          ref={moreRef}
          type="button"
          aria-hidden={!hasOverflow}
          tabIndex={hasOverflow ? 0 : -1}
          className={`shrink-0 rounded-full border border-gray-200 bg-gray-50 px-2 py-0.5 text-xs text-gray-600 ${hasOverflow ? "relative" : "invisible absolute"}`}
          onClick={(event) => event.stopPropagation()}
        >
          {t("chat.composer.more")}
        </button>
      </Popover>
    </div>
  );
}

const CARD_TAG_CLASSNAME =
  "!m-0 !inline-flex !h-[22px] !max-w-[120px] !shrink-0 !items-center !rounded-full !border-gray-200 !bg-gray-50 !px-2 !py-0 !text-xs !font-normal !leading-5 !text-gray-600";

function KnowledgeValueTags({ values }: { values: string[] }) {
  return (
    <>
      {values.map((value, index) => (
        <Tooltip key={`${value}-${index}`} title={value}>
          <Tag className={CARD_TAG_CLASSNAME} aria-label={value}>
            <span className="min-w-0 truncate">{value}</span>
          </Tag>
        </Tooltip>
      ))}
    </>
  );
}

interface KnowledgeBaseListProps {
  knowledgeBases: KnowledgeBase[];
  activeKnowledgeBase: KnowledgeBase | null;
  isLoading?: boolean;
  syncLoading?: boolean;
  totalCount?: number;
  page?: number;
  pageSize?: number;
  onPageChange?: (page: number) => void;
  onPageSizeChange?: (size: number) => void;
  error?: string | null;
  onRetry?: () => void;
  availableSources?: string[];
  availableModels?: string[];
  quotaUsage?: QuotaUsageResponse | null;
  serverFiltered?: boolean;
  initialLoadPending?: boolean;
  onClick: (kb: KnowledgeBase) => void;
  onSync: () => void;
  onCreateNew: () => void;
  onDataMateConfig?: () => void;
  showDataMateConfig?: boolean; // Control whether to show DataMate config button
  getModelDisplayName: (modelId: string) => string;
  containerHeight?: string; // Container total height, consistent with DocumentList
  onKnowledgeBaseChange?: () => void; // Callback when knowledge base switches
  onCatalogRefresh?: () => void; // Callback to reload the catalog page after tag changes
  // Optional controlled search / filter props (if parent wants to control filters)
  tagFilter?: TagResourcePredicate[];
  onTagFilterChange?: (values: TagResourcePredicate[]) => void;
  searchQuery?: string;
  onSearchChange?: (value: string) => void;
  sourceFilter?: string | string[];
  onSourceFilterChange?: (values: string[] | string) => void;
  modelFilter?: string | string[];
  onModelFilterChange?: (values: string[] | string) => void;
}

const KnowledgeBaseList: React.FC<KnowledgeBaseListProps> = ({
  knowledgeBases,
  activeKnowledgeBase,
  isLoading = false,
  syncLoading = false,
  totalCount = knowledgeBases.length,
  page = 1,
  pageSize = 12,
  onPageChange,
  onPageSizeChange,
  error,
  onRetry,
  availableSources: availableSourceOptions,
  availableModels: availableModelOptions,
  quotaUsage = null,
  serverFiltered = false,
  initialLoadPending = false,
  onClick,
  onSync,
  onCreateNew,
  onDataMateConfig,
  showDataMateConfig = false,
  getModelDisplayName,
  containerHeight = "70vh", // Default container height consistent with DocumentList
  onKnowledgeBaseChange, // New: callback function when knowledge base switches
  onCatalogRefresh,
  tagFilter,
  onTagFilterChange,
  searchQuery,
  onSearchChange,
  sourceFilter,
  onSourceFilterChange,
  modelFilter,
  onModelFilterChange,
}) => {
  const { t } = useTranslation();

  // Get user info for tenant ID
  const { user } = useAuthorizationContext();
  const { isReady: permissionsReady, can } = usePermission();
  const tenantId = user?.tenantId || null;
  const showPersonalCapacity = hasRole(user, "USER");
  const quotaMap = useMemo(() => {
    const map = new Map<string, KBQuotaStatus>();
    quotaUsage?.breakdown?.forEach((quota) => {
      map.set(quota.index_name, quota);
    });
    return map;
  }, [quotaUsage]);
  const gridRef = useRef<HTMLDivElement | null>(null);
  const [gridColumnCount, setGridColumnCount] = useState(1);
  const [jumpPage, setJumpPage] = useState<number | null>(null);
  const [batchMode, setBatchMode] = useState(false);
  const [batchSelection, setBatchSelection] = useState<string[]>([]);
  const [batchFailures, setBatchFailures] = useState<string[]>([]);
  const [batchDeleteTargets, setBatchDeleteTargets] = useState<KnowledgeBase[]>(
    []
  );
  const canBatchDelete = permissionsReady && can("kb:delete");
  const isBatchMode = batchMode && canBatchDelete;

  // Fetch groups for group name mapping
  const { data: groupData } = useGroupList(tenantId);
  const groups = groupData?.groups || [];

  // Create group name mapping from group_id to group_name
  const groupNameMap = useMemo(() => {
    const map = new Map<number, string>();
    groups.forEach((group) => {
      map.set(group.group_id, group.group_name);
    });
    return map;
  }, [groups]);

  // Get group names for knowledge base
  const getGroupNames = (groupIds?: number[]) => {
    if (!groupIds || groupIds.length === 0) return [];
    return groupIds
      .map((id) => groupNameMap.get(id))
      .filter((name): name is string => !!name);
  };

  // Get permission icon based on ingroup_permission type
  const getPermissionIcon = (permission: string) => {
    const iconProps = {
      size: 14,
      className: "text-gray-500",
    };

    switch (permission) {
      case "EDIT":
        return <PencilRuler {...iconProps} />;
      case "READ_ONLY":
        return <Eye {...iconProps} />;
      case "PRIVATE":
        return <Glasses {...iconProps} />;
      default:
        return <CircleOff {...iconProps} />;
    }
  };

  // Get permission tooltip key
  const getPermissionTooltipKey = (permission: string) => {
    return `knowledgeBase.ingroup.permission.${permission || "DEFAULT"}`;
  };

  const hasIndexedDocumentsAndChunks = (kb: KnowledgeBase) => {
    return (kb.documentCount || 0) > 0 && (kb.chunkCount || 0) > 0;
  };

  // Search and filter states
  const [searchKeyword, setSearchKeyword] = useState("");
  const [selectedSources, setSelectedSources] = useState<string[]>([]);
  const [selectedModels, setSelectedModels] = useState<string[]>([]);

  const [internalTagPredicates, setInternalTagPredicates] = useState<
    TagResourcePredicate[]
  >([]);
  const tagPredicates = tagFilter ?? internalTagPredicates;
  const setTagPredicates = onTagFilterChange ?? setInternalTagPredicates;
  const [matchedTagIds, setMatchedTagIds] = useState<Set<string> | null>(null);
  // Tag metadata is only read after the user opens a tag-related UI.
  const [tagsUiRequested, setTagsUiRequested] = useState(false);
  const {
    data: tagLibraries,
    loading: tagLibrariesLoading,
    error: tagLibrariesError,
    refresh: refreshTagLibraries,
  } = useTagLibraries({ enabled: tagsUiRequested });
  const defaultLibrary =
    tagLibraries?.find(
      (library) => library.bucket_key === "default_resource"
    ) ?? null;
  const {
    data: assignDefinitions,
    loading: assignDefinitionsLoading,
    error: assignDefinitionsError,
    refresh: refreshAssignDefinitions,
  } = useTagDefinitions(defaultLibrary?.bucket_id ?? null, {
    enabled: tagsUiRequested,
  });

  const [tagCandidates, setTagCandidates] = useState<KnowledgeBase[] | null>(
    null
  );
  const [tagLoading, setTagLoading] = useState(false);
  const [tagError, setTagError] = useState(false);
  const [tagRetry, setTagRetry] = useState(0);
  // Effective (controlled or uncontrolled) values
  const effectiveSearchKeyword =
    typeof searchQuery !== "undefined" ? searchQuery : searchKeyword;
  const effectiveSelectedSources = useMemo(
    () =>
      sourceFilter === undefined
        ? selectedSources
        : Array.isArray(sourceFilter)
          ? sourceFilter
          : sourceFilter
            ? [sourceFilter]
            : [],
    [sourceFilter, selectedSources]
  );
  const effectiveSelectedModels = useMemo(
    () =>
      modelFilter === undefined
        ? selectedModels
        : Array.isArray(modelFilter)
          ? modelFilter
          : modelFilter
            ? [modelFilter]
            : [],
    [modelFilter, selectedModels]
  );
  const quickTagOptions = (assignDefinitions ?? [])
    .filter((definition) => definition.status === "active")
    .flatMap((definition) =>
      (definition.values ?? [])
        .filter((value) => value.status === "active")
        .map((value) => ({
          key: `${definition.definition_id}:${value.value_id}`,
          label:
            definition.selection_mode === "no_value"
              ? getTagDefinitionDisplayName(
                  definition.definition_key,
                  definition.definition_name,
                  t
                )
              : getTagValueDisplayName(
                  definition.definition_key,
                  value.display_value,
                  t
                ),
          predicate: {
            definition_id: definition.definition_id,
            value_ids: [value.value_id],
          },
        }))
    );
  const quickTagKey =
    tagPredicates.length === 1 && tagPredicates[0].value_ids?.length === 1
      ? `${tagPredicates[0].definition_id}:${tagPredicates[0].value_ids[0]}`
      : null;
  const quickTag = quickTagOptions.find(({ key }) => key === quickTagKey);
  const allTagsLabel = t("knowledgeBase.tagFilter.all");
  const quickTagStatus =
    tagLibrariesError || assignDefinitionsError
      ? { key: "retry", label: t("repository.common.retry") }
      : !tagsUiRequested || tagLibrariesLoading || assignDefinitionsLoading
        ? { key: "loading", label: t("common.loading"), disabled: true }
        : quickTagOptions.length === 0
          ? {
              key: "empty",
              label: t("tagManagement.empty.noActiveDefinitions"),
              disabled: true,
            }
          : null;

  useEffect(() => {
    if (tagPredicates.length === 0) {
      setMatchedTagIds(null);
      setTagCandidates(null);
      setTagLoading(false);
      setTagError(false);
      return;
    }
    let cancelled = false;
    setTagLoading(true);
    setTagError(false);
    const loadMatches = async () => {
      let candidates = knowledgeBases;
      if (serverFiltered) {
        candidates = [];
        let offset = 0;
        for (;;) {
          const result = await knowledgeBaseService.getKnowledgeBasesInfo(
            true,
            false,
            null,
            null,
            {
              keyword: effectiveSearchKeyword,
              sources: effectiveSelectedSources,
              models: effectiveSelectedModels,
              offset,
              limit: 100,
            },
            { strict: true }
          );
          if (cancelled) return;
          candidates.push(...result.knowledgeBases);
          if (!result.hasMore) break;
          if (result.nextOffset == null || result.nextOffset <= offset) {
            throw new Error("Knowledge catalog pagination did not advance");
          }
          offset = result.nextOffset;
        }
      }
      const unique = [...new Map(candidates.map((kb) => [kb.id, kb])).values()];
      const result = await tagManagementApi.filterResourceIds(
        "knowledge_base",
        unique.map((kb) => String(kb.id)),
        tagPredicates
      );
      if (!cancelled) {
        setTagCandidates(unique);
        setMatchedTagIds(new Set(result.matched_resource_ids));
      }
    };
    void loadMatches()
      .catch((failure) => {
        if (!cancelled) {
          log.error("Knowledge catalog tag filtering failed", failure);
          setTagError(true);
        }
      })
      .finally(() => {
        if (!cancelled) setTagLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [
    knowledgeBases,
    serverFiltered,
    tagPredicates,
    effectiveSearchKeyword,
    effectiveSelectedSources,
    effectiveSelectedModels,
    tagRetry,
  ]);

  // Handlers that respect controlled props
  const handleSearchChange = (value: string) => {
    if (onSearchChange) onSearchChange(value);
    else setSearchKeyword(value);
  };

  const handleSourcesChange = (values: string[]) => {
    if (onSourceFilterChange) onSourceFilterChange(values);
    else setSelectedSources(values);
  };

  const handleModelsChange = (values: string[]) => {
    if (onModelFilterChange) onModelFilterChange(values);
    else setSelectedModels(values);
  };

  const handleKnowledgeBaseSelect = useCallback(
    (kb: KnowledgeBase) => {
      onClick(kb);
      onKnowledgeBaseChange?.();
    },
    [onClick, onKnowledgeBaseChange]
  );

  // Helper to safely extract timestamp for sorting
  const getTimestamp = (value: any): number => {
    if (!value) return 0;
    if (typeof value === "number") return value;
    const t = Date.parse(value);
    return Number.isNaN(t) ? 0 : t;
  };

  // Sort knowledge bases by update time (fallback to creation time), latest first
  const sortedKnowledgeBases = [...(tagCandidates ?? knowledgeBases)].sort(
    (a, b) => {
      const aTime = getTimestamp(a.updatedAt ?? a.createdAt);
      const bTime = getTimestamp(b.updatedAt ?? b.createdAt);
      return bTime - aTime;
    }
  );

  // Calculate available filter options
  const availableSources = useMemo(() => {
    if (availableSourceOptions?.length) return availableSourceOptions;
    const sources = new Set(knowledgeBases.map((kb) => kb.source));
    return Array.from(sources)
      .filter((source) => source)
      .sort();
  }, [availableSourceOptions, knowledgeBases]);

  const availableModels = useMemo(() => {
    if (availableModelOptions?.length) return availableModelOptions;
    const models = new Set(knowledgeBases.map((kb) => kb.embeddingModel));
    return Array.from(models)
      .filter((model) => model && model !== "unknown")
      .sort();
  }, [availableModelOptions, knowledgeBases]);

  // Filter knowledge bases based on search and filters
  const filteredKnowledgeBases = useMemo(() => {
    const result = serverFiltered
      ? sortedKnowledgeBases
      : sortedKnowledgeBases.filter((kb) => {
          // Keyword search: match name, description, or nickname
          const keyword = effectiveSearchKeyword || "";
          const kbName = kb.name || "";
          const kbDescription = kb.description || "";
          const kbNickname = kb.nickname || "";

          const matchesSearch =
            !keyword ||
            kbName.toLowerCase().includes(keyword.toLowerCase()) ||
            kbDescription.toLowerCase().includes(keyword.toLowerCase()) ||
            kbNickname.toLowerCase().includes(keyword.toLowerCase());

          // Source filter
          const matchesSource =
            effectiveSelectedSources.length === 0 ||
            effectiveSelectedSources.includes(kb.source);

          // Model filter
          const matchesModel =
            effectiveSelectedModels.length === 0 ||
            effectiveSelectedModels.includes(kb.embeddingModel);

          const matchesTag =
            matchedTagIds === null || matchedTagIds.has(String(kb.id));
          const matches =
            matchesSearch && matchesSource && matchesModel && matchesTag;

          return matches;
        });

    const tagFilteredResult =
      matchedTagIds === null
        ? result
        : result.filter((knowledgeBase) =>
            matchedTagIds.has(String(knowledgeBase.id))
          );
    return tagFilteredResult;
  }, [
    sortedKnowledgeBases,
    effectiveSearchKeyword,
    effectiveSelectedSources,
    effectiveSelectedModels,
    matchedTagIds,
    serverFiltered,
  ]);

  const filteredTotal =
    tagPredicates.length > 0 || !serverFiltered
      ? filteredKnowledgeBases.length
      : totalCount;
  const pageCount = Math.max(1, Math.ceil(filteredTotal / pageSize));
  const currentPage = Math.min(page, pageCount);
  const pagedKnowledgeBases =
    serverFiltered && tagPredicates.length === 0
      ? filteredKnowledgeBases
      : filteredKnowledgeBases.slice(
          (currentPage - 1) * pageSize,
          currentPage * pageSize
        );
  const loading = isLoading || initialLoadPending || tagLoading;
  const selectionScope = JSON.stringify([
    currentPage,
    pageSize,
    effectiveSearchKeyword,
    effectiveSelectedSources,
    effectiveSelectedModels,
    tagPredicates,
  ]);
  const selectableBatchItems = isBatchMode
    ? pagedKnowledgeBases.filter(
        (kb) =>
          kb.permission !== "READ_ONLY" &&
          (!kb.source ||
            kb.source === "nexent" ||
            kb.source === "elasticsearch")
      )
    : [];
  const selectedBatchItems = selectableBatchItems.filter((kb) =>
    batchSelection.includes(kb.id)
  );

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- A new page or filter discards the previous selection.
    setBatchSelection([]);
    setBatchFailures([]);
  }, [selectionScope, isBatchMode]);

  useEffect(() => {
    if (!loading && !error && !tagError && page > pageCount)
      onPageChange?.(pageCount);
  }, [loading, error, tagError, page, pageCount, onPageChange]);

  useLayoutEffect(() => {
    const grid = gridRef.current;
    if (!grid) return;
    const measure = () =>
      setGridColumnCount(
        Math.max(1, Math.min(4, Math.floor((grid.clientWidth + 16) / 336)))
      );
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(grid);
    return () => observer.disconnect();
  }, []);

  return (
    <div className="flex h-full min-h-0 w-full flex-col overflow-hidden bg-white">
      <header className="flex shrink-0 items-center pb-1 pt-2">
        <h1 className="text-xl font-semibold leading-7 text-[var(--color-text-primary)]">
          {t("sidebar.knowledgeBaseConfig")}
        </h1>
      </header>
      <div
        data-testid="knowledge-catalog-toolbar"
        className="my-4 flex shrink-0 flex-wrap items-center justify-between gap-3"
      >
        <div className="flex min-w-0 flex-[1_1_22rem] items-center gap-2">
          <Input
            aria-label={t("knowledgeBase.catalog.search")}
            placeholder={t("knowledgeBase.catalog.search")}
            prefix={
              <Search
                className="size-4 text-[var(--color-icon-secondary)]"
                aria-hidden
              />
            }
            value={effectiveSearchKeyword}
            onChange={(event) => handleSearchChange(event.target.value)}
            className="!min-w-0 !max-w-96 !flex-1"
            allowClear
          />
          <Dropdown
            trigger={["click"]}
            onOpenChange={(open) => {
              if (open) setTagsUiRequested(true);
            }}
            menu={{
              selectable: true,
              selectedKeys: quickTag
                ? [quickTag.key]
                : tagPredicates.length === 0
                  ? ["all"]
                  : [],
              items: [
                { key: "all", label: allTagsLabel },
                ...quickTagOptions.map(({ key, label }) => ({ key, label })),
                ...(quickTagStatus ? [quickTagStatus] : []),
              ],
              onClick: ({ key }) => {
                if (key === "retry") {
                  if (tagLibrariesError) void refreshTagLibraries();
                  else void refreshAssignDefinitions();
                  return;
                }
                const option = quickTagOptions.find((item) => item.key === key);
                setTagPredicates(option ? [option.predicate] : []);
                onPageChange?.(1);
              },
            }}
          >
            <Button
              className="shrink-0"
              icon={<TagIcon className="size-4" aria-hidden />}
              aria-haspopup="menu"
            >
              <span className="max-w-32 truncate">
                {quickTag?.label ??
                  (tagPredicates.length
                    ? t("knowledgeBase.tagFilter.placeholder")
                    : allTagsLabel)}
              </span>
              <ChevronDown className="size-3 shrink-0" aria-hidden />
            </Button>
          </Dropdown>
          <Popover
            trigger="click"
            placement="bottomRight"
            title={t("knowledgeBase.filter.title")}
            onOpenChange={(open) => {
              if (open) setTagsUiRequested(true);
            }}
            content={
              <div className="w-[300px] max-w-[calc(100vw-48px)] space-y-3">
                {availableSources.length > 0 && (
                  <div>
                    <div className="mb-1 text-xs text-gray-500">
                      {t("knowledgeBase.filter.source")}
                    </div>
                    <Select
                      mode="multiple"
                      placeholder={t("knowledgeBase.filter.source.placeholder")}
                      value={effectiveSelectedSources}
                      onChange={handleSourcesChange}
                      className="w-full"
                      allowClear
                      maxTagCount={2}
                      options={availableSources.map((source) => ({
                        value: source,
                        label: t("knowledgeBase.source." + source, {
                          defaultValue: source,
                        }),
                      }))}
                    />
                  </div>
                )}
                {availableModels.length > 0 && (
                  <div>
                    <div className="mb-1 text-xs text-gray-500">
                      {t("knowledgeBase.filter.model")}
                    </div>
                    <Select
                      mode="multiple"
                      placeholder={t("knowledgeBase.filter.model.placeholder")}
                      value={effectiveSelectedModels}
                      onChange={handleModelsChange}
                      className="w-full"
                      allowClear
                      maxTagCount={2}
                      options={availableModels.map((model) => ({
                        value: model,
                        label: getModelDisplayName(model),
                      }))}
                    />
                  </div>
                )}
                {tagsUiRequested && (
                  <div>
                    <div className="mb-1 text-xs text-gray-500">
                      {t("knowledgeBase.tagFilter.placeholder")}
                    </div>
                    {assignDefinitions ? (
                      <TagFilterControls
                        definitions={assignDefinitions}
                        value={tagPredicates}
                        onChange={(values) => {
                          setTagPredicates(values);
                          onPageChange?.(1);
                        }}
                      />
                    ) : tagLibrariesLoading || assignDefinitionsLoading ? (
                      <div className="flex justify-center py-2">
                        <Spin size="small" />
                      </div>
                    ) : (
                      <Button
                        size="small"
                        block
                        onClick={() => {
                          if (tagLibrariesError) void refreshTagLibraries();
                          else void refreshAssignDefinitions();
                        }}
                      >
                        {t("repository.common.retry")}
                      </Button>
                    )}
                  </div>
                )}
                <Button
                  size="small"
                  block
                  onClick={() => {
                    handleSearchChange("");
                    handleSourcesChange([]);
                    handleModelsChange([]);
                    setTagPredicates([]);
                    onPageChange?.(1);
                  }}
                >
                  {t("knowledgeBase.filter.clear")}
                </Button>
              </div>
            }
          >
            <Button
              className="!h-8"
              aria-label={t("knowledgeBase.filter.button")}
              aria-pressed={
                effectiveSelectedSources.length > 0 ||
                effectiveSelectedModels.length > 0 ||
                tagPredicates.length > 0
              }
              icon={<FilterOutlined />}
              type={
                effectiveSelectedSources.length > 0 ||
                effectiveSelectedModels.length > 0 ||
                tagPredicates.length > 0
                  ? "primary"
                  : "default"
              }
            >
              {t("knowledgeBase.filter.button")}
              {(effectiveSelectedSources.length > 0 ||
                effectiveSelectedModels.length > 0 ||
                tagPredicates.length > 0) && (
                <span className="ml-1">
                  {effectiveSelectedSources.length +
                    effectiveSelectedModels.length +
                    tagPredicates.length}
                </span>
              )}
            </Button>
          </Popover>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {canBatchDelete && (
            <Button
              icon={<ListChecks className="size-4" aria-hidden />}
              aria-pressed={isBatchMode}
              disabled={loading && !isBatchMode}
              onClick={() => setBatchMode(!isBatchMode)}
            >
              {t("knowledgeBase.batch.manage")}
            </Button>
          )}
          <Button
            onClick={onSync}
            loading={syncLoading}
            icon={<SyncOutlined />}
          >
            {t("knowledgeBase.button.sync")}
          </Button>
          {showDataMateConfig && (
            <Button onClick={onDataMateConfig} icon={<SettingOutlined />}>
              {t("knowledgeBase.button.dataMateConfig")}
            </Button>
          )}
          <Button
            type="primary"
            icon={<Plus className="size-4" aria-hidden />}
            onClick={onCreateNew}
          >
            {t("knowledgeBase.card.create")}
          </Button>
        </div>
      </div>
      {isBatchMode && batchFailures.length > 0 && (
        <Alert
          className="mb-3 shrink-0"
          type="error"
          showIcon
          title={t("knowledgeBase.batch.partialFailure", {
            count: batchFailures.length,
          })}
          description={
            <ul className="max-h-24 list-inside list-disc overflow-y-auto">
              {batchFailures.map((failure, index) => (
                <li key={index}>{failure}</li>
              ))}
            </ul>
          }
        />
      )}
      <div className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden p-1 pb-4">
        {error || tagError ? (
          <div
            role="alert"
            className="flex min-h-40 flex-col items-center justify-center gap-3"
          >
            <p className="text-sm text-gray-500">
              {error || t("knowledgeBase.error.fetchListRetry")}
            </p>
            <Button
              onClick={() => {
                onRetry?.();
                setTagRetry((value) => value + 1);
              }}
            >
              {t("repository.common.retry")}
            </Button>
          </div>
        ) : loading ? (
          <div className="flex min-h-40 items-center justify-center">
            <Spin />
          </div>
        ) : null}
        <div
          ref={gridRef}
          data-testid="knowledge-catalog-grid"
          className="grid gap-4"
          style={{
            gridTemplateColumns: `repeat(${gridColumnCount}, minmax(0, 1fr))`,
          }}
        >
          {!loading &&
            !error &&
            !tagError &&
            pagedKnowledgeBases.map((kb) => {
              const isActive = activeKnowledgeBase?.id === kb.id;
              const batchSelectable = selectableBatchItems.includes(kb);
              const batchChecked =
                batchSelectable && batchSelection.includes(kb.id);
              const description =
                kb.description?.trim() &&
                kb.description !== "Elasticsearch index"
                  ? kb.description
                  : t("knowledgeBase.description.default");
              const source = kb.source || "nexent";
              const updatedDate = formatDateOrFallback(
                kb.updatedAt ?? kb.createdAt
              );
              const groupNames = getGroupNames(kb.group_ids);
              const quotaData = quotaMap.get(kb.index_name || kb.id);
              const { totalCapacity } = getKnowledgeBaseQuotaDisplay(
                quotaData,
                t
              );
              return (
                <article
                  key={kb.id}
                  data-knowledge-base-row
                  aria-label={kb.name}
                  role={isBatchMode ? undefined : "button"}
                  tabIndex={isBatchMode ? undefined : 0}
                  className={`group min-w-0 rounded-lg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--color-border-focus)] ${!isBatchMode || batchSelectable ? "cursor-pointer" : ""}`}
                  onClick={() => {
                    if (!isBatchMode) handleKnowledgeBaseSelect(kb);
                    else if (batchSelectable)
                      setBatchSelection((current) =>
                        current.includes(kb.id)
                          ? current.filter((id) => id !== kb.id)
                          : [...current, kb.id]
                      );
                  }}
                  onKeyDown={(event) => {
                    if (isBatchMode || event.target !== event.currentTarget)
                      return;
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      handleKnowledgeBaseSelect(kb);
                    }
                  }}
                >
                  <Card
                    variant="outlined"
                    className={`h-full overflow-hidden transition-colors hover:!border-[var(--color-brand-hover)] ${isActive || batchChecked ? "!border-[var(--color-border-focus)]" : ""}`}
                    styles={{
                      body: {
                        display: "flex",
                        flexDirection: "column",
                        height: "100%",
                        padding: 0,
                      },
                    }}
                  >
                    <div className="flex flex-1 flex-col gap-3 p-4">
                      <div className="flex items-start justify-between gap-3">
                        <div className="flex min-w-0 items-center gap-3">
                          <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-[var(--color-select)] text-[var(--color-brand)]">
                            <FolderOpen className="h-5 w-5" />
                          </div>
                          <div className="min-w-0">
                            <h3
                              className="truncate text-base font-semibold leading-6 text-[var(--color-text-primary)]"
                              title={kb.name}
                            >
                              {kb.name}
                            </h3>
                            <span className="block truncate text-xs text-[var(--color-text-secondary)]">
                              {t("knowledgeBase.tag.source", { source })}
                            </span>
                          </div>
                        </div>

                        {isBatchMode && (
                          <span onClick={(event) => event.stopPropagation()}>
                            <Checkbox
                              aria-label={kb.name}
                              checked={batchChecked}
                              disabled={!batchSelectable}
                              onChange={(event) =>
                                setBatchSelection((current) =>
                                  event.target.checked
                                    ? [...current, kb.id]
                                    : current.filter((id) => id !== kb.id)
                                )
                              }
                            />
                          </span>
                        )}
                      </div>

                      <p className="line-clamp-2 min-h-10 text-sm leading-5 text-[var(--color-text-secondary)]">
                        {description}
                      </p>

                      <div className="flex min-w-0 items-center justify-start gap-3 text-xs leading-5 text-gray-500">
                        <span className="shrink-0">
                          {t("knowledgeBase.create.field.embeddingModel")}
                        </span>
                        <span
                          className="min-w-0 truncate text-sm text-[var(--color-text-primary)]"
                          title={getModelDisplayName(kb.embeddingModel)}
                        >
                          {getModelDisplayName(kb.embeddingModel)}
                        </span>
                      </div>

                      {quotaData && (
                        <Tooltip
                          title={`${t("knowledgeBase.capacity.available")}: ${getKnowledgeBaseQuotaDisplay(quotaData, t).availableCapacity}`}
                        >
                          <div
                            data-testid="knowledge-capacity"
                            className="flex min-w-0 items-center justify-start gap-3 text-xs leading-5"
                          >
                            <span className="shrink-0 text-gray-500">
                              {t("knowledgeBase.capacity.title")}
                            </span>
                            <span className="min-w-0 truncate text-sm tabular-nums text-[var(--color-text-primary)]">
                              {quotaData.actual_readable ||
                                formatFileSize(quotaData.actual_bytes)}
                              <span className="mx-1 text-gray-300">/</span>
                              {totalCapacity}
                            </span>
                          </div>
                        </Tooltip>
                      )}

                      <KnowledgeTagRow>
                        <Can permission="group:read">
                          {kb.ingroup_permission !== "PRIVATE" &&
                            groupNames.slice(0, 2).map((groupName) => (
                              <span
                                key={groupName}
                                className="inline-flex max-w-[120px] min-w-0 shrink-0 items-center overflow-hidden whitespace-nowrap rounded-full border border-blue-200 bg-blue-50 px-2 py-0.5 text-xs font-normal text-blue-700"
                                title={groupName}
                              >
                                <span className="min-w-0 truncate">
                                  {groupName}
                                </span>
                              </span>
                            ))}
                        </Can>
                        <Tooltip
                          title={t(
                            getPermissionTooltipKey(kb.ingroup_permission || "")
                          )}
                        >
                          <span className="inline-flex max-w-[120px] min-w-0 shrink-0 items-center gap-1 overflow-hidden whitespace-nowrap rounded-full border border-gray-200 bg-gray-50 px-2 py-0.5 text-xs font-normal text-gray-600">
                            {getPermissionIcon(kb.ingroup_permission || "")}
                            <span className="min-w-0 truncate">
                              {t(
                                getPermissionTooltipKey(
                                  kb.ingroup_permission || ""
                                )
                              )}
                            </span>
                          </span>
                        </Tooltip>
                        {source === "datamate" ? (
                          <ResourceTagChips
                            resourceType="knowledge_base"
                            resourceId={kb.id}
                            max={99}
                            singleLine
                            className="knowledge-tag-more-wrap min-w-0 max-w-full"
                            tagClassName={CARD_TAG_CLASSNAME}
                          />
                        ) : (
                          <KnowledgeValueTags values={kb.tags ?? []} />
                        )}
                        {kb.is_multimodal &&
                          hasIndexedDocumentsAndChunks(kb) && (
                            <span
                              className={`inline-flex max-w-[120px] min-w-0 shrink-0 items-center overflow-hidden whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-normal ${KB_TAG_VARIANTS.red}`}
                            >
                              <span className="min-w-0 truncate">
                                multimodal
                              </span>
                            </span>
                          )}

                        {kb.preserve_source_file === false && (
                          <span
                            className={`inline-flex max-w-[120px] min-w-0 shrink-0 items-center overflow-hidden whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-normal ${KB_TAG_VARIANTS.warning}`}
                          >
                            <span className="min-w-0 truncate">
                              {t("knowledgeBase.tag.noPreserveSourceFile")}
                            </span>
                          </span>
                        )}
                      </KnowledgeTagRow>
                    </div>

                    <div className="flex flex-wrap items-center gap-x-2 gap-y-1 border-t border-[var(--color-border-separator)] px-4 py-3 text-xs leading-5 text-[var(--color-text-secondary)]">
                      <span className="whitespace-nowrap">
                        {t("knowledgeBase.tag.documents", {
                          count: kb.documentCount || 0,
                        })}
                      </span>
                      <span aria-hidden="true" className="text-gray-300">
                        |
                      </span>
                      <span className="whitespace-nowrap">
                        {t("knowledgeBase.tag.chunks", {
                          count: kb.chunkCount || 0,
                        })}
                      </span>
                      <span
                        className="ml-auto inline-flex min-w-0 items-center gap-1"
                        title={updatedDate}
                      >
                        <Clock3 className="size-3 shrink-0" aria-hidden />
                        <span className="truncate">
                          {t("knowledgeBase.tag.updatedAt", {
                            date: updatedDate,
                          })}
                        </span>
                      </span>
                    </div>
                  </Card>
                </article>
              );
            })}
        </div>

        {!loading &&
          !error &&
          !tagError &&
          pagedKnowledgeBases.length === 0 &&
          (loading ? (
            <div className="py-10 text-center text-sm text-gray-400">
              {t("common.loading")}
            </div>
          ) : (
            <div className="py-10 text-center text-sm text-gray-400">
              {effectiveSearchKeyword ||
              effectiveSelectedSources.length > 0 ||
              effectiveSelectedModels.length > 0 ||
              tagPredicates.length > 0
                ? t("knowledgeBase.list.noResults")
                : t("knowledgeBase.list.empty")}
            </div>
          ))}
      </div>
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-t border-gray-100 py-3 text-xs">
        <span>{t("agentConfig.list.total", { count: filteredTotal })}</span>
        <div className="flex flex-wrap items-center justify-end gap-2">
          <Select
            aria-label={t("agentConfig.list.pageSize")}
            value={pageSize}
            options={[10, 12, 20, 50].map((size) => ({
              value: size,
              label: t("agentConfig.list.perPage", { count: size }),
            }))}
            onChange={(size) => {
              onPageSizeChange?.(size);
              setJumpPage(null);
            }}
            className="!h-8 !w-[116px]"
            disabled={loading}
          />
          <Pagination
            current={currentPage}
            pageSize={pageSize}
            total={filteredTotal}
            showSizeChanger={false}
            onChange={(nextPage) => {
              onPageChange?.(nextPage);
              setJumpPage(null);
            }}
            disabled={loading}
          />
          <InputNumber
            aria-label={t("agentConfig.list.jumpPage")}
            min={1}
            max={pageCount}
            controls={false}
            value={jumpPage}
            onChange={setJumpPage}
            className="!h-8 !w-12"
            disabled={loading}
          />
          <Button
            disabled={loading || jumpPage === null}
            className="!px-2"
            onClick={() => {
              if (jumpPage !== null)
                onPageChange?.(
                  Math.max(1, Math.min(pageCount, Math.trunc(jumpPage)))
                );
            }}
          >
            {t("agentConfig.list.jump")}
          </Button>
        </div>
      </div>

      {showPersonalCapacity && <PersonalKnowledgeBaseCapacityBar />}

      {isBatchMode && (
        <div
          role="toolbar"
          aria-label={t("knowledgeBase.batch.manage")}
          className="z-10 mx-auto mb-3 flex max-w-full shrink-0 flex-wrap items-center justify-center gap-3 rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-2)] px-3 py-2 shadow-lg"
        >
          <Checkbox
            disabled={
              loading ||
              Boolean(error) ||
              tagError ||
              selectableBatchItems.length === 0
            }
            checked={
              selectedBatchItems.length > 0 &&
              selectedBatchItems.length === selectableBatchItems.length
            }
            indeterminate={
              selectedBatchItems.length > 0 &&
              selectedBatchItems.length < selectableBatchItems.length
            }
            onChange={(event) =>
              setBatchSelection(
                event.target.checked
                  ? selectableBatchItems.map((kb) => kb.id)
                  : []
              )
            }
          >
            {t("knowledgeBase.batch.selectPage")}
          </Checkbox>
          <span
            aria-live="polite"
            className="text-sm text-[var(--color-text-secondary)]"
          >
            {t("knowledgeBase.batch.selectedCount", {
              count: selectedBatchItems.length,
            })}
          </span>
          <Button
            danger
            icon={<Trash2 className="size-4" aria-hidden />}
            disabled={
              loading ||
              Boolean(error) ||
              tagError ||
              selectedBatchItems.length === 0
            }
            onClick={() => setBatchDeleteTargets(selectedBatchItems)}
          >
            {t("knowledgeBase.batch.deleteSelected")}
          </Button>
          <Button
            type="text"
            icon={<X className="size-4" aria-hidden />}
            aria-label={t("knowledgeBase.batch.exit")}
            onClick={() => setBatchMode(false)}
          />
        </div>
      )}
      {batchDeleteTargets.length > 0 && (
        <KnowledgeBaseBatchDeleteDialog
          targets={batchDeleteTargets}
          canDelete={canBatchDelete}
          onCancel={() => setBatchDeleteTargets([])}
          onComplete={(failures) => {
            setBatchDeleteTargets([]);
            const failedIds = Object.keys(failures);
            setBatchSelection(failedIds);
            setBatchFailures(Object.values(failures));
            if (failedIds.length < batchDeleteTargets.length)
              onCatalogRefresh?.();
          }}
        />
      )}
    </div>
  );
};

export default KnowledgeBaseList;
