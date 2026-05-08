import { useEffect, useState } from "react";
import { Alert, Button, Form, Input, Modal, Radio } from "antd";
import { useTranslation } from "react-i18next";
import type {
  RegistryMcpCard,
  RegistryPackageArgumentInput,
  RegistryRemoteVariable,
} from "@/types/mcpTools";
import { useMcpFormRules } from "@/hooks/mcpTools/useMcpFormRules";
import { useMcpRegistryBrowser } from "@/hooks/mcpTools/useMcpRegistryBrowser";
import { useMcpRegistryQuickAdd } from "@/hooks/mcpTools/useMcpRegistryQuickAdd";
import McpRegistryToolbar from "./McpRegistryToolbar";
import McpRegistryCardList from "./McpRegistryCardList";
import McpRegistryDetailModal from "./McpRegistryDetailModal";
import ContainerPortField from "../../shared/ContainerPortField";
import { McpTransportType } from "@/const/mcpTools";

interface AddMcpServiceRegistrySectionProps {
  active: boolean;
  onAdded: () => void;
}

export default function AddMcpServiceRegistrySection({
  active,
  onAdded,
}: AddMcpServiceRegistrySectionProps) {
  const [selected, setSelected] = useState<RegistryMcpCard | null>(null);
  const browser = useMcpRegistryBrowser(active);
  const quickAdd = useMcpRegistryQuickAdd({ onSuccess: onAdded });

  if (!active) return null;

  return (
    <>
      <div className="px-6 py-5 space-y-5">
        <McpRegistryToolbar
          search={browser.filters.search}
          version={browser.filters.version}
          updatedSince={browser.filters.updatedSince}
          includeDeleted={browser.filters.includeDeleted}
          page={browser.page}
          resultCount={browser.services.length}
          onSearchChange={(value) => browser.updateFilter("search", value)}
          onVersionChange={(value) => browser.updateFilter("version", value)}
          onUpdatedSinceChange={(value) =>
            browser.updateFilter("updatedSince", value)
          }
          onIncludeDeletedChange={(value) =>
            browser.updateFilter("includeDeleted", value)
          }
        />

        <McpRegistryCardList
          loading={browser.loading}
          services={browser.services}
          hasPrevPage={browser.hasPrevPage}
          hasNextPage={browser.hasNextPage}
          onPrevPage={browser.prevPage}
          onNextPage={browser.nextPage}
          onSelect={setSelected}
          onQuickAdd={quickAdd.open}
        />
      </div>

      {selected ? (
        <McpRegistryDetailModal
          service={selected}
          onClose={() => setSelected(null)}
          onQuickAdd={quickAdd.open}
        />
      ) : null}

      <QuickAddPickerModal controller={quickAdd} />
    </>
  );
}

interface QuickAddPickerModalProps {
  controller: ReturnType<typeof useMcpRegistryQuickAdd>;
}

