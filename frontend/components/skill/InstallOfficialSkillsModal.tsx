"use client";

import React, { useState, useEffect } from "react";
import { Modal, Spin, message } from "antd";
import { useTranslation } from "react-i18next";
import { CircleCheckBig, CircleOff, CircleDot, LoaderCircle } from "lucide-react";

import { fetchOfficialSkillsWithStatus, installOfficialSkills } from "@/services/skillService";
import { InstallableSkill } from "@/types/agentConfig";
import { Tooltip } from "@/components/ui/tooltip";

interface InstallOfficialSkillsModalProps {
  open: boolean;
  onClose: () => void;
  onInstalled: () => void;
  tenantId?: string;
}

export function InstallOfficialSkillsModal({
  open,
  onClose,
  onInstalled,
  tenantId,
}: InstallOfficialSkillsModalProps) {
  const { t } = useTranslation("common");

  const [skills, setSkills] = useState<InstallableSkill[]>([]);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(false);
  const [installing, setInstalling] = useState<Set<string>>(new Set());
  const [installedSession, setInstalledSession] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (!open) return;

    let cancelled = false;
    setLoading(true);
    setSkills([]);
    setSelectedIds(new Set());
    setInstalling(new Set());
    setInstalledSession(new Set());

    fetchOfficialSkillsWithStatus(tenantId)
      .then((data) => {
        if (cancelled) return;
        setSkills(data);
        const selectable = new Set<string>();
        data.forEach((s) => {
          if (s.status === "installable") selectable.add(s.name);
        });
        setSelectedIds(selectable);
      })
      .catch(() => {
        if (!cancelled) message.error("Failed to load official skills");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => { cancelled = true; };
  }, [open]);

  const handleConfirm = async () => {
    if (selectedIds.size === 0) {
      message.warning(t("tenantResources.skills.installModal.selectAtLeastOne"));
      return;
    }

    setInstalling(new Set(selectedIds));
    setInstalledSession(new Set());

    const names = Array.from(selectedIds);
    try {
      await installOfficialSkills(names, undefined, tenantId);
      setInstalling(new Set());
      setInstalledSession(new Set(names));
      message.success(
        t("tenantResources.skills.installModal.success", { count: names.length })
      );
      onInstalled();
      setTimeout(onClose, 800);
    } catch {
      message.error("Failed to install skills");
      setInstalling(new Set());
    }
  };

  const allSelected = skills.length > 0 && skills.every((s) => selectedIds.has(s.name));
  const someSelected = skills.some((s) => selectedIds.has(s.name)) && !allSelected;

  return (
    <Modal
      title={t("tenantResources.skills.installModal.title")}
      open={open}
      onCancel={onClose}
      onOk={handleConfirm}
      okText={t("common.confirm")}
      cancelText={t("common.cancel")}
      confirmLoading={Array.from(installing).length > 0}
      width={560}
      centered
      destroyOnClose
    >
      {loading ? (
        <div className="flex items-center justify-center py-8">
          <Spin size="small" />
          <span className="ml-2 text-gray-500 text-sm">
            {t("tenantResources.tenants.skillsLoading")}
          </span>
        </div>
      ) : skills.length === 0 ? (
        <p className="text-gray-500 text-sm py-4 text-center">
          {t("tenantResources.tenants.noSkillsAvailable")}
        </p>
      ) : (
        <div
          className="border border-gray-200 rounded-md max-h-80 overflow-y-auto"
          style={{ maxHeight: 320 }}
        >
          <div className="flex items-center px-3 py-2 border-b border-gray-200 bg-gray-50 sticky top-0">
            <input
              type="checkbox"
              checked={allSelected}
              ref={(el) => {
                if (el) el.indeterminate = someSelected;
              }}
              onChange={() => {
                if (allSelected) {
                  setSelectedIds(new Set());
                } else {
                  const selectable = new Set<string>();
                  skills.forEach((s) => {
                    if (s.status === "installable") selectable.add(s.name);
                  });
                  setSelectedIds(selectable);
                }
              }}
              className="mr-3 w-4 h-4 accent-blue-500 cursor-pointer shrink-0"
            />
            <span className="flex-1 text-sm font-medium text-gray-700">
              {t("common.selectAll") || "Select all"}
            </span>
          </div>

          {skills.map((skill) => {
            const isInstalling = installing.has(skill.name);
            const isInstalledSession = installedSession.has(skill.name);
            const isAlreadyInstalled = skill.status === "installed" || isInstalledSession;
            const isResourceMissing = skill.status === "resource_missing";
            const isDisabled = isInstalling || isAlreadyInstalled || isResourceMissing;

            let iconElement: React.ReactNode;
            let tooltipText: string;

            if (isInstalling) {
              iconElement = <LoaderCircle className="h-4 w-4 text-gray-400 shrink-0 animate-spin" />;
              tooltipText = t("tenantResources.tenants.skillStatus.installing");
            } else if (isAlreadyInstalled) {
              iconElement = <CircleCheckBig className="h-4 w-4 text-green-500 shrink-0" />;
              tooltipText = t("tenantResources.tenants.skillStatus.installed");
            } else if (isResourceMissing) {
              iconElement = <CircleOff className="h-4 w-4 text-red-400 shrink-0" />;
              tooltipText = t("tenantResources.tenants.skillStatus.resourceMissing");
            } else {
              iconElement = <CircleDot className="h-4 w-4 text-green-500 shrink-0" />;
              tooltipText = t("tenantResources.tenants.skillStatus.installable");
            }

            return (
              <div
                key={skill.skill_id}
                className={`flex items-center px-3 py-2 border-b border-gray-100 last:border-b-0 hover:bg-gray-50 transition-colors ${
                  isDisabled ? "opacity-50" : ""
                }`}
              >
                <input
                  type="checkbox"
                  checked={selectedIds.has(skill.name)}
                  onChange={() => {
                    if (isDisabled) return;
                    const next = new Set(selectedIds);
                    if (next.has(skill.name)) {
                      next.delete(skill.name);
                    } else {
                      next.add(skill.name);
                    }
                    setSelectedIds(next);
                  }}
                  disabled={isDisabled}
                  className="mr-3 w-4 h-4 accent-blue-500 cursor-pointer shrink-0"
                />
                <span className="flex-1 text-sm text-gray-800 truncate">{skill.name}</span>
                <span className="ml-2 shrink-0">
                  <Tooltip title={tooltipText}>{iconElement}</Tooltip>
                </span>
              </div>
            );
          })}
        </div>
      )}
    </Modal>
  );
}
