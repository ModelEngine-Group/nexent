// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { Modal } from "antd";
import { useTranslation } from "react-i18next";

import type { ConfigItem, ConfigValue } from "../systemConfigData";
import { formatConfigValue } from "../systemConfigFormat";

export interface ConfigChange {
  item: ConfigItem;
  from: ConfigValue;
  to: ConfigValue;
}

interface SaveReviewModalProps {
  open: boolean;
  changes: ConfigChange[];
  saving: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}

export function SaveReviewModal({
  open,
  changes,
  saving,
  onCancel,
  onConfirm,
}: SaveReviewModalProps) {
  const { t } = useTranslation("common");

  return (
    <Modal
      open={open}
      onCancel={onCancel}
      onOk={onConfirm}
      confirmLoading={saving}
      okText={t("systemConfig.save.confirm")}
      cancelText={t("systemConfig.cancel")}
      width={680}
      title={t("systemConfig.save.title")}
    >
      <p className="text-[13px] leading-6 text-[var(--color-text-secondary)]">
        {t("systemConfig.save.description", { count: changes.length })}
      </p>
      <div className="mt-4 max-h-[50vh] overflow-auto rounded-lg border border-[var(--color-border-separator)]">
        <table className="w-full border-collapse text-[12px]">
          <thead className="bg-[var(--color-table-header)] text-left text-[var(--color-text-secondary)]">
            <tr>
              <th className="px-3 py-2 font-normal">
                {t("systemConfig.table.parameter")}
              </th>
              <th className="w-[120px] px-3 py-2 font-normal">
                {t("systemConfig.save.from")}
              </th>
              <th className="w-[120px] px-3 py-2 font-normal">
                {t("systemConfig.save.to")}
              </th>
              <th className="w-[190px] px-3 py-2 font-normal">
                {t("systemConfig.save.effect")}
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[var(--color-border-separator-subtle)]">
            {changes.map((change) => (
              <tr key={change.item.key}>
                <td className="px-3 py-2.5">
                  <div className="font-medium text-[var(--color-text-primary)]">
                    {t(change.item.label_key)}
                  </div>
                  <code className="font-mono text-[11px] text-[var(--color-text-secondary)]">
                    {change.item.key}
                  </code>
                </td>
                <td className="px-3 py-2.5 text-[var(--color-text-secondary)] line-through">
                  {formatConfigValue(change.item, change.from, t)}
                </td>
                <td className="px-3 py-2.5 font-medium text-[var(--color-brand)]">
                  {formatConfigValue(change.item, change.to, t)}
                </td>
                <td className="px-3 py-2.5 text-[var(--color-text-secondary)]">
                  {t(change.item.effect_key)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-4 text-[12px] text-[var(--color-text-secondary)]">
        {t("systemConfig.save.note")}
      </p>
    </Modal>
  );
}
