// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useTranslation } from "react-i18next";
import { useGlobalConfigStore } from "@/stores/global";

export function WorkbenchGreeting() {
  const { t } = useTranslation();
  const productName = useGlobalConfigStore(
    (state) => state.config.productName || "Nexent"
  );

  return (
    <div className="flex w-full flex-col items-center text-center">
      <h1 className="text-[36px] leading-[54px] text-[#191919]">
        <span className="font-bold">
          {t("workbench.landingGreetingHi", {
            defaultValue: "你好，我是{{productName}}",
            productName,
          })}
        </span>{" "}
        <span className="font-normal">
          {t("workbench.landingGreetingAsk", "需要我帮你做什么")}
        </span>
      </h1>
    </div>
  );
}
