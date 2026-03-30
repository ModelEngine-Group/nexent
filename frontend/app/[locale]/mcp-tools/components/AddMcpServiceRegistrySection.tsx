import { Button, Input, Modal, Radio } from "antd";
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
  quickAddVariableValues: Record<string, string>;
  quickAddSubmitting: boolean;
  setRegistrySearchValue: (value: string) => void;
  setSelectedRegistryService: (service: RegistryMcpCard | null) => void;
  setRegistryVersion: (value: string) => void;
  setRegistryUpdatedSince: (value: string) => void;
  setRegistryIncludeDeleted: (value: boolean) => void;
  setSelectedQuickAddOptionKey: (value: string) => void;
  handleQuickAddVariableValueChange: (key: string, value: string) => void;
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
  quickAddVariableValues,
  quickAddSubmitting,
  setRegistrySearchValue,
  setSelectedRegistryService,
  setRegistryVersion,
  setRegistryUpdatedSince,
  setRegistryIncludeDeleted,
  setSelectedQuickAddOptionKey,
  handleQuickAddVariableValueChange,
  handleRegistryPrevPage,
  handleRegistryNextPage,
  handleQuickAddFromRegistry,
  handleCloseQuickAddPicker,
  handleConfirmQuickAddOption,
  t,
}: Props) {
  const selectedQuickAddOption = quickAddOptions.find((option) => option.key === selectedQuickAddOptionKey) || null;

  const renderVariableInputs = (
    titleKey: string,
    fields: Array<{
      key: string;
      formKey?: string;
      label?: string;
      description?: string;
      format?: string;
      default?: string;
      placeholder?: string;
      isRequired?: boolean;
    }>
  ) => {
    if (!fields.length) return null;

    return (
      <div className="space-y-3 rounded-xl border border-slate-200 bg-slate-50 p-3">
        <p className="text-sm font-medium text-slate-800">{t(titleKey)}</p>
        {fields.map((field) => (
          <label key={`${selectedQuickAddOption?.key || "option"}-${field.formKey || field.key}`} className="block text-sm text-slate-600">
            <span className="font-medium text-slate-800 break-all">
              {field.label || field.key}
              {field.isRequired ? <span className="ml-1 text-rose-500">*</span> : null}
            </span>
            {field.description ? <p className="mt-1 text-xs text-slate-500">{field.description}</p> : null}
            <Input
              value={quickAddVariableValues[field.formKey || ""] || ""}
              onChange={(event) => handleQuickAddVariableValueChange(field.formKey || "", event.target.value)}
              className="mt-2 w-full rounded-xl"
              placeholder={field.placeholder || field.default || field.format || t("mcpTools.registry.quickAddPicker.variablePlaceholder")}
            />
            <div className="mt-1 flex flex-wrap gap-3 text-xs text-slate-500">
              {field.format ? (
                <span>{t("mcpTools.registry.quickAddPicker.variableFormat")}: {field.format}</span>
              ) : null}
              {field.default ? (
                <span>{t("mcpTools.registry.quickAddPicker.variableDefault")}: {field.default}</span>
              ) : null}
            </div>
          </label>
        ))}
      </div>
    );
  };

  const renderRuntimeArgumentInputs = () => {
    const args = selectedQuickAddOption?.packageRuntimeArguments || [];
    if (!args.length) return null;

    return (
      <div className="space-y-3 rounded-xl border border-slate-200 bg-slate-50 p-3">
        <p className="text-sm font-medium text-slate-800">{t("mcpTools.registry.quickAddPicker.runtimeArgumentsTitle")}</p>
        {args.map((arg) => (
          <label key={`${selectedQuickAddOption?.key || "option"}-${arg.formKey}`} className="block text-sm text-slate-600">
            <span className="font-medium text-slate-800 break-all">
              {arg.label}
              {arg.isRequired ? <span className="ml-1 text-rose-500">*</span> : null}
            </span>
            <p className="mt-1 text-xs text-slate-500">
              {arg.type === "named" ? t("mcpTools.registry.quickAddPicker.runtimeNamed") : t("mcpTools.registry.quickAddPicker.runtimePositional")}
            </p>
            {arg.description ? <p className="mt-1 text-xs text-slate-500">{arg.description}</p> : null}
            <Input
              value={quickAddVariableValues[arg.formKey] || ""}
              onChange={(event) => handleQuickAddVariableValueChange(arg.formKey, event.target.value)}
              className="mt-2 w-full rounded-xl"
              placeholder={arg.default || arg.format || t("mcpTools.registry.quickAddPicker.variablePlaceholder")}
            />
            <div className="mt-1 flex flex-wrap gap-3 text-xs text-slate-500">
              {arg.format ? <span>{t("mcpTools.registry.quickAddPicker.variableFormat")}: {arg.format}</span> : null}
              {arg.default ? <span>{t("mcpTools.registry.quickAddPicker.variableDefault")}: {arg.default}</span> : null}
            </div>
          </label>
        ))}
      </div>
    );
  };

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

          {renderVariableInputs("mcpTools.registry.quickAddPicker.variablesTitle", selectedQuickAddOption?.remoteVariables || [])}
          {renderVariableInputs("mcpTools.registry.quickAddPicker.packageTransportVariablesTitle", selectedQuickAddOption?.packageTransportVariables || [])}
          {renderVariableInputs("mcpTools.registry.quickAddPicker.packageTransportHeadersTitle", selectedQuickAddOption?.packageTransportHeaders || [])}
          {renderVariableInputs("mcpTools.registry.quickAddPicker.packageEnvironmentVariablesTitle", selectedQuickAddOption?.packageEnvironmentVariables || [])}
          {renderRuntimeArgumentInputs()}

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
