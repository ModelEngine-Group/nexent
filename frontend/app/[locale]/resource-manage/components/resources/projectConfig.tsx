"use client";

import React, { useState, useEffect } from "react";
import { Form, Input, Button, message, Card, UploadFile, Upload, Radio, Row, Col } from "antd";
import { useTranslation } from "react-i18next";
import { useGlobalConfigStore, useGlobalConfigStoreAllLanguage } from "@/stores/global";
import { API_ENDPOINTS, ApiError } from "@/services/api";

export default function ProjectConfigTab() {
  const { t } = useTranslation("common");
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const { config } = useGlobalConfigStore();
  const { configAll } = useGlobalConfigStoreAllLanguage();
  const [file, setFile] = useState<File | null>();
  const [previewUrl, setPreviewUrl] = useState<string>('');
  const [file2, setFile2] = useState<File | null>();
  const [previewUrl2, setPreviewUrl2] = useState<string>('');

  const customModifyLanguageConfig = [
    {
      key: 'productName',
      label: t('project.config.title'),
      max: 10,
    },
    {
      key: 'pageSubtitle',
      label: t('project.config.page.subtitle'),
      max: 50,
    },
    {
      key: 'pageDescription',
      label: t('project.config.page.description'),
      max: 100,
    }
  ];

  const getInitialData = (lang: 'en' | 'zh') => {
    return customModifyLanguageConfig.reduce((acc, k) => {
      acc[k.key] = configAll[lang].custom[k.key]
      return acc;
    }, {} as any)
  }

  const initialForm = {
    aboutConfig: 'open',
    icon: '',
    ...config,
    configZh: {
      ...getInitialData('zh'),
    },
    configEn: {
      ...getInitialData('en'),
    },
  }

  const loadConfig = async () => {
    form.setFieldsValue(initialForm);
  }

  useEffect(() => {
    loadConfig();
  }, [])
  
  const beforeUpload = (fileUpdate: UploadFile, logo2 = false) => {
    const isPng = fileUpdate.type === "image/png"
    if (!isPng) {
      message.error(t('project.config.logo.format'));
      return false;
    }
    const isLt200K = fileUpdate.size && fileUpdate.size / 1024 <= 200;
    if (!isLt200K) {
      message.error(t('project.config.logo.size'));
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
  }

  const handleSave = async (values: any) => {
    setLoading(true);
    try {
      await saveConfig(values, file as File, file2 as File);
      message.success(t('project.config.update.success'));
    } catch (error) {
      console.log(`Failed to update:`, error);
      message.success(t('errorCode.990202'));
    } finally {
      setLoading(false);
    }
  }

  const saveConfig = async (configData: any, iconFile?: File, iconFile2?: File): Promise<void> => {
    try {
      const formData = new FormData();
      formData.append("configZh", JSON.stringify({
        aboutConfig: configData.aboutConfig,
        ...configData.configZh,
      }));
      formData.append("configEn", JSON.stringify({
        aboutConfig: configData.aboutConfig,
        ...configData.configEn,
      }));

      if (iconFile) {
        formData.append("logo", iconFile);
      }
      if (iconFile2) {
        formData.append("logo2", iconFile2);
      }
      const response = await fetch(API_ENDPOINTS.config.projectConfig, {
        method: "POST",
        body: formData,
      })
      if (!response.ok) {
        const result = await response.json();
        throw new ApiError(response.status, result.message || 'Fail to save project config')
      }
    } catch (error) {
      if (error instanceof ApiError) {
        throw error;
      }
      throw new ApiError(500, 'Fail to save project config')
    }
  }
 
  return (
    <div className="flex flex-col h-full overflow-hidden">
      <Card
        title={t("project.config")}
      >
        <Form
          form={form}
          layout="vertical"
          onFinish={handleSave}
          initialValues={initialForm}
        >
          {
            customModifyLanguageConfig.map((item) => (
              <Row gutter={16} align={"middle"}>
                <Col span={12}>
                    <Form.Item
                      name={["configZh", item.key]}
                      label={ item.label }
                      rules={[
                        { max: item.max, message: t("chatLeftSidebar.renameErrorTooLong", { max: item.max }) }
                      ]}
                    >
                      <Input placeholder={t("project.config.language.zh")}></Input>
                    </Form.Item>
                </Col>
                <Col span={12}>
                    <Form.Item
                      name={["configEn", item.key]}
                      label={ ' ' }
                      rules={[
                        { max: item.max, message: t("chatLeftSidebar.renameErrorTooLong", { max: item.max }) }
                      ]}
                    >
                      <Input placeholder={t("project.config.language.en")}></Input>
                    </Form.Item>
                </Col>
              </Row>
            ))
          }

          <Form.Item
            name="aboutConfig"
            label={t("project.config.about.us")}
          >
            <Radio.Group options={[
              {
                value: "open", label: t('project.config.about.us.open')
              },
              {
                value: "close", label: t('project.config.about.us.close')
              }
            ]}/>
          </Form.Item>
          <Form.Item
            name="icon"
          >
            <div className="flex items-center gap-4 mt-2 mb-4">
              <span>{ t('project.config.logo.change') }</span>
              <img className="h-7" src="/modelengine-logo2.png" alt={"old logo1"}></img>
              { previewUrl && <img className="h-7" src={previewUrl} alt={"new logo1"}></img>}
            </div>
            <Upload
                beforeUpload={(fileRaw) => beforeUpload(fileRaw, false)}
                showUploadList={false}
                accept="image/png"
              >
                <Button size="small">{ t('project.config.logo.upload.new') }</Button>
              </Upload>
          </Form.Item>
          <Form.Item
            name="icon2"
          >
            <div className="flex items-center gap-4 mt-2 mb-4">
              <span>{ t('project.config.logo.change') }</span>
              <img className="h-7" src="/modelengine-logo.png" alt={"old logo2"}></img>
              { previewUrl2 && <img className="h-7" src={previewUrl2} alt={"new logo2"}></img>}
            </div>
            <Upload
                beforeUpload={(fileRaw) => beforeUpload(fileRaw, true)}
                showUploadList={false}
                accept="image/png"
              >
                <Button size="small">{ t('project.config.logo.upload.new') }</Button>
              </Upload>
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit" loading={loading}>
              {t('common.save')}
            </Button>
          </Form.Item>
        </Form>
      </Card>
    </div>
  );
}
