import { Alert, Button, Select, Switch, Tag } from "antd";
import { useTranslation } from "react-i18next";

import {
  FeatureCapabilityOverride,
  FeatureCapabilityProfile,
  EffectiveFeaturePolicy,
} from "@/types/modelConfig";

type Props = {
  baseline?: FeatureCapabilityProfile | null;
  effective?: FeatureCapabilityProfile | null;
  policy?: EffectiveFeaturePolicy | null;
  warnings?: string[];
  value: FeatureCapabilityOverride | null;
  onChange: (value: FeatureCapabilityOverride | null) => void;
};

const supportValue = (value: boolean | null | undefined) =>
  value === undefined ? "inherit" : value === null ? "unknown" : String(value);

const supportFromValue = (value: string): boolean | null | undefined =>
  value === "inherit"
    ? undefined
    : value === "unknown"
      ? null
      : value === "true";

const compactOverride = (
  value: FeatureCapabilityOverride
): FeatureCapabilityOverride | null => {
  const capabilityPatch = { ...(value.capabilityPatch || {}) };
  if (
    capabilityPatch.reasoning &&
    Object.keys(capabilityPatch.reasoning).length === 0
  )
    delete capabilityPatch.reasoning;
  if (
    capabilityPatch.promptCache &&
    Object.keys(capabilityPatch.promptCache).length === 0
  )
    delete capabilityPatch.promptCache;
  const policy = { ...(value.policy || {}) };
  if (policy.reasoning && Object.keys(policy.reasoning).length === 0)
    delete policy.reasoning;
  if (policy.promptCache && Object.keys(policy.promptCache).length === 0)
    delete policy.promptCache;
  if (
    Object.keys(capabilityPatch).length === 0 &&
    Object.keys(policy).length === 0
  )
    return null;
  return { schemaVersion: 1, capabilityPatch, policy };
};

const inheritedLabel = (value: unknown) =>
  value === null || value === undefined || value === "unknown"
    ? "unknown"
    : String(value);