function QuickAddPickerModal({ controller }: QuickAddPickerModalProps) {
  const { t } = useTranslation("common");
  const [form] = Form.useForm();
  const rules = useMcpFormRules();
  const {
    visible,
    candidate,
    options,
    selectedOption,
    selectedKey,
    values,
    containerPort,
    submitting,
  } = controller;
  const unsupportedOci =
    selectedOption?.sourceType === "package" &&
    (selectedOption.packageRegistryType || "").trim().toLowerCase() === "oci";

  useEffect(() => {
    if (!visible) return;
    form.setFieldsValue({ selectedKey, containerPort, ...values });
  }, [visible, form, selectedKey, containerPort, values]);

  const handleConfirm = async () => {
    try {
      await form.validateFields();
    } catch {
      return;
    }
    await controller.confirm();
  };

  const renderVariableInputs = (
    titleKey: string,
    fields: RegistryRemoteVariable[] = []
  ) => {
    if (!fields.length) return null;
    return (
      <div className="space-y-3 rounded-md border border-slate-200 bg-slate-50 p-3">
        <p className="text-sm font-medium text-slate-800">{t(titleKey)}</p>
        {fields.map((field) => (
          <label
            key={`${selectedOption?.key || "option"}-${field.formKey || field.key}`}
            className="block text-sm text-slate-600"
          >
            <span className="font-medium text-slate-800 break-all">
              {field.label || field.key}
              {field.isRequired ? (
                <span className="ml-1 text-rose-500">*</span>
              ) : null}
            </span>
            {field.description ? (
              <p className="mt-1 text-xs text-slate-500">{field.description}</p>
            ) : null}
            <Form.Item
              name={field.formKey}
              className="mb-0"
              rules={rules.quickAddField(
                field.label || field.key,
                Boolean(field.isRequired)
              )}
            >
              <Input
                value={values[field.formKey || ""] || ""}
                onChange={(event) => {
                  controller.setValue(field.formKey || "", event.target.value);
                  form.setFieldValue(field.formKey, event.target.value);
                }}
                className="mt-2 w-full rounded-md"
                placeholder={
                  field.placeholder ||
                  field.default ||
                  field.format ||
                  t("mcpTools.registry.quickAddPicker.variablePlaceholder")
                }
              />
            </Form.Item>
            <div className="mt-1 flex flex-wrap gap-3 text-xs text-slate-500">
              {field.format ? (
                <span>
                  {t("mcpTools.registry.quickAddPicker.variableFormat")}:{" "}
                  {field.format}
                </span>
              ) : null}
              {field.default ? (
                <span>
                  {t("mcpTools.registry.quickAddPicker.variableDefault")}:{" "}
                  {field.default}
                </span>
              ) : null}
            </div>
          </label>
        ))}
      </div>
    );
  };

  const renderArgumentInputs = (
    args: RegistryPackageArgumentInput[] = [],
    title: string
  ) => {
    if (!args.length) return null;
    return (
      <div className="space-y-3 rounded-md border border-slate-200 bg-slate-50 p-3">
        <p className="text-sm font-medium text-slate-800">{title}</p>
        {args.map((arg) => (
          <label
            key={`${selectedOption?.key || "option"}-${arg.formKey}`}
            className="block text-sm text-slate-600"
          >
            <span className="font-medium text-slate-800 break-all">
              {arg.label}
              {arg.isRequired ? (
                <span className="ml-1 text-rose-500">*</span>
              ) : null}
            </span>
            <p className="mt-1 text-xs text-slate-500">
              {arg.type === "named"
                ? t("mcpTools.registry.quickAddPicker.runtimeNamed")
                : t("mcpTools.registry.quickAddPicker.runtimePositional")}
            </p>
            {arg.description ? (
              <p className="mt-1 text-xs text-slate-500">{arg.description}</p>
            ) : null}
            <Form.Item
              name={arg.formKey}
              className="mb-0"
              rules={rules.quickAddField(arg.label, Boolean(arg.isRequired))}
            >
              <Input
                value={values[arg.formKey] || ""}
                onChange={(event) => {
                  controller.setValue(arg.formKey, event.target.value);
                  form.setFieldValue(arg.formKey, event.target.value);
                }}
                className="mt-2 w-full rounded-md"
                placeholder={
                  arg.default ||
                  arg.format ||
                  t("mcpTools.registry.quickAddPicker.variablePlaceholder")
                }
              />
            </Form.Item>
            <div className="mt-1 flex flex-wrap gap-3 text-xs text-slate-500">
              {arg.format ? (
                <span>
                  {t("mcpTools.registry.quickAddPicker.variableFormat")}:{" "}
                  {arg.format}
                </span>
              ) : null}
              {arg.default ? (
                <span>
                  {t("mcpTools.registry.quickAddPicker.variableDefault")}:{" "}
                  {arg.default}
                </span>
              ) : null}
            </div>
          </label>
        ))}
      </div>
    );
  };

  return (
    <Modal
      open={visible}
      onCancel={controller.close}
      footer={null}
      title={t("mcpTools.registry.quickAddPicker.title")}
      centered
      destroyOnHidden
    >
      <Form
        form={form}
        layout="vertical"
        requiredMark={false}
        className="space-y-4"
      >
        <p className="text-sm text-slate-600">
          {t("mcpTools.registry.quickAddPicker.description", {
            name: candidate?.server?.name || "-",
          })}
        </p>

        <Form.Item
          name="selectedKey"
          className="mb-0"
          rules={[
            {
              required: true,
              message: t("mcpTools.registry.quickAddPicker.targetRequired"),
            },
          ]}
        >
          <Radio.Group
            value={selectedKey}
            onChange={(event) => {
              const next = String(event.target.value || "");
              controller.chooseOption(next);
              form.setFieldValue("selectedKey", next);
            }}
            className="flex w-full flex-col gap-2"
          >
            {options.map((option) => {
              const sourceLabel =
                option.sourceType === "remote"
                  ? t("mcpTools.registry.quickAddPicker.sourceRemote")
                  : t("mcpTools.registry.quickAddPicker.sourcePackage");
              return (
                <Radio
                  key={option.key}
                  value={option.key}
                  className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2"
                >
                  <div className="space-y-1">
                    <p className="text-xs text-slate-500">{sourceLabel}</p>
                    <p className="text-sm text-slate-800 break-all">
                      {option.sourceLabel}
                    </p>
                  </div>
                </Radio>
              );
            })}
          </Radio.Group>
        </Form.Item>

        {unsupportedOci ? (
          <Alert
            type="warning"
            showIcon
            title={t("mcpTools.registry.quickAddUnsupported")}
          />
        ) : (
          <>
            {selectedOption?.transportType === McpTransportType.CONTAINER ? (
              <div className="space-y-3 rounded-md border border-slate-200 bg-slate-50 p-3">
                <Form.Item
                  name="containerPort"
                  className="mb-0"
                  rules={rules.containerPort}
                >
                  <div>
                    <ContainerPortField
                      scope="registry"
                      containerPort={containerPort}
                      setContainerPort={(value) => {
                        controller.setContainerPort(value);
                        form.setFieldValue("containerPort", value);
                      }}
                    />
                  </div>
                </Form.Item>
              </div>
            ) : null}

            {renderVariableInputs(
              "mcpTools.registry.quickAddPicker.variablesTitle",
              selectedOption?.remoteVariables
            )}
            {renderVariableInputs(
              "mcpTools.registry.quickAddPicker.remoteHeadersTitle",
              selectedOption?.remoteHeaders
            )}
            {renderVariableInputs(
              "mcpTools.registry.quickAddPicker.packageTransportVariablesTitle",
              selectedOption?.packageTransportVariables
            )}
            {renderVariableInputs(
              "mcpTools.registry.quickAddPicker.packageTransportHeadersTitle",
              selectedOption?.packageTransportHeaders
            )}
            {renderVariableInputs(
              "mcpTools.registry.quickAddPicker.packageEnvironmentVariablesTitle",
              selectedOption?.packageEnvironmentVariables
            )}
            {renderArgumentInputs(
              selectedOption?.packageRuntimeArguments,
              t("mcpTools.registry.quickAddPicker.runtimeArgumentsTitle")
            )}
            {renderArgumentInputs(
              selectedOption?.packageArguments,
              t("mcpTools.registry.packageField.packageArguments")
            )}
          </>
        )}

        <div className="flex justify-end gap-2">
          <Button onClick={controller.close}>{t("common.cancel")}</Button>
          <Button
            type="primary"
            loading={submitting}
            disabled={!selectedKey || unsupportedOci}
            onClick={handleConfirm}
          >
            {t("mcpTools.registry.quickAddPicker.confirm")}
          </Button>
        </div>
      </Form>
    </Modal>
  );
}
