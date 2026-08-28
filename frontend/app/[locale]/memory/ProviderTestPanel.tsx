"use client";

import { useState } from "react";
import {
  Alert,
  App,
  Button,
  Descriptions,
  Drawer,
  Form,
  Input,
  Typography,
} from "antd";
import { useTranslation } from "react-i18next";

import {
  testIngest,
  testSearch,
  type ProviderConfig,
} from "@/services/providerService";

const { Text } = Typography;
const TEST_SEARCH_TOP_K = 3;

type TestResult = {
  success: boolean;
  duration: number;
  count?: number;
  accepted?: number;
  rejected?: number;
  error?: string;
};

interface ProviderTestPanelProps {
  open: boolean;
  provider: ProviderConfig | null;
  onClose: () => void;
  onTested: () => void;
}

function numericValue(payload: unknown, keys: string[]): number | undefined {
  if (!payload || typeof payload !== "object") return undefined;
  const record = payload as Record<string, unknown>;
  for (const key of keys)
    if (typeof record[key] === "number") return record[key] as number;
  return undefined;
}

export function ProviderTestPanel({
  open,
  provider,
  onClose,
  onTested,
}: ProviderTestPanelProps) {
  const { modal } = App.useApp();
  const { t } = useTranslation("common");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<TestResult | null>(null);
  const [form] = Form.useForm<{ content: string; query: string }>();

  const execute = async () => {
    if (!provider) return;
    const values = await form.validateFields();
    modal.confirm({
      centered: true,
      title: t("memory.external.test.ingestConfirmTitle"),
      content: t("memory.external.test.sequenceConfirmDescription"),
      okText: t("memory.external.test.writeAndSearch"),
      cancelText: t("memory.external.actions.cancel"),
      onOk: () => runSequence(values.content, values.query),
    });
  };

  const runSequence = async (content: string, query: string) => {
    if (!provider) return;
    setLoading(true);
    setResult(null);
    const startedAt = performance.now();
    let accepted: number | undefined;
    let rejected: number | undefined;
    try {
      const ingestPayload = await testIngest(provider.provider_config_id, [
        {
          event_id: `test-${Date.now()}`,
          event_type: "test",
          unit_type: "user_message",
          unit_content: content,
          unit_index: 0,
          metadata: { source: "provider_connectivity_test" },
        },
      ]);
      accepted = numericValue(ingestPayload, ["accepted", "accepted_count"]);
      rejected = numericValue(ingestPayload, ["rejected", "rejected_count"]);

      const searchPayload = await testSearch(
        provider.provider_config_id,
        query,
        TEST_SEARCH_TOP_K
      );
      const count = Array.isArray(searchPayload)
        ? searchPayload.length
        : numericValue(searchPayload, ["count", "results_count", "hit_count"]);
      setResult({
        success: true,
        duration: performance.now() - startedAt,
        accepted,
        rejected,
        count,
      });
    } catch {
      setResult({
        success: false,
        duration: performance.now() - startedAt,
        accepted,
        rejected,
        error: t("memory.external.test.unknownError"),
      });
    } finally {
      setLoading(false);
      onTested();
    }
  };

  return (
    <Drawer
      open={open}
      title={t("memory.external.test.title", {
        name: provider?.provider_name ?? "",
      })}
      width={560}
      onClose={onClose}
      destroyOnHidden
      footer={
        <div className="external-provider-drawer-footer">
          <Button onClick={onClose}>
            {t("memory.external.actions.close")}
          </Button>
          <Button
            type="primary"
            loading={loading}
            onClick={() => void execute()}
          >
            {t("memory.external.test.writeAndSearch")}
          </Button>
        </div>
      }
    >
      <Alert
        type="warning"
        showIcon
        message={t("memory.external.test.sequenceWarning")}
      />
      <Form
        form={form}
        layout="vertical"
        style={{ marginTop: 20 }}
        initialValues={{
          content: t("memory.external.test.sampleContent"),
          query: t("memory.external.test.sampleQuery"),
        }}
      >
        <Form.Item
          name="content"
          label={t("memory.external.test.content")}
          extra={t("memory.external.test.contentHint")}
          rules={[
            {
              required: true,
              whitespace: true,
              message: t("memory.external.test.contentRequired"),
            },
          ]}
        >
          <Input.TextArea rows={4} />
        </Form.Item>
        <Form.Item
          name="query"
          label={t("memory.external.test.query")}
          extra={t("memory.external.test.queryHint")}
          rules={[
            {
              required: true,
              whitespace: true,
              message: t("memory.external.test.queryRequired"),
            },
          ]}
        >
          <Input.TextArea rows={3} />
        </Form.Item>
      </Form>
      {result && (
        <Alert
          className="external-provider-test-result"
          type={result.success ? "success" : "error"}
          showIcon
          message={
            result.success
              ? t("memory.external.test.succeeded")
              : t("memory.external.test.failed")
          }
          description={
            <Descriptions size="small" column={1}>
              <Descriptions.Item label={t("memory.external.test.duration")}>
                {Math.round(result.duration)} ms
              </Descriptions.Item>
              {result.accepted !== undefined && (
                <Descriptions.Item label={t("memory.external.test.accepted")}>
                  {result.accepted}
                </Descriptions.Item>
              )}
              {result.rejected !== undefined && (
                <Descriptions.Item label={t("memory.external.test.rejected")}>
                  {result.rejected}
                </Descriptions.Item>
              )}
              {result.count !== undefined && (
                <Descriptions.Item label={t("memory.external.test.hits")}>
                  {result.count}
                </Descriptions.Item>
              )}
              {result.error && (
                <Descriptions.Item label={t("memory.external.test.error")}>
                  <Text type="danger">{result.error}</Text>
                </Descriptions.Item>
              )}
            </Descriptions>
          }
        />
      )}
    </Drawer>
  );
}
