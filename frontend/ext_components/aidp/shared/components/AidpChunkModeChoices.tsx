// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React from "react";
import { useTranslation } from "react-i18next";

import { Radio } from "antd";

import styles from "@/ext_components/aidp/shared/components/AidpChunkModeChoices.module.css";

interface AidpChunkModeChoicesProps {
  value?: number;
  onChange?: (value: number) => void;
  disabled?: boolean;
}

const AidpChunkModeChoices: React.FC<AidpChunkModeChoicesProps> = ({
  value,
  onChange,
  disabled,
}) => {
  const { t } = useTranslation();

  return (
    <Radio.Group
      className="w-full"
      value={value}
      disabled={disabled}
      onChange={(event) => onChange?.(event.target.value)}
    >
      <div className={styles.chunkChoicesWrapper}>
        <div className={styles.chunkChoices}>
          <Radio
            value={0}
            className={`${styles.chunkOption} ${value === 0 ? styles.chunkOptionSelected : styles.chunkOptionUnselected}`}
          >
            <span className={styles.chunkOptionContent}>
              <span>{t("aidpKnowledge.createChunkModeSmart")}</span>
              <span className={styles.chunkOptionHint}>
                {t("aidpKnowledge.createChunkModeSmartHint")}
              </span>
            </span>
          </Radio>
          <Radio
            value={1}
            className={`${styles.chunkOption} ${value === 1 ? styles.chunkOptionSelected : styles.chunkOptionUnselected}`}
          >
            <span className={styles.chunkOptionContent}>
              <span>{t("aidpKnowledge.createChunkModeLegal")}</span>
              <span className={styles.chunkOptionHint}>
                {t("aidpKnowledge.createChunkModeLegalHint")}
              </span>
            </span>
          </Radio>
        </div>
      </div>
    </Radio.Group>
  );
};

export default AidpChunkModeChoices;
