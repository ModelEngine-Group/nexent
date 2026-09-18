"use client";

import { useEffect, useMemo, useState } from "react";
import { App, Input, Modal } from "antd";
import { useTranslation } from "react-i18next";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { USER_ROLES } from "@/const/auth";
import { useTagDefinitions, useTagLibraries } from "@/hooks/useTagManagement";
import type { TagResourcePredicate } from "@/types/tagManagement";
import {
  useInstallSkillFromRepository,
  useSkillRepositoryListingDetail,
  useSkillRepositoryListings,
  useUpdateSkillRepositoryStatus,
} from "@/hooks/skillRepository/useSkillRepositoryListings";
import type {
  SkillRepositoryListingItem,
  SkillRepositoryListingStatus,
} from "@/types/skillRepository";
import { SkillRepositoryDetailModal } from "./components/SkillRepositoryDetailModal";
import { RepositoryView } from "./components/RepositoryView";
import { getSkillRepositoryStatusLabel } from "./components/skillRepositoryShared";

const REPOSITORY_PAGE_SIZE = 6;
const SEARCH_DEBOUNCE_MS = 300;
const STATUS_ACTION_LABEL_KEYS: Partial<
  Record<SkillRepositoryListingStatus, string>
> = {
  not_shared: "skillRepository.action.status.notShared",
  shared: "skillRepository.action.status.shared",
  rejected: "skillRepository.action.status.rejected",
};

