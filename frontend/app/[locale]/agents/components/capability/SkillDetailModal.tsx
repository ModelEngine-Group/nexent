// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useEffect, useState } from "react";
import { Alert, Form, Modal, Spin } from "antd";
import { useTranslation } from "react-i18next";

import { Skill } from "@/types/agentConfig";
import type {
  SkillFileContent,
  SkillFileNode,
  SkillFormData,
} from "@/types/skill";
import {
  fetchSkillById,
  fetchSkillFileContent,
  fetchSkillFiles,
  SkillFilesAccessDeniedError,
} from "@/services/agentConfigService";
import { normalizeSkillFiles } from "@/lib/skillFileUtils";
import log from "@/lib/logger";
import SkillDraftPanel from "./SkillDraftPanel";
import SkillReadOnlyDetail from "@/components/skill/SkillReadOnlyDetail";

interface SkillDetailModalProps {
  skill: Skill | null;
  open: boolean;
  onClose: () => void;
  zIndex?: number;
  maskClosable?: boolean;
  repositoryLayout?: boolean;
}

const OFFICIAL_SOURCES = new Set(["official", "\u5b98\u65b9"]);

async function loadSkillFileTabs(
  skillName: string
): Promise<SkillFileContent[]> {
  const files = await fetchSkillFiles(skillName);
  const paths = flattenSkillFiles(normalizeSkillFiles(files), skillName);
  return Promise.all(
    paths.map(async ({ path, previewStatus }) => {
      if (previewStatus === "unsupported") {
        return { path, content: "", status: "unsupported" as const };
      }
      try {
        const result = await fetchSkillFileContent(skillName, path);
        return {
          path,
          content: result.content,
          status: result.status,
          encoding: result.encoding,
        };
      } catch (error) {
        log.error("Failed to load skill file content:", error);
        return { path, content: "", status: "read_error" as const };
      }
    })
  );
}

export default function SkillDetailModal({
  skill,
  open,
  onClose,
  zIndex = 1000,
  maskClosable = true,
  repositoryLayout = false,
}: SkillDetailModalProps) {
  const { t } = useTranslation("common");
  const [form] = Form.useForm<SkillFormData>();
  const [skillTabs, setSkillTabs] = useState<SkillFileContent[]>([
    { path: "SKILL.md", content: "" },
  ]);
  const [activeSkillTab, setActiveSkillTab] = useState("SKILL.md");
  const [loading, setLoading] = useState(false);
  const [detailInfo, setDetailInfo] = useState<Pick<
    Skill,
    "name" | "source" | "tags" | "description"
  > | null>(null);
  const [fileTreeMessage, setFileTreeMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!open || !skill) return;

    let cancelled = false;
    setDetailInfo(skill);
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
        const detailResult = await fetchSkillById(
          skill.skill_id,
          skill.tenant_id
        );
        const detail =
          detailResult.success && detailResult.data ? detailResult.data : skill;
        const skillName = detail.name?.trim() || skill.name;
        if (!cancelled) {
          setDetailInfo(detail);
          form.setFieldsValue({
            name: skillName,
            description: detail.description || "",
            source: formatSource(detail.source, t),
            tags: Array.isArray(detail.tags) ? detail.tags : [],
            content: detail.content || "",
          });
        }

        const tabs = await loadSkillFileTabs(skillName);

        if (!cancelled && tabs.length > 0) {
          const sortedTabs = sortSkillTabs(tabs);
          setSkillTabs(sortedTabs);
          setActiveSkillTab(sortedTabs[0]?.path || "SKILL.md");
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
  }, [open, skill, form, t]);

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
      footer={repositoryLayout ? undefined : null}
      onOk={handleClose}
      okText={t("common.confirm")}
      cancelText={t("common.cancel")}
      centered={repositoryLayout}
      destroyOnHidden={repositoryLayout}
      width={repositoryLayout ? 860 : 820}
      zIndex={zIndex}
      mask={{ closable: maskClosable }}
      className="skill-detail-modal"
      styles={{
        body: {
          height: repositoryLayout ? "auto" : 620,
          maxHeight: "75vh",
          overflow: repositoryLayout ? "auto" : "hidden",
        },
      }}
    >
      {fileTreeMessage ? (
        <Alert
          type="warning"
          showIcon
          title={fileTreeMessage}
          className="mb-3"
        />
      ) : null}
      <Spin spinning={loading} wrapperClassName="h-full">
        <div className="h-full">
          {repositoryLayout ? (
            <Form form={form} component={false}>
              <SkillReadOnlyDetail
                name={detailInfo?.name || skill?.name || ""}
                source={formatSource(detailInfo?.source, t)}
                tags={detailInfo?.tags ?? []}
                description={detailInfo?.description || ""}
                files={skillTabs}
              />
            </Form>
          ) : (
            <SkillDraftPanel
              form={form}
              skillTabs={skillTabs}
              setSkillTabs={setSkillTabs}
              activeSkillTab={activeSkillTab}
              setActiveSkillTab={setActiveSkillTab}
              readOnly
              repositoryLayout={repositoryLayout}
            />
          )}
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
  if (raw === "repository") return t("workbench.controls.repository");
  if (raw === "custom" || raw === "\u81ea\u5b9a\u4e49")
    return t("skillPool.group.custom");
  return raw;
}

function flattenSkillFiles(nodes: SkillFileNode[], skillName: string) {
  const paths: Array<{
    path: string;
    previewStatus: "readable" | "unsupported";
  }> = [];

  const walk = (items: SkillFileNode[], parentPath = "") => {
    items.forEach((item) => {
      const isRootSkillDir =
        !parentPath && item.type === "directory" && item.name === skillName;
      const path = isRootSkillDir
        ? ""
        : parentPath
          ? `${parentPath}/${item.name}`
          : item.name;

      if (item.type === "file") {
        paths.push({
          path,
          previewStatus:
            item.preview_status === "unsupported" ? "unsupported" : "readable",
        });
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
