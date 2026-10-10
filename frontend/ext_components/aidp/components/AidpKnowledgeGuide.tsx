"use client";

import React, { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "antd";
import { DownOutlined, UpOutlined } from "@ant-design/icons";
import { BookOpen, FolderPlus, Link2, Upload, Workflow } from "lucide-react";
import styles from "./AidpKnowledgeVisuals.module.css";

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

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      try {
        if (
          window.sessionStorage.getItem("aidpKnowledge.guideExpanded") ===
          "false"
        )
          setExpanded(false);
      } catch {
        // Keep the guide expanded when browser storage is unavailable.
      }
    });
    return () => window.cancelAnimationFrame(frame);
  }, []);

  const toggleGuide = () => {
    setExpanded((previous) => {
      const next = !previous;
      try {
        window.sessionStorage.setItem(
          "aidpKnowledge.guideExpanded",
          String(next)
        );
      } catch {
        // Keep the change in memory when browser storage is unavailable.
      }
      return next;
    });
  };

  return (
    <section className="w-full shrink-0">
      <div className={styles.guideHeader}>
        <h1>{t("aidpKnowledge.overviewTitle")}</h1>
        <Button
          type="link"
          size="small"
          className={styles.guideToggle}
          icon={expanded ? <UpOutlined /> : <DownOutlined />}
          iconPlacement="end"
          onClick={toggleGuide}
          aria-expanded={expanded}
        >
          {expanded
            ? t("aidpKnowledge.guideCollapse")
            : t("aidpKnowledge.guideExpand")}
        </Button>
      </div>

      {expanded && (
        <div className={styles.guideBody}>
          <div>
            <h2 className={styles.guideHeading}>
              <BookOpen size={16} aria-hidden="true" />
              {t("aidpKnowledge.guideWhatIs")}
            </h2>
            <p className={styles.guideIntro}>{t("aidpKnowledge.guideIntro")}</p>
          </div>
          <div className={styles.guideFlow}>
            <h2 className={styles.guideHeading}>
              <Workflow size={16} aria-hidden="true" />
              {t("aidpKnowledge.guideFlowTitle")}
            </h2>
            <div
              className={styles.guideSteps}
              aria-label={t("aidpKnowledge.guideTitle")}
            >
              {[
                {
                  title: t("aidpKnowledge.guideStepCreate"),
                  description: t("aidpKnowledge.guideStepCreateDescription"),
                  icon: FolderPlus,
                },
                {
                  title: t("aidpKnowledge.guideStepUpload"),
                  description: t("aidpKnowledge.guideStepUploadDescription"),
                  icon: Upload,
                },
                {
                  title: t("aidpKnowledge.guideStepAgent"),
                  description: t("aidpKnowledge.guideStepAgentDescription"),
                  icon: Link2,
                },
              ].map((step, index) => (
                <article key={step.title} className={styles.guideStep}>
                  <h3>
                    {t("aidpKnowledge.guideStepLabel", {
                      step: index + 1,
                      title: step.title,
                    })}
                  </h3>
                  <p>{step.description}</p>
                  <step.icon
                    className={styles.stepDecoration}
                    aria-hidden="true"
                  />
                </article>
              ))}
            </div>
          </div>
        </div>
      )}
    </section>
  );
};

export default AidpKnowledgeGuide;
