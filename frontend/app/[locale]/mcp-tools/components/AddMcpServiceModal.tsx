import { useEffect, useState } from "react";
import { App, Modal, Segmented } from "antd";
import { useTranslation } from "react-i18next";
import { MCP_TAB } from "@/const/mcpTools";
import type { McpTab } from "@/types/mcpTools";
import { useMcpToolsAddLocal } from "@/hooks/mcpTools/useMcpToolsAddLocal";
import { useMcpToolsAddRegistry } from "@/hooks/mcpTools/useMcpToolsAddRegistry";
import { useMcpToolsAddCommunity } from "@/hooks/mcpTools/useMcpToolsAddCommunity";
import AddMcpServiceLocalSection from "./AddMcpServiceLocalSection";
import AddMcpServiceRegistrySection from "./AddMcpServiceRegistrySection";
import AddMcpServiceCommunitySection from "./AddMcpServiceCommunitySection";

interface AddMcpServiceModalProps {
  open: boolean;
  onServiceAdded: () => Promise<unknown>;
  onClose: () => void;
}

export default function AddMcpServiceModal({
  open,
  onServiceAdded,
  onClose,
}: AddMcpServiceModalProps) {
  const { message } = App.useApp();
  const { t } = useTranslation("common");
  const [addModalTab, setAddModalTab] = useState<McpTab>(MCP_TAB.LOCAL);

  const local = useMcpToolsAddLocal({
    addModalTab,
    t: (key) => String(t(key)),
    message,
    onServiceAdded,
    onClose,
  });

  const registry = useMcpToolsAddRegistry({
    open,
    addModalTab,
    t: (key) => String(t(key)),
    message,
    onServiceAdded,
    onClose,
  });

  const community = useMcpToolsAddCommunity({
    open,
    addModalTab,
    t: (key) => String(t(key)),
    message,
    onServiceAdded,
    onClose,
  });

  const { reset: resetLocal } = local;
  const { reset: resetRegistry } = registry;
  const { reset: resetCommunity } = community;

  useEffect(() => {
    if (!open) {
      setAddModalTab(MCP_TAB.LOCAL);
      resetLocal();
      resetRegistry();
      resetCommunity();
    }
  }, [open, resetLocal, resetRegistry, resetCommunity]);

  if (!open) {
    return null;
  }

  return (
    <Modal
      open
      footer={null}
      closable
      centered
      width={addModalTab === MCP_TAB.LOCAL ? 900 : 1200}
      onCancel={onClose}
      styles={{
        mask: { background: "rgba(15,23,42,0.6)", backdropFilter: "blur(2px)" },
        body: { padding: 0 },
      }}
    >
      <div>
        <div className="border-b border-slate-100 px-6 py-5">
          <div>
            <h2 className="text-2xl font-semibold text-slate-900">{t("mcpTools.addModal.title")}</h2>
          </div>
        </div>

        <div className="px-6 pt-4">
          <Segmented
            value={addModalTab}
            onChange={(value) => setAddModalTab(value as McpTab)}
            options={[
              { label: t("mcpTools.addModal.tabLocal"), value: MCP_TAB.LOCAL },
              { label: t("mcpTools.addModal.tabRegistry"), value: MCP_TAB.MCP_REGISTRY },
              { label: t("mcpTools.addModal.tabCommunity"), value: MCP_TAB.COMMUNITY },
            ]}
            className="h-9 rounded-full border border-slate-200 bg-slate-100 p-[2px] text-sm [&_.ant-segmented-group]:h-full [&_.ant-segmented-item]:rounded-full [&_.ant-segmented-item-label]:px-4 [&_.ant-segmented-item-label]:leading-[30px] [&_.ant-segmented-thumb]:rounded-full [&_.ant-segmented-thumb]:bg-white [&_.ant-segmented-thumb]:shadow-sm [&_.ant-segmented-thumb]:top-[2px] [&_.ant-segmented-thumb]:bottom-[2px]"
          />
        </div>

        {addModalTab === MCP_TAB.LOCAL ? (
          <AddMcpServiceLocalSection
            newServiceName={local.newServiceName}
            newServiceDesc={local.newServiceDesc}
            newTransportType={local.newTransportType}
            newServiceUrl={local.newServiceUrl}
            newServiceAuthorizationToken={local.newServiceAuthorizationToken}
            containerConfigJson={local.containerConfigJson}
            containerPort={local.containerPort}
            newTagDrafts={local.newTagDrafts}
            newTagInputValue={local.newTagInputValue}
            addingService={local.addingService}
            setNewServiceName={local.setNewServiceName}
            setNewServiceDesc={local.setNewServiceDesc}
            setNewTransportType={local.setNewTransportType}
            setNewServiceUrl={local.setNewServiceUrl}
            setNewServiceAuthorizationToken={local.setNewServiceAuthorizationToken}
            setContainerConfigJson={local.setContainerConfigJson}
            setContainerPort={local.setContainerPort}
            addNewTag={local.addNewTag}
            removeNewTag={local.removeNewTag}
            setNewTagInputValue={local.setNewTagInputValue}
            handleAddService={local.handleAddService}
            t={(key, params) => String(t(key, params))}
          />
        ) : addModalTab === MCP_TAB.MCP_REGISTRY ? (
          <AddMcpServiceRegistrySection
            registrySearchValue={registry.registrySearchValue}
            selectedRegistryService={registry.selectedRegistryService}
            filteredRegistryServices={registry.filteredRegistryServices}
            registryLoading={registry.registryLoading}
            registryPage={registry.registryPage}
            hasPrevRegistryPage={registry.hasPrevRegistryPage}
            hasNextRegistryPage={registry.hasNextRegistryPage}
            registryVersion={registry.registryVersion}
            registryUpdatedSince={registry.registryUpdatedSince}
            registryIncludeDeleted={registry.registryIncludeDeleted}
            quickAddPickerVisible={registry.quickAddPickerVisible}
            quickAddCandidateService={registry.quickAddCandidateService}
            quickAddOptions={registry.quickAddOptions}
            selectedQuickAddOptionKey={registry.selectedQuickAddOptionKey}
            quickAddSubmitting={registry.quickAddSubmitting}
            setRegistrySearchValue={registry.setRegistrySearchValue}
            setSelectedRegistryService={registry.setSelectedRegistryService}
            setRegistryVersion={registry.setRegistryVersion}
            setRegistryUpdatedSince={registry.setRegistryUpdatedSince}
            setRegistryIncludeDeleted={registry.setRegistryIncludeDeleted}
            setSelectedQuickAddOptionKey={registry.setSelectedQuickAddOptionKey}
            handleRegistryPrevPage={registry.handleRegistryPrevPage}
            handleRegistryNextPage={registry.handleRegistryNextPage}
            handleQuickAddFromRegistry={registry.handleQuickAddFromRegistry}
            handleCloseQuickAddPicker={registry.handleCloseQuickAddPicker}
            handleConfirmQuickAddOption={registry.handleConfirmQuickAddOption}
            t={(key, params) => String(t(key, params))}
          />
        ) : (
          <AddMcpServiceCommunitySection
            communitySearchValue={community.communitySearchValue}
            selectedCommunityService={community.selectedCommunityService}
            filteredCommunityServices={community.filteredCommunityServices}
            communityLoading={community.communityLoading}
            communityPage={community.communityPage}
            hasPrevCommunityPage={community.hasPrevCommunityPage}
            hasNextCommunityPage={community.hasNextCommunityPage}
            quickAddConfirmVisible={community.quickAddConfirmVisible}
            quickAddSourceService={community.quickAddSourceService}
            quickAddDraft={community.quickAddDraft}
            setCommunitySearchValue={community.setCommunitySearchValue}
            setSelectedCommunityService={community.setSelectedCommunityService}
            updateQuickAddDraft={community.updateQuickAddDraft}
            addQuickAddTag={community.addQuickAddTag}
            removeQuickAddTag={community.removeQuickAddTag}
            handleCommunityPrevPage={community.handleCommunityPrevPage}
            handleCommunityNextPage={community.handleCommunityNextPage}
            handleQuickAddFromCommunity={community.handleQuickAddFromCommunity}
            handleCloseQuickAddConfirm={community.handleCloseQuickAddConfirm}
            handleConfirmQuickAddFromCommunity={community.handleConfirmQuickAddFromCommunity}
            quickAddSubmitting={community.quickAddSubmitting}
            t={(key, params) => String(t(key, params))}
          />
        )}
      </div>
    </Modal>
  );
}
