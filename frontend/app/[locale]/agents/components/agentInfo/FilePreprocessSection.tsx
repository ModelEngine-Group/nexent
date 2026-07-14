"use client";

import type { CSSProperties } from "react";
import { useTranslation } from "react-i18next";
import {
  Row,
  Col,
  Flex,
  Card,
  Tooltip,
  Popover,
  Slider,
  InputNumber,
  Radio,
  Switch,
} from "antd";
import { QuestionCircleOutlined } from "@ant-design/icons";
import { Settings } from "lucide-react";

import { useAgentConfigStore } from "@/stores/agentConfigStore";
import { DEFAULT_AGENT_FILE_PREPROCESS_CONFIG } from "@/types/agentConfig";

// Shared overlay style for the per-mode settings popover.
const SETTING_POPOVER_OVERLAY_STYLE: CSSProperties = {
  width: 400,
  padding: "12px 16px",
  boxSizing: "content-box",
};

// Slider + manual number input combo for file preprocess settings.
function FilePreprocessSettingRow({
  label,
  tooltip,
  value,
  min,
  max,
  step,
  onChange,
}: {
  label: string;
  tooltip?: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (v: number) => void;
}) {
  return (
    <div className="fp-setting-row">
      <div className="fp-setting-label">
        {tooltip ? (
          <Tooltip title={tooltip}>
            <span>{label}</span>
          </Tooltip>
        ) : (
          label
        )}
      </div>
      <Flex gap={8} align="center">
        <Slider
          className="file-preprocess-slider fp-setting-slider"
          min={min}
          max={max}
          step={step}
          value={value}
          onChange={onChange}
          marks={{ [min]: String(min), [max]: String(max) }}
        />
        <InputNumber
          min={min}
          max={max}
          step={step}
          value={value}
          controls={false}
          onChange={(v) => {
            if (typeof v === "number") onChange(v);
          }}
          className="fp-setting-input"
        />
      </Flex>
    </div>
  );
}

