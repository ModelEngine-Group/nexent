"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { App, Button } from "antd";
import { useTranslation } from "react-i18next";
import { Plus, Tag } from "lucide-react";
import { parseMcpReviewDeepLinkParams } from "@/lib/notificationNavigation";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { USER_ROLES } from "@/const/auth";
import { useMcpServicesList } from "@/hooks/mcpTools/useMcpServicesList";
import { useMyCommunityMcp } from "@/hooks/mcpTools/useMyCommunityMcp";
import { useMcpCommunityBrowser } from "@/hooks/mcpTools/useMcpCommunityBrowser";
import { useMcpCommunityReview } from "@/hooks/mcpTools/useMcpCommunityReview";
import { useMcpCommunityQuickAdd } from "@/hooks/mcpTools/useMcpCommunityQuickAdd";
import { useTagLibraries } from "@/hooks/useTagManagement";
import { deleteCommunityMcpTool } from "@/services/mcpToolsService";
import type { CommunityMcpCard, McpServiceItem } from "@/types/mcpTools";
import { McpToolsServicesTab } from "@/const/mcpTools";
import AddMcpServiceModal from "./components/add/AddMcpServiceModal";
import TagDefinitionManagementModal from "@/components/tag/TagDefinitionManagementModal";
import CommunityQuickAddModal from "./components/add/community/CommunityQuickAddModal";
import McpCommunityDetailModal from "./components/add/community/McpCommunityDetailModal";
import McpServiceDetailModal from "./components/McpServiceDetailModal";
import RepositoryMcpDetailModal from "./components/RepositoryMcpDetailModal";
import PublishedServiceDetailModal from "./components/PublishedServiceDetailModal";
import { getDeduplicatedMineItems } from "./mcp-space-shared";

