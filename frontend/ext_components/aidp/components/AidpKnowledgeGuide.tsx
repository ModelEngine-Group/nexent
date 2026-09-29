"use client";

import React, { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button, Steps } from "antd";

/**
 * Collapsible guide shown above the AIDP knowledge base overview.
 *
 * The three steps describe the documented usage flow (create, upload, connect
 * an agent); they are explanatory only and do not add shortcuts. The guide
 * starts expanded and can be collapsed back to a single reopen entry without
 * touching the list state around it.
 */
const AidpKnowledgeGuide: React.FC = () => {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(true);

  return (
    <section className="w-full shrink-0">
      <div className="flex min-h-9 items-center justify-between gap-4">
        <h1 className="text-lg font-semibold text-gray-800">
          {t("aidpKnowledge.overviewTitle")}
        </h1>
        <Button
          type="link"
          size="small"
          className="px-0"
          onClick={() => setExpanded((previous) => !previous)}
          aria-expanded={expanded}
        >
          {expanded
            ? t("aidpKnowledge.guideCollapse")
            : t("aidpKnowledge.guideExpand")}
        </Button>
      </div>

      {expanded && (
        <div className="pb-5 pt-2">
          <p className="text-sm leading-6 text-gray-600">
            {t("aidpKnowledge.guideIntro")}
          </p>
          <Steps
            responsive
            size="small"
            className="mt-6"
            items={[
              { title: t("aidpKnowledge.guideStepCreate") },
              { title: t("aidpKnowledge.guideStepUpload") },
              { title: t("aidpKnowledge.guideStepAgent") },
            ]}
          />
        </div>
      )}
    </section>
  );
};

export default AidpKnowledgeGuide;
