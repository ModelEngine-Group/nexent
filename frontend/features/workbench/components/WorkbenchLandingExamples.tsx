"use client";

import type { FC } from "react";
import { LightbulbIcon } from "lucide-react";
import { useAui } from "@assistant-ui/react";
import { useTranslation } from "react-i18next";
import { setWorkbenchComposerTag } from "@/features/workbench/lib/workbench-composer-tag";

export const WorkbenchLandingExamples: FC = () => {
  const aui = useAui();
  const { t } = useTranslation("common");

  const items = [
    {
      key: "agent",
      category: t("workbench.landingExamples.agent.category", "智能体创建"),
      template: t(
        "workbench.landingExamples.agent.template",
        "创建【智能体名称】智能体，面向[目标用户]的智能体，核心功能是[核心职能]。输出[输出形式]。必须[关键约束]。"
      ),
      description: t(
        "workbench.landingExamples.agent.description",
        "示例：面向慢病人群的健康管理智能体：用户上传体检报告，包含血压、血糖、身高体重、睡眠情况等指标，逐项解读并给出干预建议，对比历史数据说明变化趋势。"
      ),
    },
    {
      key: "skill",
      category: t("workbench.landingExamples.skill.category", "技能创建"),
      template: t(
        "workbench.landingExamples.skill.template",
        "创建一个名为[技能名称]的Skill，用于[技能用途，含触发场景]。（可选）执行步骤：[步骤1]→[步骤2]→[步骤3]。输入：[输入内容]；输出：[输出格式]。"
      ),
      description: t(
        "workbench.landingExamples.skill.description",
        "示例：分诊推荐技能：根据患者主诉症状输出建议科室与注意事项，在用户描述身体不适时触发，按步骤收集症状与病程信息，对照分诊规则区间匹配等级后输出分诊建议。"
      ),
    },
  ];

  return (
    <section
      aria-label={t("workbench.askMeLikeThis", "你可以这样问我")}
      className="mt-32 text-left"
    >
      <h2 className="text-base font-medium leading-[22px] text-black">
        {t("workbench.askMeLikeThis", "你可以这样问我")}
      </h2>
      <div className="mt-5 flex flex-col gap-6">
        {items.map(({ key, category, template, description }) => (
          <button
            key={key}
            type="button"
            onClick={() => {
              setWorkbenchComposerTag(category);
              aui.composer().setText(template);
              requestAnimationFrame(() =>
                document
                  .querySelector<HTMLTextAreaElement>(
                    "[data-workbench-composer]"
                  )
                  ?.focus()
              );
            }}
            className="flex w-full flex-col items-start rounded-lg text-left"
          >
            <span className="flex w-full items-center gap-2">
              <LightbulbIcon
                className="size-4 shrink-0 text-[#191919]"
                aria-hidden
              />
              <span className="shrink-0 text-base font-bold leading-6 text-[#191919]">
                {category}
              </span>
              <span
                className="shrink-0 text-base leading-6 text-[rgba(25,25,25,0.3)]"
                aria-hidden
              >
                |
              </span>
              <span className="min-w-0 flex-1 truncate text-base font-normal leading-6 text-[#191919]">
                {template}
              </span>
            </span>
            <span className="mt-1 block text-xs leading-5 text-[rgba(25,25,25,0.5)]">
              {description}
            </span>
          </button>
        ))}
      </div>
    </section>
  );
};