export function useMcpSpaceController() {
  const { t } = useTranslation("common");
  const { message, modal } = App.useApp();
  const { user } = useAuthorizationContext();
  const router = useRouter();
  const params = useParams<{ locale: string }>();
  const locale = params.locale || "en";
  const searchParams = useSearchParams();
  const isAdmin = useMemo(
    () => user?.role === USER_ROLES.ADMIN || user?.role === USER_ROLES.SU,
    [user?.role]
  );

  const [tab, setTab] = useState<McpToolsServicesTab>(
    McpToolsServicesTab.REPOSITORY
  );
  const [showAddModal, setShowAddModal] = useState(false);
  const [tagManagementOpen, setTagManagementOpen] = useState(false);
  const { data: tagLibraries } = useTagLibraries();
  const defaultLibrary =
    tagLibraries?.find((lib) => lib.bucket_key === "default_resource") ?? null;
  const [selectedLocal, setSelectedLocal] = useState<McpServiceItem | null>(
    null
  );
  const [selectedRepository, setSelectedRepository] =
    useState<CommunityMcpCard | null>(null);
  const [selectedReview, setSelectedReview] = useState<CommunityMcpCard | null>(
    null
  );
  const [selectedPublished, setSelectedPublished] =
    useState<CommunityMcpCard | null>(null);

  const reviewDeepLink = useMemo(
    () => parseMcpReviewDeepLinkParams(searchParams),
    [searchParams]
  );

  useEffect(() => {
    const tabParam = searchParams.get("tab");
    /* eslint-disable react-hooks/set-state-in-effect -- URL changes select the requested tab. */
    if (tabParam === McpToolsServicesTab.MINE) {
      setTab(McpToolsServicesTab.MINE);
    } else if (tabParam === McpToolsServicesTab.REVIEW && isAdmin) {
      setTab(McpToolsServicesTab.REVIEW);
    } else if (tabParam === McpToolsServicesTab.REPOSITORY) {
      setTab(McpToolsServicesTab.REPOSITORY);
    }
    /* eslint-enable react-hooks/set-state-in-effect */
  }, [searchParams, isAdmin]);

  const handleReviewDeepLinkConsumed = useCallback(() => {
    router.replace(`/${locale}/mcp-space?tab=mine`);
  }, [locale, router]);

  const localList = useMcpServicesList();
  const myPublished = useMyCommunityMcp(
    tab === McpToolsServicesTab.MINE || Boolean(reviewDeepLink)
  );
  const repositoryBrowser = useMcpCommunityBrowser(
    tab === McpToolsServicesTab.REPOSITORY,
    6
  );
  const reviewBrowser = useMcpCommunityReview(isAdmin);
  const quickAdd = useMcpCommunityQuickAdd({
    onSuccess: () => setShowAddModal(false),
  });
  const isRepositoryInstalled = useCallback(
    (service: CommunityMcpCard) => {
      return localList.services.some((localService) => {
        if (localService.permission !== "EDIT") return false;
        if (
          service.communityId &&
          localService.communityId === service.communityId
        )
          return true;
        return localService.name === service.name;
      });
    },
    [localList.services]
  );
  const detailMcpIdRef = useRef<number | null>(null);

  useEffect(() => {
    if (!isAdmin && tab === McpToolsServicesTab.REVIEW) {
      /* eslint-disable react-hooks/set-state-in-effect -- Hide the admin tab when access changes. */
      setTab(McpToolsServicesTab.REPOSITORY);
      /* eslint-enable react-hooks/set-state-in-effect */
    }
  }, [isAdmin, tab]);

  const openAddModal = () => {
    setShowAddModal(true);
  };

  const openLocalDetail = (service: McpServiceItem) => {
    detailMcpIdRef.current = service.mcpId;
    setSelectedLocal(service);
  };

  const closeLocalDetail = () => {
    detailMcpIdRef.current = null;
    setSelectedLocal(null);
  };

  const handleToggled = async (mcpId: number) => {
    const result = await localList.refetch();
    const updated = result.data?.find((s) => s.mcpId === mcpId);
    if (updated && detailMcpIdRef.current === mcpId) {
      setSelectedLocal(updated);
    }
  };

  const handleRepositoryOffline = (service: CommunityMcpCard) => {
    if (!service.communityId) return;
    modal.confirm({
      title: t("mcpTools.mine.unpublishOnlineVersionTitle"),
      content: t("mcpTools.mine.unpublishOnlineVersionDescription", {
        name: service.name,
      }),
      okText: t("mcpTools.repository.offline"),
      cancelText: t("common.cancel"),
      okButtonProps: { danger: true },
      centered: true,
      onOk: async () => {
        try {
          await deleteCommunityMcpTool(service.communityId!);
          message.success(t("mcpTools.mine.unpublishOnlineVersionSuccess"));
          await Promise.all([
            repositoryBrowser.refetch(),
            myPublished.refetch(),
            localList.refetch(),
          ]);
        } catch {
          message.error(t("mcpTools.mine.unpublishOnlineVersionFailed"));
        }
      },
    });
  };

  const repositoryCount = repositoryBrowser.services.length;
  const mineCount = getDeduplicatedMineItems(
    localList.services,
    myPublished.items
  ).length;
  const pendingReviewCount = reviewBrowser.services.filter(
    (s) => (s.reviewStatus || "pending") === "pending"
  ).length;

  const searchActions =
    tab === McpToolsServicesTab.MINE ? (
      <>
        <Button
          type="primary"
          className="flex h-11 shrink-0 items-center gap-1.5"
          icon={<Plus className="size-4" />}
          onClick={openAddModal}
        >
          {t("mcpTools.addModal.title")}
        </Button>
        <Button
          className="flex h-11 shrink-0 items-center gap-1.5"
          icon={<Tag className="size-4" />}
          onClick={() => setTagManagementOpen(true)}
        >
          {t("mcpTools.tagManagement")}
        </Button>
      </>
    ) : null;

  const onReviewed = async () => {
    await Promise.all([
      reviewBrowser.refetch(),
      repositoryBrowser.refetch(),
      myPublished.refetch(),
      localList.refetch(),
    ]);
  };

  const dialogs = (
    <>
      {selectedLocal ? (
        <McpServiceDetailModal
          selectedService={selectedLocal}
          onClose={closeLocalDetail}
          onToggled={handleToggled}
        />
      ) : null}

      {selectedRepository ? (
        <RepositoryMcpDetailModal
          service={selectedRepository}
          installed={isRepositoryInstalled(selectedRepository)}
          onClose={() => setSelectedRepository(null)}
          onInstall={quickAdd.open}
        />
      ) : null}

      {selectedReview ? (
        <McpCommunityDetailModal
          service={selectedReview}
          onClose={() => setSelectedReview(null)}
        />
      ) : null}

      <PublishedServiceDetailModal
        open={Boolean(selectedPublished)}
        service={selectedPublished}
        onClose={() => setSelectedPublished(null)}
      />

      {quickAdd.visible ? (
        <CommunityQuickAddModal controller={quickAdd} />
      ) : null}

      <AddMcpServiceModal
        open={showAddModal}
        onClose={() => setShowAddModal(false)}
      />

      <TagDefinitionManagementModal
        open={tagManagementOpen}
        onClose={() => setTagManagementOpen(false)}
        bucketId={defaultLibrary?.bucket_id ?? 0}
        bucketName={defaultLibrary?.bucket_name ?? ""}
        canManage={true}
      />
    </>
  );

  return {
    tab,
    setTab,
    isAdmin,
    repositoryCount,
    mineCount,
    pendingReviewCount,
    repositoryProps: {
      browser: repositoryBrowser,
      localServices: localList.services,
      isAdmin,
      actions: searchActions,
      onSelect: setSelectedRepository,
      onInstall: quickAdd.open,
      onOffline: handleRepositoryOffline,
    },
    mineProps: {
      localList,
      myPublished,
      actions: searchActions,
      reviewDeepLink,
      onReviewDeepLinkConsumed: handleReviewDeepLinkConsumed,
      onAdd: openAddModal,
      onEditLocal: openLocalDetail,
      onEditCommunity: setSelectedPublished,
      onToggled: handleToggled,
    },
    reviewProps: {
      browser: reviewBrowser,
      onSelect: setSelectedReview,
      onReviewed,
    },
    dialogs,
  };
}
