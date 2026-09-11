import React, {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";

import log from "@/lib/logger";

import { Button, Input, Popover, Progress, Select, Tooltip } from "antd";
import {
  SyncOutlined,
  PlusOutlined,
  SettingOutlined,
  SearchOutlined,
  FilterOutlined,
} from "@ant-design/icons";
import {
  PencilRuler,
  Tag,
  Eye,
  Glasses,
  Trash2,
  SquarePen,
  CircleOff,
  BookOpen,
  FolderOpen,
} from "lucide-react";
import { Can } from "@/components/permission/Can";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { useGroupList } from "@/hooks/group/useGroupList";
import { KnowledgeBaseEditModal } from "./KnowledgeBaseEditModal";
import PersonalKnowledgeBaseCapacityBar from "./PersonalKnowledgeBaseCapacityBar";
import ResourceTagAssignmentModal from "@/components/tag/ResourceTagAssignmentModal";
import TagDefinitionManagementModal from "@/components/tag/TagDefinitionManagementModal";
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
import { USER_ROLES } from "@/const/auth";
import { calculateKnowledgeBaseInitialLimit } from "@/lib/knowledgeBaseViewport";
import type { KBQuotaStatus, QuotaUsageResponse } from "@/types/quota";

interface KnowledgeBaseListProps {
  knowledgeBases: KnowledgeBase[];
  activeKnowledgeBase: KnowledgeBase | null;
  isLoading?: boolean;
  isLoadingMore?: boolean;
  syncLoading?: boolean;
  totalCount?: number;
  hasMore?: boolean;
  estimatedRowHeight?: number;
  estimatedItemHeights?: Record<string, number> | null;
  availableSources?: string[];
  availableModels?: string[];
  quotaUsage?: QuotaUsageResponse | null;
  onLoadMore?: () => void;
  serverFiltered?: boolean;
  initialLoadPending?: boolean;
  onViewportCapacityChange?: (
    capacity: number,
    hasMeasuredRows: boolean
  ) => void;
  onClick: (kb: KnowledgeBase) => void;
  onDelete: (id: string) => void;
  onSync: () => void;
  onCreateNew: () => void;
  onDataMateConfig?: () => void;
  showDataMateConfig?: boolean; // Control whether to show DataMate config button
  getModelDisplayName: (modelId: string) => string;
  containerHeight?: string; // Container total height, consistent with DocumentList
  onKnowledgeBaseChange?: () => void; // Callback when knowledge base switches
  onKnowledgeBaseUpdate?: (updatedKnowledgeBase: KnowledgeBase) => void; // Callback when knowledge base is updated
  // Optional controlled search / filter props (if parent wants to control filters)
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
  isLoadingMore = false,
  syncLoading = false,
  totalCount = knowledgeBases.length,
  hasMore = false,
  estimatedRowHeight = 112,
  estimatedItemHeights,
  availableSources: availableSourceOptions,
  availableModels: availableModelOptions,
  quotaUsage = null,
  onLoadMore,
  serverFiltered = false,
  initialLoadPending = false,
  onViewportCapacityChange,
  onClick,
  onDelete,
  onSync,
  onCreateNew,
  onDataMateConfig,
  showDataMateConfig = false,
  getModelDisplayName,
  containerHeight = "70vh", // Default container height consistent with DocumentList
  onKnowledgeBaseChange, // New: callback function when knowledge base switches
  onKnowledgeBaseUpdate, // Callback when knowledge base is updated
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
  const tenantId = user?.tenantId || null;
  const showPersonalCapacity = user?.role === USER_ROLES.USER;
  const quotaMap = useMemo(() => {
    const map = new Map<string, KBQuotaStatus>();
    quotaUsage?.breakdown?.forEach((quota) => {
      map.set(quota.index_name, quota);
    });
    return map;
  }, [quotaUsage]);
  const scrollContainerRef = useRef<HTMLDivElement | null>(null);
  const previousScrollTopRef = useRef(0);
  const [measuredRowHeight, setMeasuredRowHeight] =
    useState(estimatedRowHeight);
  const [hasMeasuredRows, setHasMeasuredRows] = useState(false);
  const [gridColumnCount, setGridColumnCount] = useState(1);

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

  // Edit modal states
  const [editModalVisible, setEditModalVisible] = useState(false);
  const [assignTarget, setAssignTarget] = useState<{
    indexName: string;
    canEdit: boolean;
  } | null>(null);
  const [tagManagementOpen, setTagManagementOpen] = useState(false);
  const [tagPredicates, setTagPredicates] = useState<TagResourcePredicate[]>(
    []
  );
  const [matchedTagIds, setMatchedTagIds] = useState<Set<string> | null>(null);
  const { data: tagLibraries } = useTagLibraries();
  const defaultLibrary =
    tagLibraries?.find(
      (library) => library.bucket_key === "default_resource"
    ) ?? null;
  const { data: assignDefinitions, refresh: refreshAssignDefinitions } =
    useTagDefinitions(defaultLibrary?.bucket_id ?? null);

  useEffect(() => {
    if (tagPredicates.length === 0) {
      setMatchedTagIds(null);
      return;
    }
    const resourceIds = knowledgeBases.map((knowledgeBase) =>
      String(knowledgeBase.id)
    );
    if (resourceIds.length === 0) {
      setMatchedTagIds(new Set());
      return;
    }
    let cancelled = false;
    void tagManagementApi
      .filterResourceIds("knowledge_base", resourceIds, tagPredicates)
      .then((result) => {
        if (!cancelled) {
          setMatchedTagIds(new Set(result.matched_resource_ids));
        }
      })
      .catch(() => {
        if (!cancelled) {
          setMatchedTagIds(new Set());
        }
      });
    return () => {
      cancelled = true;
    };
  }, [knowledgeBases, tagPredicates]);
  const [editingKnowledge, setEditingKnowledge] =
    useState<KnowledgeBase | null>(null);

  // Open edit modal
  const openEditModal = (kb: KnowledgeBase) => {
    setEditingKnowledge(kb);
    setEditModalVisible(true);
  };

  // Close edit modal
  const closeEditModal = () => {
    setEditModalVisible(false);
    setEditingKnowledge(null);
  };

  // Effective (controlled or uncontrolled) values
  const effectiveSearchKeyword =
    typeof searchQuery !== "undefined" ? searchQuery : searchKeyword;
  const effectiveSelectedSources =
    typeof sourceFilter !== "undefined"
      ? Array.isArray(sourceFilter)
        ? sourceFilter
        : sourceFilter
          ? [sourceFilter]
          : []
      : selectedSources;
  const effectiveSelectedModels =
    typeof modelFilter !== "undefined"
      ? Array.isArray(modelFilter)
        ? modelFilter
        : modelFilter
          ? [modelFilter]
          : []
      : selectedModels;

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
  const sortedKnowledgeBases = [...knowledgeBases].sort((a, b) => {
    const aTime = getTimestamp(a.updatedAt ?? a.createdAt);
    const bTime = getTimestamp(b.updatedAt ?? b.createdAt);
    return bTime - aTime;
  });

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
    log.log("Filtering knowledge bases:", {
      totalCount: knowledgeBases.length,
      searchKeyword: effectiveSearchKeyword,
      sourceFilter: effectiveSelectedSources,
      modelFilter: effectiveSelectedModels,
    });

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

          if (!matches) {
            log.log("KB filtered out:", {
              name: kb.name,
              source: kb.source,
              embeddingModel: kb.embeddingModel,
              matchesSearch,
              matchesSource,
              matchesModel,
            });
          }

          return matches;
        });

    const tagFilteredResult =
      matchedTagIds === null
        ? result
        : result.filter((knowledgeBase) =>
            matchedTagIds.has(String(knowledgeBase.id))
          );
    log.log("Filtered result:", tagFilteredResult.length, "items");
    return tagFilteredResult;
  }, [
    sortedKnowledgeBases,
    effectiveSearchKeyword,
    effectiveSelectedSources,
    effectiveSelectedModels,
    matchedTagIds,
    serverFiltered,
  ]);

  useLayoutEffect(() => {
    const rows = scrollContainerRef.current?.querySelectorAll<HTMLElement>(
      "[data-knowledge-base-row]"
    );
    if (!rows?.length) {
      if (hasMeasuredRows) setHasMeasuredRows(false);
      return;
    }
    const average =
      Array.from(rows).reduce(
        (sum, row) => sum + row.getBoundingClientRect().height,
        0
      ) / rows.length;
    if (average > 0 && Math.abs(average - measuredRowHeight) > 1) {
      setMeasuredRowHeight(average);
    }
    if (!hasMeasuredRows) setHasMeasuredRows(true);
  }, [filteredKnowledgeBases.length, hasMeasuredRows, measuredRowHeight]);

  useLayoutEffect(() => {
    const container = scrollContainerRef.current;
    if (!container || !onViewportCapacityChange) return;

    const reportCapacity = () => {
      if (container.clientHeight <= 0 || measuredRowHeight <= 0) return;
      const columns = container.clientWidth >= 768 ? 2 : 1;
      setGridColumnCount((current) =>
        current === columns ? current : columns
      );
      onViewportCapacityChange(
        calculateKnowledgeBaseInitialLimit(
          container.clientHeight,
          measuredRowHeight
        ) * columns,
        hasMeasuredRows
      );
    };
    reportCapacity();
    const observer = new ResizeObserver(reportCapacity);
    observer.observe(container);
    return () => observer.disconnect();
  }, [hasMeasuredRows, measuredRowHeight, onViewportCapacityChange]);

  const placeholderHeight = useMemo(() => {
    const unloadedCount = Math.max(
      0,
      totalCount - filteredKnowledgeBases.length
    );
    if (!unloadedCount) return 0;
    if (estimatedItemHeights) {
      const loadedIds = new Set(filteredKnowledgeBases.map((kb) => kb.id));
      const reservedHeight = Object.entries(estimatedItemHeights).reduce(
        (sum, [id, height]) => sum + (loadedIds.has(id) ? 0 : height),
        0
      );
      if (reservedHeight > 0) {
        return Math.ceil(reservedHeight / gridColumnCount);
      }
    }
    return Math.ceil(unloadedCount / gridColumnCount) * measuredRowHeight;
  }, [
    estimatedItemHeights,
    filteredKnowledgeBases.length,
    gridColumnCount,
    measuredRowHeight,
    totalCount,
  ]);

  const handleScroll = useCallback(
    (event: React.UIEvent<HTMLDivElement>) => {
      const container = event.currentTarget;
      const hasDownwardIntent =
        container.scrollTop > previousScrollTopRef.current;
      previousScrollTopRef.current = container.scrollTop;
      if (!hasDownwardIntent || !hasMore || isLoadingMore || !onLoadMore)
        return;

      if (
        container.scrollTop + container.clientHeight >=
        container.scrollHeight - 160
      ) {
        onLoadMore();
      }
    },
    [hasMore, isLoadingMore, onLoadMore]
  );

  return (
    <div className="flex h-full min-h-0 w-full flex-col overflow-hidden rounded-2xl bg-white">
      <div className="shrink-0 px-6 pb-4 pt-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex min-w-0 items-center gap-3">
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-blue-100 text-blue-600">
              <BookOpen className="h-5 w-5" />
            </div>
            <div className="min-w-0">
              <h1 className="truncate text-2xl font-semibold tracking-tight text-gray-900">
                {t("knowledgeBase.page.title")}
              </h1>
              <p className="mt-1 text-sm text-gray-500">
                {t("knowledgeBase.page.description")}
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="primary"
              className="!h-10 !rounded-lg !px-4"
              onClick={onCreateNew}
              icon={<PlusOutlined />}
            >
              {t("knowledgeBase.button.create")}
            </Button>
            <Tooltip title={t("knowledgeBase.button.sync")}>
              <Button
                aria-label={t("knowledgeBase.button.sync")}
                className="!h-10 !w-10 !rounded-lg !p-0"
                onClick={onSync}
                icon={<SyncOutlined spin={syncLoading} />}
              />
            </Tooltip>
            <Tooltip title={t("knowledgeBase.button.tagManagement")}>
              <Button
                aria-label={t("knowledgeBase.button.tagManagement")}
                className="!h-10 !w-10 !rounded-lg !p-0"
                onClick={() => setTagManagementOpen(true)}
                icon={<Tag className="h-4 w-4" />}
              />
            </Tooltip>
            {showDataMateConfig && (
              <Tooltip title={t("knowledgeBase.button.dataMateConfig")}>
                <Button
                  aria-label={t("knowledgeBase.button.dataMateConfig")}
                  className="!h-10 !w-10 !rounded-lg !p-0"
                  onClick={onDataMateConfig}
                  icon={<SettingOutlined />}
                />
              </Tooltip>
            )}
          </div>
        </div>

        <div className="mt-6 flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-base font-semibold text-gray-900">
            {t("knowledgeBase.page.all")}
            <span className="ml-2 text-sm font-normal text-gray-400">
              {t("knowledgeBase.page.count", { count: totalCount })}
            </span>
          </h2>
          <div className="flex min-w-0 flex-1 justify-end gap-3 sm:min-w-[360px]">
            <Input
              size="large"
              placeholder={t("knowledgeBase.search.placeholder")}
              prefix={<SearchOutlined className="text-gray-400" />}
              value={effectiveSearchKeyword}
              onChange={(e) => handleSearchChange(e.target.value)}
              className="h-10 max-w-[560px] flex-1 !rounded-lg"
              allowClear
            />
            <Popover
              trigger="click"
              placement="bottomRight"
              title={t("knowledgeBase.filter.title")}
              content={
                <div className="w-[300px] space-y-3">
                  {availableSources.length > 0 && (
                    <div>
                      <div className="mb-1 text-xs text-gray-500">
                        {t("knowledgeBase.filter.source")}
                      </div>
                      <Select
                        mode="multiple"
                        placeholder={t(
                          "knowledgeBase.filter.source.placeholder"
                        )}
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
                        placeholder={t(
                          "knowledgeBase.filter.model.placeholder"
                        )}
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
                  {defaultLibrary && assignDefinitions && (
                    <div>
                      <div className="mb-1 text-xs text-gray-500">
                        {t("knowledgeBase.tagFilter.placeholder")}
                      </div>
                      <TagFilterControls
                        definitions={assignDefinitions}
                        value={tagPredicates}
                        onChange={setTagPredicates}
                      />
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
                    }}
                  >
                    {t("knowledgeBase.filter.clear")}
                  </Button>
                </div>
              }
            >
              <Button
                className="!h-10 !rounded-lg"
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
        </div>
      </div>

      <div
        ref={scrollContainerRef}
        className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden px-6 pb-6"
        onScroll={handleScroll}
      >
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <button
            type="button"
            data-knowledge-base-row
            className="group flex min-h-[220px] flex-col items-center justify-center rounded-2xl border border-dashed border-blue-300 bg-blue-50/40 p-6 text-center transition hover:border-blue-500 hover:bg-blue-50"
            onClick={onCreateNew}
          >
            <span className="flex h-12 w-12 items-center justify-center rounded-full bg-blue-100 text-2xl font-light text-blue-600 transition group-hover:scale-105">
              +
            </span>
            <span className="mt-4 text-base font-semibold text-blue-700">
              {t("knowledgeBase.card.create")}
            </span>
            <span className="mt-1 text-sm text-blue-500">
              {t("knowledgeBase.card.createDescription")}
            </span>
          </button>

          {filteredKnowledgeBases.map((kb) => {
            const isActive = activeKnowledgeBase?.id === kb.id;
            const description =
              kb.description?.trim() && kb.description !== "Elasticsearch index"
                ? kb.description
                : t("knowledgeBase.description.default");
            const source = kb.source || "nexent";
            const updatedDate = formatDateOrFallback(
              kb.updatedAt ?? kb.createdAt
            );
            const groupNames = getGroupNames(kb.group_ids);
            const quotaData = quotaMap.get(kb.index_name || kb.id);
            const hasQuota = quotaData?.soft_quota_bytes != null;
            const availableCapacity = quotaData
              ? hasQuota
                ? formatFileSize(
                    Math.max(
                      quotaData.soft_quota_bytes! - quotaData.actual_bytes,
                      0
                    )
                  )
                : t("knowledgeBase.capacity.unlimited")
              : "-";
            const totalCapacity = quotaData
              ? hasQuota
                ? quotaData.soft_quota_readable ||
                  formatFileSize(quotaData.soft_quota_bytes!)
                : t("knowledgeBase.capacity.unlimited")
              : "-";
            const quotaUsagePercent = quotaData
              ? Math.min(
                  100,
                  Math.max(
                    0,
                    quotaData.usage_pct ??
                      (hasQuota && quotaData.soft_quota_bytes! > 0
                        ? (quotaData.actual_bytes /
                            quotaData.soft_quota_bytes!) *
                          100
                        : quotaData.actual_bytes > 0
                          ? 100
                          : 0)
                  )
                )
              : 0;

            return (
              <article
                key={kb.id}
                data-knowledge-base-row
                role="button"
                tabIndex={0}
                className={`group flex min-h-[220px] cursor-pointer flex-col rounded-2xl border bg-white p-5 shadow-sm transition hover:-translate-y-0.5 hover:shadow-md ${
                  isActive
                    ? "border-blue-500 ring-2 ring-blue-100"
                    : "border-gray-200 hover:border-blue-200"
                }`}
                onClick={() => handleKnowledgeBaseSelect(kb)}
                onKeyDown={(event) => {
                  if (event.target !== event.currentTarget) return;
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    handleKnowledgeBaseSelect(kb);
                  }
                }}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="flex min-w-0 items-center gap-3">
                    <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-blue-50 text-blue-600">
                      <FolderOpen className="h-5 w-5" />
                    </div>
                    <div className="min-w-0">
                      <h3
                        className="truncate text-base font-semibold text-gray-900"
                        title={kb.name}
                      >
                        {kb.name}
                      </h3>
                      <span className="mt-1 block truncate text-xs text-gray-400">
                        {t("knowledgeBase.tag.source", { source })}
                      </span>
                    </div>
                  </div>

                  <div className="flex shrink-0 items-center gap-0.5 opacity-70 transition group-hover:opacity-100">
                    <Can permission="kb:update">
                      <Tooltip title={t("knowledgeBase.action.assignTags")}>
                        <Button
                          type="text"
                          size="small"
                          aria-label={t("knowledgeBase.action.assignTags")}
                          icon={<Tag className="h-4 w-4" />}
                          onClick={(event) => {
                            event.stopPropagation();
                            setAssignTarget({
                              indexName: kb.id,
                              canEdit: kb.permission !== "READ_ONLY",
                            });
                          }}
                        />
                      </Tooltip>
                      {(!kb.source ||
                        kb.source === "nexent" ||
                        kb.source === "elasticsearch") &&
                        kb.permission !== "READ_ONLY" && (
                          <Tooltip title={t("common.edit")}>
                            <Button
                              type="text"
                              size="small"
                              aria-label={t("common.edit")}
                              icon={<SquarePen className="h-4 w-4" />}
                              onClick={(event) => {
                                event.stopPropagation();
                                openEditModal(kb);
                              }}
                            />
                          </Tooltip>
                        )}
                    </Can>
                    <Can permission="kb:delete">
                      {kb.permission !== "READ_ONLY" && (
                        <Tooltip title={t("common.delete")}>
                          <Button
                            type="text"
                            danger
                            size="small"
                            aria-label={t("common.delete")}
                            icon={<Trash2 className="h-4 w-4" />}
                            onClick={(event) => {
                              event.stopPropagation();
                              onDelete(kb.id);
                            }}
                          />
                        </Tooltip>
                      )}
                    </Can>
                  </div>
                </div>

                <p className="mt-4 line-clamp-2 min-h-10 text-sm leading-5 text-gray-500">
                  {description}
                </p>

                <div className="mt-4 flex flex-wrap content-start gap-2">
                  <span
                    className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ${KB_TAG_VARIANTS.light}`}
                  >
                    {t("knowledgeBase.tag.documents", {
                      count: kb.documentCount || 0,
                    })}
                  </span>
                  <span
                    className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ${KB_TAG_VARIANTS.light}`}
                  >
                    {t("knowledgeBase.tag.chunks", {
                      count: kb.chunkCount || 0,
                    })}
                  </span>
                  {kb.embeddingModel !== "unknown" && (
                    <span
                      className={`inline-flex max-w-full items-center truncate rounded-full px-2.5 py-1 text-xs font-medium ${KB_TAG_VARIANTS.model}`}
                      title={getModelDisplayName(kb.embeddingModel)}
                    >
                      {getModelDisplayName(kb.embeddingModel)}
                    </span>
                  )}
                  {kb.is_multimodal && hasIndexedDocumentsAndChunks(kb) && (
                    <span
                      className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ${KB_TAG_VARIANTS.red}`}
                    >
                      multimodal
                    </span>
                  )}
                  <ResourceTagChips
                    resourceType="knowledge_base"
                    resourceId={kb.id}
                    max={3}
                  />
                  <Can permission="group:read">
                    {kb.ingroup_permission !== "PRIVATE" &&
                      groupNames.slice(0, 2).map((groupName) => (
                        <span
                          key={groupName}
                          className="inline-flex max-w-full items-center truncate rounded-full border border-blue-200 bg-blue-50 px-2.5 py-1 text-xs font-medium text-blue-700"
                          title={groupName}
                        >
                          {groupName}
                        </span>
                      ))}
                  </Can>
                  {kb.preserve_source_file === false && (
                    <span
                      className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ${KB_TAG_VARIANTS.warning}`}
                    >
                      {t("knowledgeBase.tag.noPreserveSourceFile")}
                    </span>
                  )}
                  <Tooltip
                    title={t(
                      getPermissionTooltipKey(kb.ingroup_permission || "")
                    )}
                  >
                    <span className="inline-flex items-center gap-1 rounded-full border border-gray-200 bg-gray-50 px-2.5 py-1 text-xs font-medium text-gray-600">
                      {getPermissionIcon(kb.ingroup_permission || "")}
                      {t(getPermissionTooltipKey(kb.ingroup_permission || ""))}
                    </span>
                  </Tooltip>
                </div>

                {quotaData && (
                  <div className="mt-4 rounded-xl border border-gray-100 bg-gray-50/80 px-3 py-2.5">
                    <div className="mb-2 flex items-center justify-between gap-2 text-xs">
                      <span className="font-medium text-gray-600">
                        {t("knowledgeBase.capacity.title")}
                      </span>
                      {hasQuota && (
                        <span className="text-gray-400">
                          {Math.round(quotaUsagePercent)}%
                        </span>
                      )}
                    </div>
                    <div className="grid grid-cols-2 gap-3 text-xs">
                      <div className="min-w-0">
                        <div className="text-gray-400">
                          {t("knowledgeBase.capacity.available")}
                        </div>
                        <div className="truncate font-medium text-gray-800">
                          {availableCapacity}
                        </div>
                      </div>
                      <div className="min-w-0 text-right">
                        <div className="text-gray-400">
                          {t("knowledgeBase.capacity.total")}
                        </div>
                        <div className="truncate font-medium text-gray-800">
                          {totalCapacity}
                        </div>
                      </div>
                    </div>
                    {hasQuota && (
                      <Progress
                        className="!mb-0 !mt-2"
                        percent={quotaUsagePercent}
                        showInfo={false}
                        size="small"
                        status={
                          quotaData.kb_warning_level === "exceeded"
                            ? "exception"
                            : "normal"
                        }
                      />
                    )}
                  </div>
                )}

                <div className="mt-auto flex items-center justify-between border-t border-gray-100 pt-4 text-xs text-gray-400">
                  <span>
                    {t("knowledgeBase.tag.updatedAt", { date: updatedDate })}
                  </span>
                  <span className="font-medium text-gray-500">{source}</span>
                </div>
              </article>
            );
          })}
        </div>

        {filteredKnowledgeBases.length === 0 &&
          (isLoading || initialLoadPending ? (
            <div className="py-10 text-center text-sm text-gray-400">
              Loading...
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

        {placeholderHeight > 0 && (
          <div aria-hidden="true" style={{ height: placeholderHeight }} />
        )}
        {isLoadingMore && (
          <div className="py-3 text-center text-xs text-gray-400">
            Loading...
          </div>
        )}
      </div>

      {showPersonalCapacity && <PersonalKnowledgeBaseCapacityBar />}

      {/* Edit Knowledge Base Modal */}
      <KnowledgeBaseEditModal
        open={editModalVisible}
        knowledgeBase={editingKnowledge}
        tenantId={tenantId}
        onCancel={closeEditModal}
        onSuccess={(updatedKnowledgeBase) => {
          if (onKnowledgeBaseUpdate) {
            onKnowledgeBaseUpdate(updatedKnowledgeBase);
          }
        }}
      />
      <TagDefinitionManagementModal
        open={tagManagementOpen}
        onClose={() => {
          setTagManagementOpen(false);
          void refreshAssignDefinitions();
        }}
        bucketId={defaultLibrary?.bucket_id ?? 0}
        bucketName={defaultLibrary?.bucket_name ?? ""}
        canManage={true}
      />
      <ResourceTagAssignmentModal
        open={assignTarget !== null}
        onClose={() => setAssignTarget(null)}
        resourceType="knowledge_base"
        resourceId={assignTarget?.indexName ?? ""}
        definitions={assignDefinitions ?? []}
        canEdit={assignTarget?.canEdit ?? false}
        onManageDefinitions={() => setTagManagementOpen(true)}
      />
    </div>
  );
};

export default KnowledgeBaseList;
