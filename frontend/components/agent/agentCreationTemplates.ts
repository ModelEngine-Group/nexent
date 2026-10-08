export interface AgentCreationTemplate {
  id: string;
  titleKey: string;
  descriptionKey: string;
  tagKey: string;
  iconClassName: string;
}

/**
 * Temporary frontend-only template metadata for the creation modal.
 * Replace this catalog with the repository API when a template contract is available.
 */
export const AGENT_CREATION_TEMPLATES: AgentCreationTemplate[] = [
  {
    id: "cardiomyopathy-screening",
    titleKey: "agentConfig.createModal.templates.cardiomyopathy.title",
    descriptionKey:
      "agentConfig.createModal.templates.cardiomyopathy.description",
    tagKey: "agentConfig.createModal.templates.medicalTag",
    iconClassName: "bg-[#8b78e6]",
  },
  {
    id: "medication-safety",
    titleKey: "agentConfig.createModal.templates.medicationSafety.title",
    descriptionKey:
      "agentConfig.createModal.templates.medicationSafety.description",
    tagKey: "agentConfig.createModal.templates.medicalTag",
    iconClassName: "bg-[#65c7c9]",
  },
  {
    id: "health-report",
    titleKey: "agentConfig.createModal.templates.healthReport.title",
    descriptionKey:
      "agentConfig.createModal.templates.healthReport.description",
    tagKey: "agentConfig.createModal.templates.medicalTag",
    iconClassName: "bg-[#d875c5]",
  },
  {
    id: "medical-literature",
    titleKey: "agentConfig.createModal.templates.medicalLiterature.title",
    descriptionKey:
      "agentConfig.createModal.templates.medicalLiterature.description",
    tagKey: "agentConfig.createModal.templates.medicalTag",
    iconClassName: "bg-[#e66b78]",
  },
];
