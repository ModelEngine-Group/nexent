"use client";

import { useEffect, useState } from "react";
import { Alert, Form, Modal, Spin } from "antd";
import { useTranslation } from "react-i18next";

import { Skill } from "@/types/agentConfig";
import type { SkillFileContent, SkillFileNode, SkillFormData } from "@/types/skill";
import {
  fetchSkillFileContent,
  fetchSkillFiles,
  SkillFilesAccessDeniedError,
} from "@/services/agentConfigService";
import { normalizeSkillFiles } from "@/lib/skillFileUtils";
import log from "@/lib/logger";
import SkillDraftPanel from "./SkillDraftPanel";

interface SkillDetailModalProps {
  skill: Skill | null;
  open: boolean;
  onClose: () => void;
}

const OFFICIAL_SOURCES = new Set(["official", "\u5b98\u65b9"]);

export default function SkillDetailModal({ skill, open, onClose }: SkillDetailModalProps) {
  const { t } = useTranslation("common");
  const [form] = Form.useForm<SkillFormData>();
  const [skillTabs, setSkillTabs] = useState<SkillFileContent[]>([
    { path: "SKILL.md", content: "" },
  ]);
  const [activeSkillTab, setActiveSkillTab] = useState("SKILL.md");
  const [loading, setLoading] = useState(false);
  const [fileTreeMessage, setFileTreeMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!open || !skill) return;

    let cancelled = false;
    form.setFieldsValue({
      name: skill.name,
      description: skill.description || "",
      source: formatSource(skill.source, t),
      tags: Array.isArray(skill.tags) ? skill.tags : [],
      content: skill.content || "",
    });
    setSkillTabs([{ path: "SKILL.md", content: skill.content || "" }]);
    setActiveSkillTab("SKILL.md");
    setFileTreeMessage(null);

    const loadFiles = async () => {
      setLoading(true);
      try {
        const files = await fetchSkillFiles(skill.name);
        const flatFiles = flattenSkillFiles(normalizeSkillFiles(files), skill.name);
        if (flatFiles.length === 0) {
          return;
        }

        const tabs = await Promise.all(
          flatFiles.map(async (path) => {
            try {
              const content = await fetchSkillFileContent(skill.name, path);
              return { path, content: content || "" };
            } catch (error) {
              log.error("Failed to load skill file content:", error);
              return { path, content: "" };
            }
          })
        );

        if (!cancelled) {
          setSkillTabs(sortSkillTabs(tabs));
          setActiveSkillTab(sortSkillTabs(tabs)[0]?.path || "SKILL.md");
        }
      } catch (error) {
        if (cancelled) return;
        if (error instanceof SkillFilesAccessDeniedError) {
          setFileTreeMessage(error.message);
        } else {
          log.error("Failed to load skill files:", error);
          setFileTreeMessage(t("skillManagement.detail.noFiles"));
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };

    void loadFiles();

    return () => {
      cancelled = true;
    };
  }, [open, skill?.skill_id, form, t]);

  const handleClose = () => {
    setSkillTabs([{ path: "SKILL.md", content: "" }]);
    setActiveSkillTab("SKILL.md");
    setFileTreeMessage(null);
    onClose();
  };

  return (
    <Modal
      title={t("skillManagement.detail.title")}
      open={open}
      onCancel={handleClose}
      footer={null}
      width={820}
      className="skill-detail-modal"
      styles={{
        body: {
          height: 620,
          maxHeight: "75vh",
          overflow: "hidden",
        },
      }}
    >
      {fileTreeMessage ? (
        <Alert type="warning" showIcon message={fileTreeMessage} className="mb-3" />
      ) : null}
      <Spin spinning={loading} wrapperClassName="h-full">
        <div className="h-full">
          <SkillDraftPanel
            form={form}
            skillTabs={skillTabs}
            setSkillTabs={setSkillTabs}
            activeSkillTab={activeSkillTab}
            setActiveSkillTab={setActiveSkillTab}
            readOnly
          />
        </div>
      </Spin>
      <style jsx global>{`
        .skill-detail-modal .ant-spin-nested-loading,
        .skill-detail-modal .ant-spin-container {
          height: 100%;
        }
      `}</style>
    </Modal>
  );
}

function formatSource(source: string | undefined, t: (key: string) => string) {
  const raw = (source || "").trim();
  if (!raw) return "-";
  if (OFFICIAL_SOURCES.has(raw)) return t("skillPool.group.official");
  if (raw === "repository") return "\u4ed3\u5e93";
  if (raw === "custom" || raw === "\u81ea\u5b9a\u4e49") return t("skillPool.group.custom");
  return raw;
}

function flattenSkillFiles(nodes: SkillFileNode[], skillName: string) {
  const paths: string[] = [];

  const walk = (items: SkillFileNode[], parentPath = "") => {
    items.forEach((item) => {
      const isRootSkillDir = !parentPath && item.type === "directory" && item.name === skillName;
      const path = isRootSkillDir
        ? ""
        : parentPath
          ? `${parentPath}/${item.name}`
          : item.name;

      if (item.type === "file") {
        paths.push(path);
        return;
      }

      if (item.children?.length) {
        walk(item.children, path);
      }
    });
  };

  walk(nodes);
  return paths;
}

function sortSkillTabs(tabs: SkillFileContent[]) {
  return [...tabs].sort((a, b) => {
    if (a.path === "SKILL.md") return -1;
    if (b.path === "SKILL.md") return 1;
    return a.path.localeCompare(b.path);
  });
}
