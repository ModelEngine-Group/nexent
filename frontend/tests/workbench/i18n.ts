// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import zh from "@/public/locales/zh/common.json";
import en from "@/public/locales/en/common.json";

export async function initializeTestI18n(language = "zh") {
  await i18n.use(initReactI18next).init({
    lng: language,
    fallbackLng: "zh",
    defaultNS: "common",
    keySeparator: false,
    resources: { zh: { common: zh }, en: { common: en } },
    interpolation: { escapeValue: false },
  });
}