// Enable toggle + two mode cards (full_text_reference / chunk_search) for the
// conversation-level file preprocess config. Reads/writes the agent config
// store directly, so it stays in sync with the rest of the agent form.
export default function FilePreprocessSection() {
  const { t } = useTranslation("common");
  const editedAgent = useAgentConfigStore((state) => state.editedAgent);
  const updateAgentConfig = useAgentConfigStore(
    (state) => state.updateAgentConfig
  );

  // File preprocess config is read from the store (not form fields) so the
  // card-based UI reflects the persisted config directly.
  const filePreprocessConfig =
    editedAgent.file_preprocess?.config ??
    DEFAULT_AGENT_FILE_PREPROCESS_CONFIG.config;
  const filePreprocessEnabled = (
    editedAgent.file_preprocess ?? DEFAULT_AGENT_FILE_PREPROCESS_CONFIG
  ).enable;
  const selectedFileMode = filePreprocessConfig.file_mode;
  const setFilePreprocessConfig = (
    partial: Partial<typeof filePreprocessConfig>
  ) => {
    const fp =
      editedAgent.file_preprocess || DEFAULT_AGENT_FILE_PREPROCESS_CONFIG;
    updateAgentConfig({
      file_preprocess: { ...fp, config: { ...fp.config, ...partial } },
    });
  };
  const setFilePreprocessMode = (
    mode: "full_text_reference" | "chunk_search"
  ) => {
    const fp =
      editedAgent.file_preprocess || DEFAULT_AGENT_FILE_PREPROCESS_CONFIG;
    updateAgentConfig({
      file_preprocess: { ...fp, config: { ...fp.config, file_mode: mode } },
    });
  };

  return (
    <>
      <Row gutter={16}>
        <Col span={24}>
          <Flex align="center" gap={8} className="fp-enable-row">
            <span className="fp-mode-title">
              {t("agent.enableFilePreprocess")}
            </span>
            <Tooltip title={t("agent.enableFilePreprocess.tooltip")}>
              <QuestionCircleOutlined className="fp-info-icon" />
            </Tooltip>
            <Switch
              size="small"
              checked={filePreprocessEnabled}
              onChange={(checked) => {
                const cur =
                  editedAgent.file_preprocess ||
                  DEFAULT_AGENT_FILE_PREPROCESS_CONFIG;
                updateAgentConfig({
                  file_preprocess: { ...cur, enable: checked },
                });
              }}
            />
          </Flex>
        </Col>
      </Row>

      {filePreprocessEnabled && (
        <Flex gap={16} align="stretch" className="mb-3">
          {/* full_text_reference card */}
          <Card
            size="small"
            onClick={() => setFilePreprocessMode("full_text_reference")}
            className="fp-mode-card"
            style={{
              borderColor:
                selectedFileMode === "full_text_reference"
                  ? "#1677ff"
                  : undefined,
            }}
          >
            <Flex justify="space-between" align="center" gap={12}>
              <Flex align="center" gap={4} className="fp-card-left">
                <span className="fp-mode-title">
                  {t("agent.filePreprocess.fileModeFullTextReference")}
                </span>
                <Tooltip
                  title={t(
                    "agent.filePreprocess.fileModeFullTextReference.desc"
                  )}
                >
                  <QuestionCircleOutlined className="fp-info-icon" />
                </Tooltip>
              </Flex>
              <Flex align="center" gap={8}>
                <span
                  className="fp-settings-trigger"
                  style={{
                    visibility:
                      selectedFileMode === "full_text_reference"
                        ? "visible"
                        : "hidden",
                  }}
                  onClick={(e) => e.stopPropagation()}
                >
                  <Popover
                    trigger="click"
                    placement="bottomRight"
                    overlayInnerStyle={SETTING_POPOVER_OVERLAY_STYLE}
                    content={
                      <>
                        <FilePreprocessSettingRow
                          label={t("agent.filePreprocess.maxParseLength")}
                          tooltip={t(
                            "agent.filePreprocess.maxParseLength.tooltip"
                          )}
                          value={filePreprocessConfig.max_parse_length}
                          min={1}
                          max={200000}
                          step={1000}
                          onChange={(v) =>
                            setFilePreprocessConfig({ max_parse_length: v })
                          }
                        />
                        <FilePreprocessSettingRow
                          label={t("agent.filePreprocess.promptMaxTokenLength")}
                          tooltip={t(
                            "agent.filePreprocess.promptMaxTokenLength.tooltip"
                          )}
                          value={filePreprocessConfig.prompt_max_token_length}
                          min={1}
                          max={200000}
                          step={1000}
                          onChange={(v) =>
                            setFilePreprocessConfig({
                              prompt_max_token_length: v,
                            })
                          }
                        />
                      </>
                    }
                  >
                    <span className="inline-flex items-center cursor-pointer text-gray-400 hover:text-gray-600">
                      <Settings size={16} />
                    </span>
                  </Popover>
                </span>
                <Radio
                  checked={selectedFileMode === "full_text_reference"}
                  onChange={() => {}}
                  className="fp-radio"
                />
              </Flex>
            </Flex>
            <div className="fp-mode-desc">
              {t("agent.filePreprocess.fileModeFullTextReference.desc")}
            </div>
          </Card>

          {/* chunk_search card */}
          <Card
            size="small"
            onClick={() => setFilePreprocessMode("chunk_search")}
            className="fp-mode-card"
            style={{
              borderColor:
                selectedFileMode === "chunk_search" ? "#1677ff" : undefined,
            }}
          >
            <Flex justify="space-between" align="center" gap={12}>
              <Flex align="center" gap={4} className="fp-card-left">
                <span className="fp-mode-title">
                  {t("agent.filePreprocess.fileModeChunkSearch")}
                </span>
                <Tooltip
                  title={t("agent.filePreprocess.fileModeChunkSearch.desc")}
                >
                  <QuestionCircleOutlined className="fp-info-icon" />
                </Tooltip>
              </Flex>
              <Flex align="center" gap={8}>
                <span
                  className="fp-settings-trigger"
                  style={{
                    visibility:
                      selectedFileMode === "chunk_search"
                        ? "visible"
                        : "hidden",
                  }}
                  onClick={(e) => e.stopPropagation()}
                >
                  <Popover
                    trigger="click"
                    placement="bottomRight"
                    overlayInnerStyle={SETTING_POPOVER_OVERLAY_STYLE}
                    content={
                      <>
                        <FilePreprocessSettingRow
                          label={t("agent.filePreprocess.rerankTopN")}
                          tooltip={t("agent.filePreprocess.rerankTopN.tooltip")}
                          value={filePreprocessConfig.rerank_top_n}
                          min={1}
                          max={50}
                          step={1}
                          onChange={(v) =>
                            setFilePreprocessConfig({ rerank_top_n: v })
                          }
                        />
                        <FilePreprocessSettingRow
                          label={t("agent.filePreprocess.promptMaxTokenLength")}
                          tooltip={t(
                            "agent.filePreprocess.promptMaxTokenLength.tooltip"
                          )}
                          value={filePreprocessConfig.prompt_max_token_length}
                          min={1}
                          max={200000}
                          step={1000}
                          onChange={(v) =>
                            setFilePreprocessConfig({
                              prompt_max_token_length: v,
                            })
                          }
                        />
                      </>
                    }
                  >
                    <span className="inline-flex items-center cursor-pointer text-gray-400 hover:text-gray-600">
                      <Settings size={16} />
                    </span>
                  </Popover>
                </span>
                <Radio
                  checked={selectedFileMode === "chunk_search"}
                  onChange={() => {}}
                  className="fp-radio"
                />
              </Flex>
            </Flex>
            <div className="fp-mode-desc">
              {t("agent.filePreprocess.fileModeChunkSearch.desc")}
            </div>
          </Card>
        </Flex>
      )}
    </>
  );
}
