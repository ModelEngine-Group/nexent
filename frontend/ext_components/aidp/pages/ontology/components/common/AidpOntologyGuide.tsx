// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React from "react";
import { useTranslation } from "react-i18next";
import { BookOpen, Database, FolderPlus, Link2, Workflow } from "lucide-react";

import styles from "../../../knowledge-list/AidpKnowledgeGuide.module.css";

/**
 * Static tutorial shown above the ontology list.
 *
 * The three steps mirror the ontology usage flow (create the domain, build
 * entities/metadata/rules, bind it to a knowledge base). The expanded state is
 * owned by the list page header so the toggle can sit next to the page title.
 */
const AidpOntologyGuide: React.FC = () => {
  const { t } = useTranslation();

  return (
    <div className={styles.guideBody}>
      <div>
        <h2 className={styles.guideHeading}>
          <BookOpen size={16} aria-hidden="true" />
          {t("aidpKnowledge.ontologyGuideWhatIs")}
        </h2>
        <p className={styles.guideIntro}>
          {t("aidpKnowledge.ontologyGuideIntro")}
        </p>
        <ol className={styles.guideBenefits}>
          <li>{t("aidpKnowledge.ontologyGuideBenefitOne")}</li>
          <li>{t("aidpKnowledge.ontologyGuideBenefitTwo")}</li>
        </ol>
      </div>
      <div className={styles.guideFlow}>
        <h2 className={styles.guideHeading}>
          <Workflow size={16} aria-hidden="true" />
          {t("aidpKnowledge.ontologyGuideFlowTitle")}
        </h2>
        <div
          className={styles.guideSteps}
          aria-label={t("aidpKnowledge.ontologyGuideFlowTitle")}
        >
          {[
            {
              title: t("aidpKnowledge.ontologyGuideStepCreate"),
              description: t(
                "aidpKnowledge.ontologyGuideStepCreateDescription"
              ),
              icon: FolderPlus,
            },
            {
              title: t("aidpKnowledge.ontologyGuideStepBuild"),
              description: t("aidpKnowledge.ontologyGuideStepBuildDescription"),
              icon: Database,
            },
            {
              title: t("aidpKnowledge.ontologyGuideStepBind"),
              description: t("aidpKnowledge.ontologyGuideStepBindDescription"),
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
              <step.icon className={styles.stepDecoration} aria-hidden="true" />
            </article>
          ))}
        </div>
      </div>
    </div>
  );
};

export default AidpOntologyGuide;