export function SkillSpace({ active }: { active: boolean }) {
  const { t } = useTranslation("common");
  const { message, modal } = App.useApp();
  const { user } = useAuthorizationContext();
  const isAdmin = user?.role === USER_ROLES.ADMIN;
  const [repositoryPage, setRepositoryPage] = useState(1);
  const [repositorySearch, setRepositorySearch] = useState("");
  const [repositoryTagPredicates, setRepositoryTagPredicates] = useState<
    TagResourcePredicate[]
  >([]);
  const [debouncedRepositorySearch, setDebouncedRepositorySearch] =
    useState("");
  const [detailRepositoryId, setDetailRepositoryId] = useState<number | null>(
    null
  );
  const [copyListing, setCopyListing] =
    useState<SkillRepositoryListingItem | null>(null);
  const [copyTargetName, setCopyTargetName] = useState("");
  const [copyNameError, setCopyNameError] = useState<string | null>(null);
  const { data: tagLibraries } = useTagLibraries();
  const defaultTagLibrary =
    tagLibraries?.find(
      (library) => library.bucket_key === "default_resource"
    ) ?? null;
  const { data: tagDefinitions } = useTagDefinitions(
    defaultTagLibrary?.bucket_id ?? null
  );

  useEffect(() => {
    const timer = window.setTimeout(
      () => setDebouncedRepositorySearch(repositorySearch),
      SEARCH_DEBOUNCE_MS
    );
    return () => window.clearTimeout(timer);
  }, [repositorySearch]);

  const repositoryParams = useMemo(
    () => ({
      status: "shared" as const,
      page: repositoryPage,
      page_size: REPOSITORY_PAGE_SIZE,
      ...(debouncedRepositorySearch.trim()
        ? { search: debouncedRepositorySearch.trim() }
        : {}),
      ...(repositoryTagPredicates.length > 0
        ? { tag_predicates: repositoryTagPredicates }
        : {}),
    }),
    [debouncedRepositorySearch, repositoryPage, repositoryTagPredicates]
  );
  const {
    data: repositoryData,
    isLoading: isRepositoryLoading,
    isError: isRepositoryError,
    isFetching: isRepositoryFetching,
    refetch: refetchRepository,
  } = useSkillRepositoryListings(repositoryParams, active);
  const installMutation = useInstallSkillFromRepository();
  const updateStatusMutation = useUpdateSkillRepositoryStatus();
  const {
    data: detailData,
    isLoading: isDetailLoading,
    isError: isDetailError,
    isFetching: isDetailFetching,
    refetch: refetchDetail,
  } = useSkillRepositoryListingDetail(
    detailRepositoryId,
    detailRepositoryId != null
  );
  const repositoryItems = repositoryData?.items ?? [];
  const repositoryTotal = repositoryData?.pagination?.total ?? 0;
  const updatingRepositoryId = updateStatusMutation.isPending
    ? (updateStatusMutation.variables?.skillRepositoryId ?? null)
    : null;
  const installingRepositoryId = installMutation.isPending
    ? (installMutation.variables?.skillRepositoryId ?? null)
    : null;

  useEffect(() => {
    if (active) refetchRepository().catch(() => {});
  }, [active, refetchRepository]);

  useEffect(() => {
    const total = repositoryData?.pagination?.total;
    if (total == null) return;
    const totalPages = Math.max(1, Math.ceil(total / REPOSITORY_PAGE_SIZE));
    if (repositoryPage > totalPages) {
      /* eslint-disable react-hooks/set-state-in-effect -- Clamp after server pagination changes. */
      setRepositoryPage(totalPages);
      /* eslint-enable react-hooks/set-state-in-effect */
    }
  }, [repositoryData?.pagination?.total, repositoryPage]);

  const getDuplicateSkillNames = (error: unknown): string[] | null => {
    const detail =
      error instanceof Error && "detail" in error
        ? (error as { detail?: unknown }).detail
        : null;
    if (
      typeof detail !== "object" ||
      detail == null ||
      !("type" in detail) ||
      (detail as { type?: unknown }).type !== "skill_duplicate"
    ) {
      return null;
    }
    const duplicates = (detail as { duplicate_skills?: unknown })
      .duplicate_skills;
    return Array.isArray(duplicates)
      ? duplicates.filter((name): name is string => typeof name === "string")
      : [];
  };

  const openDetail = (listing: SkillRepositoryListingItem) => {
    setDetailRepositoryId(listing.skill_repository_id);
  };

  const handleInstall = (listing: SkillRepositoryListingItem) => {
    const baseName = listing.name?.trim() || "Skill";
    setCopyListing(listing);
    setCopyTargetName(
      t("skillRepository.copy.defaultName", { name: baseName })
    );
    setCopyNameError(null);
  };

  const handleConfirmInstall = async () => {
    if (!copyListing) {
      return;
    }
    const targetName = copyTargetName.trim();
    if (!targetName) {
      setCopyNameError(t("skillRepository.copy.nameRequired"));
      return;
    }
    try {
      setCopyNameError(null);
      const result = await installMutation.mutateAsync({
        skillRepositoryId: copyListing.skill_repository_id,
        targetName,
      });
      message.success(
        result.name
          ? t("skillRepository.copy.successWithName", { name: result.name })
          : t("skillRepository.copy.success")
      );
      setCopyListing(null);
      setCopyTargetName("");
    } catch (error) {
      const duplicateNames = getDuplicateSkillNames(error);
      if (duplicateNames) {
        setCopyNameError(
          duplicateNames.length > 0
            ? t("skillRepository.copy.duplicateWithNames", {
                names: duplicateNames.join("、"),
              })
            : t("skillRepository.copy.duplicate")
        );
        return;
      }
      message.error(
        error instanceof Error
          ? error.message
          : t("skillRepository.copy.failed")
      );
    }
  };

  const handleUpdateStatus = async (
    listing: SkillRepositoryListingItem,
    status: SkillRepositoryListingStatus,
    content?: string
  ) => {
    try {
      await updateStatusMutation.mutateAsync({
        skillRepositoryId: listing.skill_repository_id,
        status,
        content,
      });
      message.success(
        t("skillRepository.action.success", {
          action: STATUS_ACTION_LABEL_KEYS[status]
            ? t(STATUS_ACTION_LABEL_KEYS[status])
            : getSkillRepositoryStatusLabel(t, status),
        })
      );
    } catch (error) {
      message.error(
        error instanceof Error
          ? error.message
          : t("skillRepository.common.statusUpdateFailed")
      );
    }
  };
  const confirmTakeDown = (listing: SkillRepositoryListingItem) => {
    modal.confirm({
      title: t("skillRepository.action.confirmTakeDown"),
      content: listing.name,
      okText: t("skillRepository.action.status.notShared"),
      cancelText: t("common.cancel"),
      okButtonProps: { danger: true },
      onOk: () => handleUpdateStatus(listing, "not_shared"),
    });
  };
  return (
    <>
      {active ? (
        <RepositoryView
          searchQuery={repositorySearch}
          onSearchChange={(value) => {
            setRepositorySearch(value);
            setRepositoryPage(1);
          }}
          tagDefinitions={tagDefinitions ?? []}
          tagPredicates={repositoryTagPredicates}
          onTagPredicatesChange={(value) => {
            setRepositoryTagPredicates(value);
            setRepositoryPage(1);
          }}
          listings={repositoryItems}
          isLoading={isRepositoryLoading}
          isError={isRepositoryError}
          isFetching={isRepositoryFetching}
          page={repositoryPage}
          pageSize={REPOSITORY_PAGE_SIZE}
          total={repositoryTotal}
          onPageChange={setRepositoryPage}
          onRetry={() => refetchRepository()}
          onInstall={handleInstall}
          onDetailClick={openDetail}
          showAdminMenu={isAdmin}
          onTakeDown={confirmTakeDown}
          installingRepositoryId={installingRepositoryId}
          takingDownRepositoryId={updatingRepositoryId}
        />
      ) : null}
      <SkillRepositoryDetailModal
        open={detailRepositoryId != null}
        detail={detailData}
        isLoading={isDetailLoading}
        isError={isDetailError}
        isFetching={isDetailFetching}
        onClose={() => setDetailRepositoryId(null)}
        onRetry={() => refetchDetail()}
      />
      <Modal
        centered
        destroyOnHidden
        title={t("skillRepository.copy.title")}
        open={copyListing != null}
        okText={t("skillRepository.copy.confirm")}
        cancelText={t("common.cancel")}
        confirmLoading={installMutation.isPending}
        onOk={handleConfirmInstall}
        onCancel={() => {
          setCopyListing(null);
          setCopyTargetName("");
          setCopyNameError(null);
        }}
      >
        <div className="space-y-2 pt-2">
          <label className="text-sm font-medium text-slate-700 dark:text-slate-200">
            {t("skillRepository.copy.nameLabel")}
          </label>
          <Input
            value={copyTargetName}
            status={copyNameError ? "error" : undefined}
            placeholder={t("skillRepository.copy.namePlaceholder")}
            maxLength={100}
            onChange={(event) => {
              setCopyTargetName(event.target.value);
              if (copyNameError) {
                setCopyNameError(null);
              }
            }}
            onPressEnter={handleConfirmInstall}
          />
          {copyNameError ? (
            <p className="text-sm text-red-500">{copyNameError}</p>
          ) : (
            <p className="text-sm text-slate-500">
              {t("skillRepository.copy.renameHint")}
            </p>
          )}
        </div>
      </Modal>
    </>
  );
}
