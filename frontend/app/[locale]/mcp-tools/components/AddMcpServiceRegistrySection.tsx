import { Button, Modal, Radio } from "antd";
import McpRegistryToolbar from "./McpRegistryToolbar";
import McpRegistryCardList from "./McpRegistryCardList";
import McpRegistryDetailModal from "./McpRegistryDetailModal";
import type { RegistryMcpCard, RegistryQuickAddOption } from "@/types/mcpTools";

interface Props {
  registrySearchValue: string;
  selectedRegistryService: RegistryMcpCard | null;
  filteredRegistryServices: RegistryMcpCard[];
  registryLoading: boolean;
  registryPage: number;
  hasPrevRegistryPage: boolean;
  hasNextRegistryPage: boolean;
  registryVersion: string;
  registryUpdatedSince: string;
  registryIncludeDeleted: boolean;
  quickAddPickerVisible: boolean;
  quickAddCandidateService: RegistryMcpCard | null;
  quickAddOptions: RegistryQuickAddOption[];
  selectedQuickAddOptionKey: string;
  quickAddSubmitting: boolean;
  setRegistrySearchValue: (value: string) => void;
  setSelectedRegistryService: (service: RegistryMcpCard | null) => void;
  setRegistryVersion: (value: string) => void;
  setRegistryUpdatedSince: (value: string) => void;
  setRegistryIncludeDeleted: (value: boolean) => void;
  setSelectedQuickAddOptionKey: (value: string) => void;
  handleRegistryPrevPage: () => void;
  handleRegistryNextPage: () => void;
  handleQuickAddFromRegistry: (service: RegistryMcpCard) => void;
  handleCloseQuickAddPicker: () => void;
  handleConfirmQuickAddOption: () => Promise<void>;
  t: (key: string, params?: Record<string, unknown>) => string;
}

export default function AddMcpServiceRegistrySection({
  registrySearchValue,
  selectedRegistryService,
  filteredRegistryServices,
  registryLoading,
  registryPage,
  hasPrevRegistryPage,
  hasNextRegistryPage,
  registryVersion,
  registryUpdatedSince,
  registryIncludeDeleted,
  quickAddPickerVisible,
  quickAddCandidateService,
  quickAddOptions,
  selectedQuickAddOptionKey,
  quickAddSubmitting,
  setRegistrySearchValue,
  setSelectedRegistryService,
  setRegistryVersion,
  setRegistryUpdatedSince,
  setRegistryIncludeDeleted,
  setSelectedQuickAddOptionKey,
  handleRegistryPrevPage,
  handleRegistryNextPage,
  handleQuickAddFromRegistry,
  handleCloseQuickAddPicker,
  handleConfirmQuickAddOption,
  t,
}: Props) {
  return (
    <>
      <div className="px-6 py-5 space-y-5">
        <McpRegistryToolbar
          registrySearchValue={registrySearchValue}
          registryPage={registryPage}
          resultCount={filteredRegistryServices.length}
          registryVersion={registryVersion}
          registryUpdatedSince={registryUpdatedSince}
          registryIncludeDeleted={registryIncludeDeleted}
          onRegistrySearchChange={setRegistrySearchValue}
          onRegistryVersionChange={setRegistryVersion}
          onRegistryUpdatedSinceChange={setRegistryUpdatedSince}
          onRegistryIncludeDeletedChange={setRegistryIncludeDeleted}
          t={t}
        />

        <McpRegistryCardList
          registryLoading={registryLoading}
          services={filteredRegistryServices}
          hasPrevRegistryPage={hasPrevRegistryPage}
          hasNextRegistryPage={hasNextRegistryPage}
          onPrevRegistryPage={handleRegistryPrevPage}
          onNextRegistryPage={handleRegistryNextPage}
          onSelectRegistryService={setSelectedRegistryService}
          onQuickAddFromRegistry={handleQuickAddFromRegistry}
          t={t}
        />
      </div>

      {selectedRegistryService ? (
        <McpRegistryDetailModal
          service={selectedRegistryService}
          t={t}
          onClose={() => setSelectedRegistryService(null)}
          onQuickAddFromRegistry={handleQuickAddFromRegistry}
        />
      ) : null}

      <Modal
        open={quickAddPickerVisible}
        onCancel={handleCloseQuickAddPicker}
        footer={null}
        title={t("mcpTools.registry.quickAddPicker.title")}
        centered
        destroyOnHidden
      >
        <div className="space-y-4">
          <p className="text-sm text-slate-600">
            {t("mcpTools.registry.quickAddPicker.description", {
              name: quickAddCandidateService?.name || "-",
            })}
          </p>

          <Radio.Group
            value={selectedQuickAddOptionKey}
            onChange={(event) => setSelectedQuickAddOptionKey(String(event.target.value || ""))}
            className="flex w-full flex-col gap-2"
          >
            {quickAddOptions.map((option) => {
              const sourceLabel =
                option.sourceType === "remote"
                  ? t("mcpTools.registry.quickAddPicker.sourceRemote")
                  : t("mcpTools.registry.quickAddPicker.sourcePackage");

              return (
                <Radio
                  key={option.key}
                  value={option.key}
                  className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2"
                >
                  <div className="space-y-1">
                    <p className="text-xs text-slate-500">{sourceLabel}</p>
                    <p className="text-sm text-slate-800 break-all">{option.sourceLabel}</p>
                  </div>
                </Radio>
              );
            })}
          </Radio.Group>

          <div className="flex justify-end gap-2">
            <Button className="rounded-full" onClick={handleCloseQuickAddPicker}>
              {t("common.cancel")}
            </Button>
            <Button
              type="primary"
              className="rounded-full"
              loading={quickAddSubmitting}
              disabled={!selectedQuickAddOptionKey}
              onClick={() => {
                void handleConfirmQuickAddOption();
              }}
            >
              {t("mcpTools.registry.quickAddPicker.confirm")}
            </Button>
          </div>
        </div>
      </Modal>
    </>
  );
}
