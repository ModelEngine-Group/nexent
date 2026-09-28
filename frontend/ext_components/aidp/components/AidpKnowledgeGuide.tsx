"use client";

import React, { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button, Steps } from "antd";
import { DownOutlined, InfoCircleFilled, UpOutlined } from "@ant-design/icons";

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
    <div className="w-full bg-white border border-gray-200 rounded-md overflow-hidden">
      <button
        type="button"
        onClick={() => setExpanded((previous) => !previous)}
        aria-expanded={expanded}
        className="w-full flex items-center justify-between gap-2 px-4 py-3 text-left hover:bg-gray-50 transition-colors"
      >
        <span className="flex items-center gap-2 text-sm font-medium text-gray-800">
          <InfoCircleFilled style={{ color: "#1677ff" }} />
          {t("aidpKnowledge.guideTitle")}
        </span>
        <span className="flex items-center gap-1 text-xs text-gray-500">
          {expanded
            ? t("aidpKnowledge.guideCollapse")
            : t("aidpKnowledge.guideExpand")}
          {expanded ? <UpOutlined /> : <DownOutlined />}
        </span>
      </button>

      {expanded && (
        <div className="px-4 pb-4 border-t border-gray-100">
          <p className="mt-3 text-xs text-gray-600">
            {t("aidpKnowledge.guideIntro")}
          </p>
          <Steps
            size="small"
            className="mt-4"
            items={[
              { title: t("aidpKnowledge.guideStepCreate") },
              { title: t("aidpKnowledge.guideStepUpload") },
              { title: t("aidpKnowledge.guideStepAgent") },
            ]}
          />
        </div>
      )}
    </div>
  );
};

export default AidpKnowledgeGuide;