export const ModelFeatureCapabilityFields = ({
  baseline,
  effective,
  policy,
  warnings = [],
  value,
  onChange,
}: Props) => {
  const { t } = useTranslation();
  const override: FeatureCapabilityOverride = value || { schemaVersion: 1 };

  const updateCapability = (
    branch: "reasoning" | "promptCache",
    field: string,
    next: unknown
  ) => {
    const capabilityPatch = { ...(override.capabilityPatch || {}) };
    const branchValue = { ...(capabilityPatch[branch] || {}) } as Record<
      string,
      unknown
    >;
    if (next === undefined) delete branchValue[field];
    else branchValue[field] = next;
    capabilityPatch[branch] = branchValue;
    onChange(compactOverride({ ...override, capabilityPatch }));
  };

  const updateCapabilityBranch = (
    branch: "reasoning" | "promptCache",
    updates: Record<string, unknown>
  ) => {
    const capabilityPatch = { ...(override.capabilityPatch || {}) };
    const branchValue = { ...(capabilityPatch[branch] || {}) } as Record<
      string,
      unknown
    >;
    Object.entries(updates).forEach(([field, next]) => {
      if (next === undefined) delete branchValue[field];
      else branchValue[field] = next;
    });
    capabilityPatch[branch] = branchValue;
    onChange(compactOverride({ ...override, capabilityPatch }));
  };

  const updatePolicy = (
    branch: "reasoning" | "promptCache",
    field: string,
    next: unknown
  ) => {
    const nextPolicy = { ...(override.policy || {}) };
    const branchValue = { ...(nextPolicy[branch] || {}) } as Record<
      string,
      unknown
    >;
    if (next === undefined) delete branchValue[field];
    else branchValue[field] = next;
    nextPolicy[branch] = branchValue;
    onChange(compactOverride({ ...override, policy: nextPolicy }));
  };

  const reasoningPatch = override.capabilityPatch?.reasoning;
  const cachePatch = override.capabilityPatch?.promptCache;
  const reasoningEffective = effective?.reasoning || baseline?.reasoning;
  const cacheEffective = effective?.promptCache || baseline?.promptCache;
  const reasoningMode = reasoningPatch?.mode || reasoningEffective?.mode;
  const reasoningSupported =
    reasoningPatch && "supported" in reasoningPatch
      ? reasoningPatch.supported
      : reasoningEffective?.supported;
  const reasoningEfforts =
    reasoningPatch?.efforts || reasoningEffective?.efforts || [];
  const cacheSupported =
    cachePatch && "supported" in cachePatch
      ? cachePatch.supported
      : cacheEffective?.supported;

  return (
    <div className="space-y-3 rounded-md border border-gray-200 p-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-sm font-medium text-gray-800">
            {t("model.dialog.capabilities.title")}
          </div>
          <div className="mt-1 text-xs text-gray-500">
            {t("model.dialog.capabilities.description")}
          </div>
        </div>
        <Button size="small" disabled={!value} onClick={() => onChange(null)}>
          {t("model.dialog.capabilities.restore")}
        </Button>
      </div>

      {warnings.includes("override_identity_mismatch") && (
        <Alert
          type="warning"
          showIcon
          message={t("model.dialog.capabilities.identityMismatch")}
        />
      )}
      {warnings.includes("invalid_feature_capability_override") && (
        <Alert
          type="error"
          showIcon
          message={t("model.dialog.capabilities.invalidOverride")}
        />
      )}

      <div className="grid gap-3 md:grid-cols-2">
        <section className="space-y-3 rounded-md bg-gray-50 p-3">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium">
              {t("model.dialog.capabilities.reasoning")}
            </span>
            <Tag color={policy?.reasoning.enabled ? "green" : "default"}>
              {policy?.reasoning.enabled
                ? t("model.dialog.capabilities.enabled")
                : t("model.dialog.capabilities.disabled")}
            </Tag>
          </div>
          <label className="block text-xs text-gray-600">
            {t("model.dialog.capabilities.support")}
            <Select
              className="mt-1 w-full"
              value={supportValue(reasoningPatch?.supported)}
              options={[
                {
                  value: "inherit",
                  label: `${t("model.dialog.capabilities.inherit")} (${inheritedLabel(baseline?.reasoning.supported)})`,
                },
                {
                  value: "true",
                  label: t("model.dialog.capabilities.supported"),
                },
                {
                  value: "false",
                  label: t("model.dialog.capabilities.unsupported"),
                },
                {
                  value: "unknown",
                  label: t("model.dialog.capabilities.unknown"),
                },
              ]}
              onChange={(selected) => {
                const supported = supportFromValue(selected);
                if (
                  supported === true &&
                  !["always", "toggle", "effort"].includes(reasoningMode || "")
                ) {
                  updateCapabilityBranch("reasoning", {
                    supported,
                    mode: "toggle",
                    requestStyle: "extra_body_enable_thinking",
                  });
                } else updateCapability("reasoning", "supported", supported);
              }}
            />
          </label>
          <label className="block text-xs text-gray-600">
            {t("model.dialog.capabilities.mode")}
            <Select
              className="mt-1 w-full"
              disabled={reasoningSupported !== true}
              value={reasoningPatch?.mode || "inherit"}
              options={["inherit", "always", "toggle", "effort"].map(
                (item) => ({
                  value: item,
                  label:
                    item === "inherit"
                      ? `${t("model.dialog.capabilities.inherit")} (${inheritedLabel(baseline?.reasoning.mode)})`
                      : item,
                })
              )}
              onChange={(selected) => {
                if (selected === "effort") {
                  const efforts = reasoningEfforts.length
                    ? reasoningEfforts
                    : ["low", "medium", "high"];
                  updateCapabilityBranch("reasoning", {
                    mode: "effort",
                    requestStyle: "openai_reasoning_effort",
                    efforts,
                    defaultEffort:
                      reasoningEffective?.defaultEffort ||
                      efforts[1] ||
                      efforts[0],
                  });
                  return;
                }
                updateCapabilityBranch("reasoning", {
                  mode: selected === "inherit" ? undefined : selected,
                  requestStyle:
                    selected === "toggle"
                      ? "extra_body_enable_thinking"
                      : selected === "effort"
                        ? "openai_reasoning_effort"
                        : undefined,
                });
              }}
            />
          </label>
          {reasoningMode === "effort" && (
            <>
              <label className="block text-xs text-gray-600">
                {t("model.dialog.capabilities.efforts")}
                <Select
                  mode="tags"
                  className="mt-1 w-full"
                  value={reasoningPatch?.efforts || []}
                  placeholder={reasoningEfforts.join(", ")}
                  onChange={(items) => {
                    const selectedDefault =
                      reasoningPatch?.defaultEffort ||
                      reasoningEffective?.defaultEffort;
                    updateCapabilityBranch("reasoning", {
                      efforts: items,
                      defaultEffort: items.includes(selectedDefault || "")
                        ? selectedDefault
                        : items[0],
                    });
                  }}
                />
              </label>
              <label className="block text-xs text-gray-600">
                {t("model.dialog.capabilities.defaultEffort")}
                <Select
                  className="mt-1 w-full"
                  allowClear
                  value={reasoningPatch?.defaultEffort}
                  placeholder={reasoningEffective?.defaultEffort || "medium"}
                  options={reasoningEfforts.map((effort) => ({
                    value: effort,
                    label: effort,
                  }))}
                  onChange={(selected) =>
                    updateCapability(
                      "reasoning",
                      "defaultEffort",
                      selected || undefined
                    )
                  }
                />
              </label>
            </>
          )}
          <div className="flex items-center justify-between text-xs text-gray-600">
            <span>{t("model.dialog.capabilities.defaultEnabled")}</span>
            <div className="flex items-center gap-2">
              <span>
                {override.policy?.reasoning?.enabled === undefined
                  ? t("model.dialog.capabilities.inherit")
                  : ""}
              </span>
              <Switch
                checked={
                  override.policy?.reasoning?.enabled ??
                  policy?.reasoning.enabled ??
                  false
                }
                disabled={
                  reasoningSupported !== true || reasoningMode === "always"
                }
                onChange={(checked) =>
                  updatePolicy("reasoning", "enabled", checked)
                }
              />
              {override.policy?.reasoning?.enabled !== undefined && (
                <Button
                  type="link"
                  size="small"
                  onClick={() =>
                    updatePolicy("reasoning", "enabled", undefined)
                  }
                >
                  {t("model.dialog.capabilities.inherit")}
                </Button>
              )}
            </div>
          </div>
        </section>

        <section className="space-y-3 rounded-md bg-gray-50 p-3">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium">
              {t("model.dialog.capabilities.promptCache")}
            </span>
            <Tag color={policy?.promptCache.enabled ? "green" : "default"}>
              {policy?.promptCache.enabled
                ? t("model.dialog.capabilities.enabled")
                : t("model.dialog.capabilities.disabled")}
            </Tag>
          </div>
          <label className="block text-xs text-gray-600">
            {t("model.dialog.capabilities.support")}
            <Select
              className="mt-1 w-full"
              value={supportValue(cachePatch?.supported)}
              options={[
                {
                  value: "inherit",
                  label: `${t("model.dialog.capabilities.inherit")} (${inheritedLabel(baseline?.promptCache.supported)})`,
                },
                {
                  value: "true",
                  label: t("model.dialog.capabilities.supported"),
                },
                {
                  value: "false",
                  label: t("model.dialog.capabilities.unsupported"),
                },
                {
                  value: "unknown",
                  label: t("model.dialog.capabilities.unknown"),
                },
              ]}
              onChange={(selected) => {
                const supported = supportFromValue(selected);
                if (
                  supported === true &&
                  ["none", "unknown", undefined].includes(cacheEffective?.mode)
                )
                  updateCapabilityBranch("promptCache", {
                    supported,
                    mode: "provider_automatic",
                  });
                else updateCapability("promptCache", "supported", supported);
              }}
            />
          </label>
          <label className="block text-xs text-gray-600">
            {t("model.dialog.capabilities.mode")}
            <Select
              className="mt-1 w-full"
              disabled={cacheSupported !== true}
              value={cachePatch?.mode || "inherit"}
              options={[
                "inherit",
                "openai_automatic",
                "provider_automatic",
                "anthropic_ephemeral",
              ].map((item) => ({
                value: item,
                label:
                  item === "inherit"
                    ? `${t("model.dialog.capabilities.inherit")} (${inheritedLabel(baseline?.promptCache.mode)})`
                    : item,
              }))}
              onChange={(selected) =>
                updateCapability(
                  "promptCache",
                  "mode",
                  selected === "inherit" ? undefined : selected
                )
              }
            />
          </label>
          <label className="flex items-center justify-between text-xs text-gray-600">
            {t("model.dialog.capabilities.metrics")}
            <Select
              className="w-40"
              value={supportValue(cachePatch?.metricsAvailable)}
              options={[
                {
                  value: "inherit",
                  label: t("model.dialog.capabilities.inherit"),
                },
                {
                  value: "true",
                  label: t("model.dialog.capabilities.available"),
                },
                {
                  value: "false",
                  label: t("model.dialog.capabilities.unavailable"),
                },
                {
                  value: "unknown",
                  label: t("model.dialog.capabilities.unknown"),
                },
              ]}
              onChange={(selected) =>
                updateCapability(
                  "promptCache",
                  "metricsAvailable",
                  supportFromValue(selected)
                )
              }
            />
          </label>
          <div className="flex items-center justify-between text-xs text-gray-600">
            <span>{t("model.dialog.capabilities.defaultEnabled")}</span>
            <div className="flex items-center gap-2">
              <span>
                {override.policy?.promptCache?.enabled === undefined
                  ? t("model.dialog.capabilities.inherit")
                  : ""}
              </span>
              <Switch
                checked={
                  override.policy?.promptCache?.enabled ??
                  policy?.promptCache.enabled ??
                  false
                }
                disabled={cacheSupported !== true}
                onChange={(checked) =>
                  updatePolicy("promptCache", "enabled", checked)
                }
              />
              {override.policy?.promptCache?.enabled !== undefined && (
                <Button
                  type="link"
                  size="small"
                  onClick={() =>
                    updatePolicy("promptCache", "enabled", undefined)
                  }
                >
                  {t("model.dialog.capabilities.inherit")}
                </Button>
              )}
            </div>
          </div>
        </section>
      </div>
    </div>
  );
};
