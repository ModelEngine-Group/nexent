// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import React, { useState, useEffect } from "react";
import {
  Form,
  message,
  Card,
  UploadFile,
  Upload,
  Radio,
  Row,
  Col,
  Tabs,
} from "antd";
import { useTranslation } from "react-i18next";
import {
  useGlobalConfigStore,
  useGlobalConfigStoreAllLanguage,
} from "@/stores/global";
import { API_ENDPOINTS, ApiError } from "@/services/api";
import { publicAsset } from "@/lib/publicAsset";
import { getHomeLogo } from "@/lib/projectBranding";
import logger from "@/lib/logger";
import { StandardInput as Input } from "@/components/common/StandardInput";
import { StandardButton as Button } from "@/components/common/StandardButton";
import { PlatformQuotaPanel } from "./PlatformQuotaPanel";

interface ProjectConfigTabProps {
  showPlatformQuota?: boolean;
}

interface ProjectConfigValues {
  aboutConfig: string;
  configZh: Record<string, string>;
  configEn: Record<string, string>;
}

export default function ProjectConfigTab({
  showPlatformQuota = false,
}: ProjectConfigTabProps) {
  const { t } = useTranslation("common");
  const [form] = Form.useForm<ProjectConfigValues>();
  const [loading, setLoading] = useState(false);
  const { config } = useGlobalConfigStore();
  const { configAll } = useGlobalConfigStoreAllLanguage();
  const [file, setFile] = useState<File | null>();
  const [previewUrl, setPreviewUrl] = useState<string>("");
  const [file2, setFile2] = useState<File | null>();
  const [previewUrl2, setPreviewUrl2] = useState<string>("");
  const [homeLogoFile, setHomeLogoFile] = useState<File | null>(null);
  const [homeLogoPreview, setHomeLogoPreview] = useState("");
  const [removeHomeLogo, setRemoveHomeLogo] = useState(false);
  const configuredHomeLogo = config.homeLogo ?? config.tabLogo;

  useEffect(
    () => () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
    },
    [previewUrl]
  );

  useEffect(
    () => () => {
      if (previewUrl2) URL.revokeObjectURL(previewUrl2);
    },
    [previewUrl2]
  );
  useEffect(
    () => () => {
      if (homeLogoPreview) URL.revokeObjectURL(homeLogoPreview);
    },
    [homeLogoPreview]
  );

  const customModifyLanguageConfig = [
    {
      key: "productName",
      label: t("project.config.title"),
      hint: t("project.config.title.hint"),
      max: 20,
      maxEn: 50,
      optional: true,
    },
    {
      key: "homeTitle",
      label: t("project.config.home.title"),
      max: 50,
      maxEn: 100,
      optional: true,
    },
    {
      key: "pageSubtitle",
      label: t("project.config.page.subtitle"),
      max: 50,
      maxEn: 100,
    },
    {
      key: "pageDescription",
      label: t("project.config.page.description"),
      max: 150,
      maxEn: 200,
    },
  ];

  const getInitialData = (lang: "en" | "zh") => {
    return customModifyLanguageConfig.reduce<Record<string, string>>(
      (acc, k) => {
        acc[k.key] =
          configAll[lang]?.custom?.[k.key] ??
          (k.key === "homeTitle"
            ? configAll[lang]?.custom?.tabTitle
            : undefined) ??
          "";
        return acc;
      },
      {}
    );
  };

  const initialForm = {
    aboutConfig: "open",
    icon: "",
    ...config,
    configZh: {
      ...getInitialData("zh"),
    },
    configEn: {
      ...getInitialData("en"),
    },
  };

  const beforeUpload = (
    fileUpdate: UploadFile,
    logo2 = false,
    homeLogo = false
  ) => {
    const isPng =
      fileUpdate.type === "image/png" || fileUpdate.type === "image/jpeg";
    if (!isPng) {
      message.error(t("project.config.logo.format"));
      return false;
    }
    const isLt200K = fileUpdate.size && fileUpdate.size / 1024 <= 200;
    if (!isLt200K) {
      message.error(t("project.config.logo.size"));
      return false;
    }

    if (homeLogo) {
      setHomeLogoFile(fileUpdate as unknown as File);
      setHomeLogoPreview(URL.createObjectURL(fileUpdate as unknown as File));
      setRemoveHomeLogo(false);
      return false;
    }
    if (logo2) {
      setFile2(fileUpdate as unknown as File);
      setPreviewUrl2(URL.createObjectURL(fileUpdate as unknown as File));
      return false;
    }
    setFile(fileUpdate as unknown as File);
    setPreviewUrl(URL.createObjectURL(fileUpdate as unknown as File));
    return false;
  };

  const handleSave = async (values: ProjectConfigValues) => {
    setLoading(true);
    try {
      await saveConfig(values, file as File, file2 as File);
      message.success(t("project.config.update.success"));
      setLoading(false);
      location.reload();
    } catch (error) {
      logger.error("Failed to update project configuration", error);
      message.error(t("errorCode.990202"));
      setLoading(false);
    }
  };

  const saveConfig = async (
    configData: ProjectConfigValues,
    iconFile?: File,
    iconFile2?: File
  ): Promise<void> => {
    try {
      const formData = new FormData();
      formData.append(
        "configZh",
        JSON.stringify({
          aboutConfig: configData.aboutConfig,
          ...configData.configZh,
        })
      );
      formData.append(
        "configEn",
        JSON.stringify({
          aboutConfig: configData.aboutConfig,
          ...configData.configEn,
        })
      );

      if (iconFile) {
        formData.append("logo", iconFile);
      }
      if (iconFile2) {
        formData.append("logo2", iconFile2);
      }
      if (homeLogoFile) formData.append("homeLogo", homeLogoFile);
      formData.append("removeHomeLogo", String(removeHomeLogo));
      const response = await fetch(API_ENDPOINTS.config.projectConfig, {
        method: "POST",
        body: formData,
      });
      if (!response.ok) {
        const result = await response.json();
        throw new ApiError(
          response.status,
          result.message || "Fail to save project config"
        );
      }
    } catch (error) {
      if (error instanceof ApiError) {
        throw error;
      }
      throw new ApiError(500, "Fail to save project config");
    }
  };

  const projectConfigContent = (
    <Card>
      <Form
        form={form}
        layout="vertical"
        onFinish={handleSave}
        initialValues={initialForm}
      >
        {customModifyLanguageConfig.map((item) => (
          <Row gutter={16} align={"middle"} key={item.key}>
            <Col span={12}>
              <Form.Item
                name={["configZh", item.key]}
                label={item.label}
                extra={item.hint}
                rules={[
                  {
                    required: !item.optional,
                    message: t("project.config.contentRequired"),
                  },
                  {
                    max: item.max,
                    message: t("chatLeftSidebar.renameErrorTooLong", {
                      max: item.max,
                    }),
                  },
                ]}
              >
                <Input
                  allowClear
                  placeholder={
                    item.key === "homeTitle"
                      ? t("project.config.home.title.placeholder")
                      : t("project.config.language.zh")
                  }
                ></Input>
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                name={["configEn", item.key]}
                label={`${item.label}-English`}
                extra={item.hint}
                rules={[
                  {
                    required: !item.optional,
                    message: t("project.config.contentRequired"),
                  },
                  {
                    max: item.maxEn,
                    message: t("chatLeftSidebar.renameErrorTooLong", {
                      max: item.maxEn,
                    }),
                  },
                ]}
              >
                <Input
                  allowClear
                  placeholder={
                    item.key === "homeTitle"
                      ? t("project.config.home.title.placeholder")
                      : t("project.config.language.en")
                  }
                ></Input>
              </Form.Item>
            </Col>
          </Row>
        ))}

        <Form.Item name="aboutConfig" label={t("project.config.about.us")}>
          <Radio.Group
            options={[
              {
                value: "open",
                label: t("project.config.about.us.open"),
              },
              {
                value: "close",
                label: t("project.config.about.us.close"),
              },
            ]}
          />
        </Form.Item>
        <Form.Item extra={t("project.config.system.logo.hint")}>
          <div className="flex items-center gap-4 mt-2 mb-4">
            <span>{t("project.config.page.simple.log")}</span>
            <img
              className="h-7"
              src={
                previewUrl2 ? previewUrl2 : publicAsset("/modelengine-logo.png")
              }
              alt={t("project.config.page.simple.log")}
            ></img>
          </div>
          <Upload
            beforeUpload={(fileRaw) => beforeUpload(fileRaw, true)}
            showUploadList={false}
            accept="image/png,image/jpeg"
          >
            <Button size="small">{t("project.config.logo.upload.new")}</Button>
          </Upload>
        </Form.Item>
        <Form.Item label={t("project.config.home.logo")}>
          <div className="mb-4 mt-2 flex items-center gap-4">
            <img
              className="h-7 max-w-40 object-contain"
              src={
                homeLogoPreview ||
                (removeHomeLogo || !configuredHomeLogo
                  ? previewUrl2 || publicAsset("/modelengine-logo.png")
                  : getHomeLogo(config))
              }
              alt={t("project.config.home.logo")}
            />
            <span className="text-sm text-muted-foreground">
              {t("project.config.home.logo.hint")}
            </span>
          </div>
          <div className="flex items-center gap-3">
            <Upload
              beforeUpload={(fileRaw) => beforeUpload(fileRaw, false, true)}
              showUploadList={false}
              accept="image/png,image/jpeg"
            >
              <Button size="small">
                {t("project.config.home.logo.upload")}
              </Button>
            </Upload>
            <Button
              size="small"
              disabled={
                removeHomeLogo || (!homeLogoFile && !configuredHomeLogo)
              }
              onClick={() => {
                setHomeLogoFile(null);
                setHomeLogoPreview("");
                setRemoveHomeLogo(true);
              }}
            >
              {t("project.config.home.logo.reset")}
            </Button>
          </div>
        </Form.Item>
        <Form.Item>
          <Button variant="primary" htmlType="submit" loading={loading}>
            {t("common.save")}
          </Button>
        </Form.Item>
      </Form>
    </Card>
  );

  if (showPlatformQuota) {
    return (
      <Tabs
        defaultActiveKey="project"
        items={[
          {
            key: "project",
            label: t("project.config"),
            children: projectConfigContent,
          },
          {
            key: "platform-quota",
            label: t("quota.platformOverview", "Platform Quota"),
            children: <PlatformQuotaPanel showTenantAllocations={false} />,
          },
        ]}
      />
    );
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {projectConfigContent}
    </div>
  );
}
