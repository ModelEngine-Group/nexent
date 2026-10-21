// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useTranslation } from "react-i18next";

export function AgentPublicationEmpty() {
  const { t } = useTranslation("common");

  return (
    <section
      data-testid="agent-publication-empty"
      aria-label={t("agent.highFidelity.publishMode")}
      className="mx-4 mb-5 flex min-h-0 flex-1 items-center justify-center rounded-lg bg-white px-6 py-10"
    >
      <div className="flex max-w-full flex-col items-center gap-4 text-center">
        <svg
          aria-hidden="true"
          width="120"
          height="104"
          viewBox="0 0 120 104"
          fill="none"
        >
          <ellipse cx="60" cy="96" rx="44" ry="4" fill="#F5F5F5" />
          <g stroke="#A3A3A3" strokeLinecap="round" strokeLinejoin="round">
            <path d="M45 16L42 9M60 13V5M75 16L79 9" />
            <path d="M20 42H78V91H20V42Z" fill="white" />
            <path
              d="M78 42H100V87C100 89.2 98.2 91 96 91H78V42Z"
              fill="#F5F5F5"
            />
            <path d="M20 42L10 60H66L78 42H20Z" fill="white" />
            <path d="M78 42L88 60H110L100 42H78Z" fill="#FAFAFA" />
          </g>
          <path d="M28 71H48V75H28V71Z" fill="#5B9BE6" />
          <path d="M28 79H43M28 84H36" stroke="#A3A3A3" strokeLinecap="round" />
        </svg>
        <div className="text-sm leading-[22px] text-[#808080]">
          <p>{t("agent.highFidelity.publicationEmpty.description")}</p>
          <p>{t("agent.highFidelity.publicationEmpty.access")}</p>
          <p>{t("agent.highFidelity.publicationEmpty.action")}</p>
        </div>
      </div>
    </section>
  );
}
