// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import React, {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";

import { Button, InputNumber, Popover, Select, Spin, Tooltip } from "antd";
import {
  SyncOutlined,
  SettingOutlined,
  FilterOutlined,
} from "@ant-design/icons";
import {
  PencilRuler,
  Tag,
  Eye,
  Glasses,
  CircleOff,
  MoreHorizontal,
  Search,
  Clock3,
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
import { getKnowledgeBaseQuotaDisplay } from "@/lib/knowledgeBaseQuota";
import { USER_ROLES } from "@/const/auth";
import { StandardButton } from "@/components/common/StandardButton";
import { StandardInput } from "@/components/common/StandardInput";
import { StandardPaginator } from "@/components/common/StandardPaginator";
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
  onDelete,
  onSync,
  onCreateNew,
  onDataMateConfig,
  showDataMateConfig = false,
  getModelDisplayName,
  containerHeight = "70vh", // Default container height consistent with DocumentList
  onKnowledgeBaseChange, // New: callback function when knowledge base switches
  onKnowledgeBaseUpdate, // Callback when knowledge base is updated
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
  const tenantId = user?.tenantId || null;
  const showPersonalCapacity = user?.role === USER_ROLES.USER;
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
  const [internalTagPredicates, setInternalTagPredicates] = useState<
    TagResourcePredicate[]
  >([]);
  const tagPredicates = tagFilter ?? internalTagPredicates;
  const setTagPredicates = onTagFilterChange ?? setInternalTagPredicates;
  const [matchedTagIds, setMatchedTagIds] = useState<Set<string> | null>(null);
  const { data: tagLibraries } = useTagLibraries();
  const defaultLibrary =
    tagLibraries?.find(
      (library) => library.bucket_key === "default_resource"
    ) ?? null;
  const { data: assignDefinitions, refresh: refreshAssignDefinitions } =
    useTagDefinitions(defaultLibrary?.bucket_id ?? null);

  const [tagCandidates, setTagCandidates] = useState<KnowledgeBase[] | null>(
    null
  );
  const [tagLoading, setTagLoading] = useState(false);
  const [tagError, setTagError] = useState(false);
  const [tagRetry, setTagRetry] = useState(0);
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
      <header className="flex h-12 shrink-0 items-center py-[10px]">
        <h1 className="text-[20px] font-medium leading-7 text-[#191919]">
          {t("sidebar.knowledgeBaseConfig")}
        </h1>
      </header>
      <div
        data-testid="knowledge-catalog-toolbar"
        className="mb-3 mt-3 flex shrink-0 flex-wrap items-center justify-between gap-3"
      >
        <div className="flex min-w-0 flex-1 items-center gap-2 sm:flex-none">
          <StandardInput
            placeholder={t("knowledgeBase.search.placeholder")}
            prefix={<Search className="size-4 text-[#777777]" />}
            value={effectiveSearchKeyword}
            onChange={(event) => handleSearchChange(event.target.value)}
            className="!h-8 !w-full sm:!w-[280px] lg:!w-[360px]"
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
                {defaultLibrary && assignDefinitions && (
                  <div>
                    <div className="mb-1 text-xs text-gray-500">
                      {t("knowledgeBase.tagFilter.placeholder")}
                    </div>
                    <TagFilterControls
                      definitions={assignDefinitions}
                      value={tagPredicates}
                      onChange={(values) => {
                        setTagPredicates(values);
                        onPageChange?.(1);
                      }}
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
                    onPageChange?.(1);
                  }}
                >
                  {t("knowledgeBase.filter.clear")}
                </Button>
              </div>
            }
          >
            <StandardButton
              className="!h-8"
              aria-label={t("knowledgeBase.filter.button")}
              aria-pressed={
                effectiveSelectedSources.length > 0 ||
                effectiveSelectedModels.length > 0 ||
                tagPredicates.length > 0
              }
              icon={<FilterOutlined />}
              variant={
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
            </StandardButton>
          </Popover>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <StandardButton
            onClick={onSync}
            loading={syncLoading}
            icon={<SyncOutlined />}
          >
            {t("knowledgeBase.button.sync")}
          </StandardButton>
          <StandardButton
            onClick={() => setTagManagementOpen(true)}
            icon={<Tag className="size-4" />}
          >
            {t("knowledgeBase.button.tagManagement")}
          </StandardButton>
          {showDataMateConfig && (
            <StandardButton
              onClick={onDataMateConfig}
              icon={<SettingOutlined />}
            >
              {t("knowledgeBase.button.dataMateConfig")}
            </StandardButton>
          )}
          <StandardButton variant="primary" onClick={onCreateNew}>
            {t("knowledgeBase.card.create")}
          </StandardButton>
        </div>
      </div>
      <div className="min-h-0 max-h-[calc(100%-160px)] flex-none overflow-y-auto overflow-x-hidden px-px pb-3 pt-px">
        {error || tagError ? (
          <div
            role="alert"
            className="flex min-h-40 flex-col items-center justify-center gap-3"
          >
            <p className="text-sm text-gray-500">
              {error || t("knowledgeBase.error.fetchListRetry")}
            </p>
            <StandardButton
              onClick={() => {
                onRetry?.();
                setTagRetry((value) => value + 1);
              }}
            >
              {t("repository.common.retry")}
            </StandardButton>
          </div>
        ) : loading ? (
          <div className="flex min-h-40 items-center justify-center">
            <Spin />
          </div>
        ) : null}
        <div
          ref={gridRef}
          data-testid="knowledge-catalog-grid"
          className="grid gap-x-4 gap-y-3"
          style={{
            gridTemplateColumns: `repeat(${gridColumnCount}, minmax(0, 1fr))`,
          }}
        >
          {!loading &&
            !error &&
            !tagError &&
            pagedKnowledgeBases.map((kb) => {
              const isActive = activeKnowledgeBase?.id === kb.id;
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
                  role="button"
                  tabIndex={0}
                  className={`group relative flex h-full min-h-[220px] min-w-0 cursor-pointer flex-col gap-2 rounded-[12px] bg-white p-4 ring-1 transition-colors hover:ring-[#a8a8a8] focus-visible:ring-[#777777] ${isActive ? "ring-[#a8a8a8]" : "ring-[rgba(201,201,201,0.4)]"}`}
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
                      <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-blue-50 text-blue-600">
                        <FolderOpen className="h-5 w-5" />
                      </div>
                      <div className="min-w-0">
                        <h3
                          className="truncate text-[16px] font-medium leading-6 text-[#191919]"
                          title={kb.name}
                        >
                          {kb.name}
                        </h3>
                        <span className="mt-1 block truncate text-xs text-gray-400">
                          {t("knowledgeBase.tag.source", { source })}
                        </span>
                      </div>
                    </div>

                    <Popover
                      trigger="click"
                      placement="bottomRight"
                      content={
                        <div
                          className="flex flex-col [&>.ant-btn~.ant-btn]:!border-t [&>.ant-btn~.ant-btn]:!border-t-gray-100"
                          onClick={(event) => event.stopPropagation()}
                        >
                          <Can permission="kb:update">
                            <Tooltip
                              title={t("knowledgeBase.action.assignTags")}
                            >
                              <Button
                                type="text"
                                size="small"
                                className="!w-full !justify-start !rounded-none !text-left"
                                aria-label={t(
                                  "knowledgeBase.action.assignTags"
                                )}
                                onClick={(event) => {
                                  event.stopPropagation();
                                  setAssignTarget({
                                    indexName: kb.id,
                                    canEdit: kb.permission !== "READ_ONLY",
                                  });
                                }}
                              >
                                {t("knowledgeBase.action.assignTags")}
                              </Button>
                            </Tooltip>
                            {(!kb.source ||
                              kb.source === "nexent" ||
                              kb.source === "elasticsearch") &&
                              kb.permission !== "READ_ONLY" && (
                                <Tooltip title={t("common.edit")}>
                                  <Button
                                    type="text"
                                    size="small"
                                    className="!w-full !justify-start !rounded-none !text-left"
                                    aria-label={t("common.edit")}
                                    onClick={(event) => {
                                      event.stopPropagation();
                                      openEditModal(kb);
                                    }}
                                  >
                                    {t("common.edit")}
                                  </Button>
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
                                  className="!w-full !justify-start !rounded-none !text-left"
                                  aria-label={t("common.delete")}
                                  onClick={(event) => {
                                    event.stopPropagation();
                                    onDelete(kb.id);
                                  }}
                                >
                                  {t("common.delete")}
                                </Button>
                              </Tooltip>
                            )}
                          </Can>
                        </div>
                      }
                    >
                      <button
                        type="button"
                        aria-label={t("skillRepository.common.moreActions")}
                        className="flex size-7 shrink-0 items-center justify-center rounded text-[#777777] hover:bg-gray-100"
                        onClick={(event) => event.stopPropagation()}
                      >
                        <MoreHorizontal className="size-4" />
                      </button>
                    </Popover>
                  </div>

                  <p className="line-clamp-2 text-sm leading-5 text-[#1a1a1a]">
                    {description}
                  </p>

                  <div className="flex min-w-0 items-center justify-start gap-3 text-xs leading-5 text-gray-500">
                    <span className="shrink-0">
                      {t("knowledgeBase.create.field.embeddingModel")}
                    </span>
                    <span
                      className="min-w-0 truncate text-sm text-[#1a1a1a]"
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
                        <span className="min-w-0 truncate text-sm tabular-nums text-[#1a1a1a]">
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
                            getPermissionTooltipKey(kb.ingroup_permission || "")
                          )}
                        </span>
                      </span>
                    </Tooltip>
                    <ResourceTagChips
                      resourceType="knowledge_base"
                      resourceId={kb.id}
                      max={99}
                      singleLine
                      className="knowledge-tag-more-wrap min-w-0 max-w-full"
                      tagClassName="!m-0 !inline-flex !h-[22px] !max-w-[120px] !shrink-0 !items-center !rounded-full !border-gray-200 !bg-gray-50 !px-2 !py-0 !text-xs !font-normal !leading-5 !text-gray-600"
                    />
                    {kb.is_multimodal && hasIndexedDocumentsAndChunks(kb) && (
                      <span
                        className={`inline-flex max-w-[120px] min-w-0 shrink-0 items-center overflow-hidden whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-normal ${KB_TAG_VARIANTS.red}`}
                      >
                        <span className="min-w-0 truncate">multimodal</span>
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

                  <div className="mt-1 flex flex-wrap items-center justify-start gap-x-2 gap-y-1 border-t border-gray-100 pt-3 text-xs leading-5 text-gray-500">
                    <span
                      className="inline-flex min-w-0 items-center gap-1"
                      title={updatedDate}
                    >
                      <Clock3 className="size-3 shrink-0" />
                      <span className="truncate">
                        {t("knowledgeBase.tag.updatedAt", {
                          date: updatedDate,
                        })}
                      </span>
                    </span>
                    <span aria-hidden="true" className="text-gray-300">
                      |
                    </span>
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
                  </div>
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
          <StandardPaginator
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
          <StandardButton
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
          </StandardButton>
        </div>
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
