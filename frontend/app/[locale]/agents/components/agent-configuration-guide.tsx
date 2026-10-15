"use client";

import { Info, Workflow } from "lucide-react";
import { useTranslation } from "react-i18next";

const STEP_KEYS = [
  "create",
  "configure",
  "personalize",
  "publish",
  "use",
] as const;

export default function AgentConfigurationGuide() {
  const { t } = useTranslation("common");

  return (
    <div className="flex min-w-0 flex-col gap-6 tracking-[0px]">
      <div
        data-testid="agent-guide-introduction"
        className="flex flex-col gap-3"
      >
        <h2 className="flex h-6 items-center gap-2 text-[16px] font-medium leading-6 text-[#191919]">
          <Info className="size-4 shrink-0" aria-hidden="true" />
          <span>{t("agentConfig.guide.title")}</span>
        </h2>
        <p className="text-[14px] font-normal leading-[22px] text-[#191919]">
          {t("agentConfig.guide.description")}
        </p>
        <ol className="list-decimal pl-5 text-[14px] font-normal leading-[22px] text-[#777777]">
          <li>{t("agentConfig.guide.point.one")}</li>
          <li>{t("agentConfig.guide.point.two")}</li>
        </ol>
      </div>

      <div data-testid="agent-guide-process" className="flex flex-col gap-3">
        <h2 className="flex h-6 items-center gap-2 text-[16px] font-medium leading-6 text-[#191919]">
          <Workflow className="size-4 shrink-0" aria-hidden="true" />
          <span>{t("agentConfig.guide.process.title")}</span>
        </h2>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
          {STEP_KEYS.map((key, index) => (
            <div
              key={key}
              data-testid="agent-guide-step"
              className="relative flex min-h-[156px] w-full min-w-0 flex-col overflow-hidden rounded-[8px] px-[21.09px] py-6 shadow-[inset_0_0_20px_0_rgba(239,239,239,0.3)] ring-1 ring-inset ring-white [background:linear-gradient(180deg,rgba(236,243,255,1)_19.667%,rgba(252,253,253,1)_101.235%)]"
            >
              <h3 className="text-[18px] font-medium leading-[26px] text-[#191919]">
                {t("agentConfig.guide.stepLabel", { number: index + 1 })}
                {t(`agentConfig.guide.step.${key}.title`)}
              </h3>
              <p className="mt-4 text-[14px] font-normal leading-[22px] text-[#777777]">
                {t(`agentConfig.guide.step.${key}.description`)}
              </p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
