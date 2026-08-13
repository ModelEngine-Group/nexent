"use client";

import React, { useState, useCallback } from "react";
import {
  Row,
  Col,
  Card,
  Typography,
  Button,
  Input,
  Checkbox,
  Form,
  Space,
  Tag,
  Rate,
  message,
  ConfigProvider,
} from "antd";
import {
  CheckCircleFilled,
  WarningFilled,
  FormOutlined,
  CheckSquareOutlined,
  StarFilled,
  ExclamationCircleFilled,
  InfoCircleFilled,
  PushpinOutlined,
} from "@ant-design/icons";
import A2UIChart from "./A2UIChart";
import type { A2UIComponent, A2UISurface, HITLInteraction } from "@/types/chat";

const { TextArea } = Input;
const { Title, Text } = Typography;

interface A2UIRendererProps {
  surfaces: A2UISurface[];
  pendingInteractions?: HITLInteraction[];
  onAction?: (action: string, data?: Record<string, any>) => Promise<void> | void;
  messageId?: string;
}

interface A2UIComponentRendererProps {
  component: A2UIComponent;
  dataModel?: Record<string, any>;
  onAction?: (action: string, data?: Record<string, any>) => Promise<void> | void;
  onDataChange?: (binding: string, value: any) => void;
  formData?: Record<string, any>;
  onFormSubmit?: (interactionId: string, formData: Record<string, any>) => void;
  surfaceId?: string;
  surfaceCatalog?: string;
}

const iconMap: Record<string, React.ReactNode> = {
  pushpin: <PushpinOutlined />,
  form: <FormOutlined />,
  checkbox: <CheckSquareOutlined />,
  textfield: <FormOutlined />,
};

// Map card types to Chinese labels
const cardTypeLabels: Record<string, string> = {
  info: "Info · 信息卡片",
  feedback: "Feedback · 反馈卡片",
  confirmation: "Confirmation · 确认卡片",
  form: "Form · 表单卡片",
  rating: "Rating · 评分卡片",
  chart: "Chart · 统计图表",
};

/**
 * Safely extract a display string from a value that may be a plain string
 * or a structured object like `{ display: "inline", text: "..." }`.
 * Returns a plain string suitable for React rendering.
 */
function safeRenderText(value: any): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (typeof value === "object") {
    if (typeof value.text === "string") return value.text;
    if (typeof value.content === "string") return value.content;
    if (typeof value.label === "string") return value.label;
    try {
      return JSON.stringify(value);
    } catch {
      return "";
    }
  }
  return String(value);
}

const A2UIComponentRenderer: React.FC<A2UIComponentRendererProps> = ({
  component,
  dataModel,
  onAction,
  onDataChange,
  formData,
  onFormSubmit,
  surfaceId,
  surfaceCatalog,
}) => {
  const [localFormData, setLocalFormData] = useState<Record<string, any>>({});
  const [submitting, setSubmitting] = useState(false);

  const handleDataChange = useCallback(
    (binding: string, value: any) => {
      setLocalFormData((prev) => ({ ...prev, [binding]: value }));
      onDataChange?.(binding, value);
    },
    [onDataChange]
  );

  const handleAction = useCallback(
    async (action: string, data?: Record<string, any>) => {
      if (!onAction) return;
      try {
        await onAction(action, data);
      } catch (err) {
        console.error("A2UI action error:", err);
      }
    },
    [onAction]
  );

  const handleFormSubmit = useCallback(
    async (interactionId: string) => {
      if (!onFormSubmit) return;
      setSubmitting(true);
      try {
        await onFormSubmit(interactionId, localFormData);
      } catch (err) {
        console.error("Form submission error:", err);
      } finally {
        setSubmitting(false);
      }
    },
    [onFormSubmit, localFormData]
  );

  const renderChildren = (comp: A2UIComponent): React.ReactNode => {
    if (comp.child) {
      return (
        <A2UIComponentRenderer
          component={comp.child}
          dataModel={dataModel}
          onAction={onAction}
          onDataChange={handleDataChange}
          formData={localFormData}
          onFormSubmit={handleFormSubmit}
          surfaceId={surfaceId}
          surfaceCatalog={surfaceCatalog}
        />
      );
    }
    if (comp.children && comp.children.length > 0) {
      return comp.children.map((child) => (
        <A2UIComponentRenderer
          key={child.id}
          component={child}
          dataModel={dataModel}
          onAction={onAction}
          onDataChange={handleDataChange}
          formData={localFormData}
          onFormSubmit={handleFormSubmit}
          surfaceId={surfaceId}
          surfaceCatalog={surfaceCatalog}
        />
      ));
    }
    return null;
  };

  // Get card type from surface or component
  const getCardType = (): string | null => {
    if (surfaceId) {
      const match = surfaceId.match(/card_([^_]+)/);
      if (match) return match[1];
    }
    return null;
  };

  const cardType = getCardType();

  switch (component.component) {
    case "Row": {
      const distribution = component.distribution || "start";
      return (
        <Row
          gutter={component.spacing ?? 8}
          wrap={component.wrap ?? true}
          justify={distribution as any}
          style={{ marginBottom: 8 }}
        >
          {renderChildren(component)}
        </Row>
      );
    }

    case "Column":
    case "Col": {
      return (
        <Col style={{ marginBottom: 8 }}>
          {renderChildren(component)}
        </Col>
      );
    }

    case "Card": {
      const cardTitle = safeRenderText(component.text) || safeRenderText(component.label);
      const titleIsHtml = /<[a-z][\s\S]*>/i.test(cardTitle);
      const titleEl = titleIsHtml ? (
        <span dangerouslySetInnerHTML={{ __html: cardTitle }} />
      ) : (
        cardTitle || undefined
      );

      // Determine card type and icon
      const typeLabel = cardType ? cardTypeLabels[cardType] : null;
      const iconStyle: React.CSSProperties = {
        width: 40,
        height: 40,
        borderRadius: "50%",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        fontSize: 20,
        marginBottom: 12,
      };

      let decorationIcon: React.ReactNode = null;
      let decorationStyle: React.CSSProperties = {};

      if (cardType === "info") {
        decorationIcon = <CheckCircleFilled style={{ color: "#52c41a" }} />;
        decorationStyle = {
          ...iconStyle,
          background: "#f6ffed",
        };
      } else if (cardType === "confirmation") {
        decorationIcon = <WarningFilled style={{ color: "#faad14" }} />;
        decorationStyle = {
          ...iconStyle,
          background: "#fffbe6",
        };
      } else if (cardType === "feedback") {
        decorationIcon = <InfoCircleFilled style={{ color: "#1677ff" }} />;
        decorationStyle = {
          ...iconStyle,
          background: "#e6f4ff",
        };
      } else if (cardType === "rating") {
        decorationIcon = <StarFilled style={{ color: "#faad14" }} />;
        decorationStyle = {
          ...iconStyle,
          background: "#fffbe6",
        };
      } else if (cardType === "form") {
        decorationIcon = <FormOutlined style={{ color: "#1677ff" }} />;
        decorationStyle = {
          ...iconStyle,
          background: "#e6f4ff",
        };
      }

      return (
        <div
          style={{
            background: "white",
            borderRadius: 12,
            boxShadow: "0 2px 12px rgba(0,0,0,0.08)",
            padding: 20,
            marginBottom: 16,
            maxWidth: 440,
            fontFamily:
              '-apple-system, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif',
          }}
        >
          {typeLabel && (
            <div
              style={{
                display: "inline-block",
                background: "#e6f4ff",
                color: "#1677ff",
                padding: "2px 8px",
                borderRadius: 4,
                fontSize: 12,
                marginBottom: 12,
              }}
            >
              {typeLabel}
            </div>
          )}
          {decorationIcon && (
            <div style={decorationStyle}>{decorationIcon}</div>
          )}
          {cardTitle && (
            <div
              style={{
                fontSize: 16,
                fontWeight: 600,
                marginBottom: 8,
                color: "#1f1f1f",
              }}
            >
              {titleEl}
            </div>
          )}
          {renderChildren(component)}
        </div>
      );
    }

    case "Text": {
      const textContent = safeRenderText(component.text);
      const isHtml = /<[a-z][\s\S]*>/i.test(textContent);

      if (isHtml) {
        if (component.variant === "h3" || component.variant === "title") {
          return (
            <h4
              style={{
                margin: 0,
                fontSize: 16,
                fontWeight: 600,
                marginBottom: 8,
                color: "#1f1f1f",
              }}
              dangerouslySetInnerHTML={{ __html: textContent }}
            />
          );
        }
        if (component.variant === "subtitle") {
          return (
            <h5
              style={{ margin: 0, fontSize: 14, marginBottom: 8, color: "#1f1f1f" }}
              dangerouslySetInnerHTML={{ __html: textContent }}
            />
          );
        }
        if (component.variant === "paragraph") {
          return (
            <p
              style={{
                margin: 0,
                fontSize: 14,
                color: "#595959",
                marginBottom: 16,
                lineHeight: 1.6,
              }}
              dangerouslySetInnerHTML={{ __html: textContent }}
            />
          );
        }
        return (
          <div
            style={{
              fontSize: 14,
              color: "#595959",
              lineHeight: 1.6,
            }}
            dangerouslySetInnerHTML={{ __html: textContent }}
          />
        );
      }

      if (component.variant === "h3" || component.variant === "title") {
        return (
          <div
            style={{
              fontSize: 16,
              fontWeight: 600,
              marginBottom: 8,
              color: "#1f1f1f",
            }}
          >
            {textContent}
          </div>
        );
      }
      if (component.variant === "subtitle") {
        return (
          <div
            style={{ fontSize: 14, marginBottom: 8, color: "#1f1f1f" }}
          >
            {textContent}
          </div>
        );
      }
      if (component.variant === "paragraph") {
        return (
          <div
            style={{
              fontSize: 14,
              color: "#595959",
              marginBottom: 16,
              lineHeight: 1.6,
            }}
          >
            {textContent}
          </div>
        );
      }
      if (component.variant === "secondary") {
        return (
          <div style={{ fontSize: 14, color: "#8c8c8c" }}>
            {textContent}
          </div>
        );
      }
      return (
        <div style={{ fontSize: 14, color: "#595959", lineHeight: 1.6 }}>
          {textContent}
        </div>
      );
    }

    case "Button": {
      const variant = component.variant || "primary";
      const action = component.action;
      const actionName =
        typeof action === "object" ? action?.event?.name : action;
      const actionPayload =
        typeof action === "object" ? action?.event?.payload : undefined;
      const isFormSubmit =
        typeof actionName === "string" && actionName.startsWith("form:submit");

      // Map variant to Ant Design button type
      let buttonType: "primary" | "default" | "dashed" = "default";
      if (variant === "primary" || variant === "success") {
        buttonType = "primary";
      } else if (variant === "dashed") {
        buttonType = "dashed";
      }

      const isDanger = variant === "danger";

      // Custom style for different variants
      let customStyle: React.CSSProperties = {
        marginRight: 8,
        marginBottom: 8,
        borderRadius: 6,
        padding: "6px 16px",
        fontSize: 14,
        height: "auto",
      };

      if (variant === "success") {
        customStyle = {
          ...customStyle,
          background: "#52c41a",
          borderColor: "#52c41a",
          color: "white",
        };
      } else if (variant === "danger") {
        customStyle = {
          ...customStyle,
          background: "#ff4d4f",
          borderColor: "#ff4d4f",
          color: "white",
        };
      }

      return (
        <Button
          type={buttonType}
          danger={isDanger}
          loading={submitting && isFormSubmit}
          onClick={() => {
            if (isFormSubmit && component.dataBinding) {
              handleFormSubmit(component.dataBinding);
            } else if (actionName) {
              handleAction(actionName, actionPayload || formData);
            }
          }}
          style={customStyle}
        >
          {(() => {
            const btnText = safeRenderText(component.text) || safeRenderText(component.label);
            const btnIsHtml = /<[a-z][\s\S]*>/i.test(btnText);
            return btnIsHtml ? (
              <span dangerouslySetInnerHTML={{ __html: btnText }} />
            ) : (
              btnText
            );
          })()}
        </Button>
      );
    }

    case "TextField": {
      const binding = component.dataBinding || component.id;
      const label =
        safeRenderText(component.props?.label) || safeRenderText(component.label);
      const placeholder =
        safeRenderText(component.props?.placeholder) ||
        safeRenderText(component.placeholder);
      const required =
        (component.props?.required as boolean) ??
        component.required ??
        false;
      const defaultValue =
        safeRenderText(dataModel?.[binding]) || safeRenderText(component.value);
      return (
        <div style={{ marginBottom: 12 }}>
          {label && (
            <label
              style={{
                display: "block",
                marginBottom: 6,
                fontSize: 13,
                color: "#595959",
              }}
            >
              {label}
              {required && <span style={{ color: "#ff4d4f" }}> *</span>}
            </label>
          )}
          <Input
            placeholder={placeholder}
            defaultValue={defaultValue}
            required={required}
            onChange={(e) => handleDataChange(binding, e.target.value)}
            style={{
              borderRadius: 6,
              padding: "8px 12px",
              fontSize: 14,
            }}
          />
        </div>
      );
    }

    case "TextArea": {
      const binding = component.dataBinding || component.id;
      const label =
        safeRenderText(component.props?.label) || safeRenderText(component.label);
      const placeholder =
        safeRenderText(component.props?.placeholder) ||
        safeRenderText(component.placeholder);
      const required =
        (component.props?.required as boolean) ??
        component.required ??
        false;
      const defaultValue =
        safeRenderText(dataModel?.[binding]) || safeRenderText(component.value);
      return (
        <div style={{ marginBottom: 12 }}>
          {label && (
            <label
              style={{
                display: "block",
                marginBottom: 6,
                fontSize: 13,
                color: "#595959",
              }}
            >
              {label}
              {required && <span style={{ color: "#ff4d4f" }}> *</span>}
            </label>
          )}
          <TextArea
            placeholder={placeholder}
            defaultValue={defaultValue}
            required={required}
            onChange={(e) => handleDataChange(binding, e.target.value)}
            autoSize={{ minRows: 3, maxRows: 6 }}
            style={{
              borderRadius: 6,
              padding: "8px 12px",
              fontSize: 14,
              minHeight: 60,
            }}
          />
        </div>
      );
    }

    case "CheckBox":
    case "Checkbox": {
      const binding = component.dataBinding || component.id;
      const defaultChecked =
        (dataModel?.[binding] as boolean) ?? component.checked ?? false;
      return (
        <Checkbox
          defaultChecked={defaultChecked}
          onChange={(e) => handleDataChange(binding, e.target.checked)}
          style={{ marginBottom: 8 }}
        >
          {safeRenderText(component.text) || safeRenderText(component.label)}
        </Checkbox>
      );
    }

    case "Form": {
      const interactionId = component.dataBinding || component.id;
      const title = safeRenderText(component.text) || safeRenderText(component.label) || "Form";
      const hasSubmitButton = component.children?.some(
        (child: any) =>
          child?.component === "Button" &&
          (child?.action?.event?.name?.startsWith("submit") ||
            child?.text?.toLowerCase().includes("submit"))
      );
      return (
        <Form
          layout="vertical"
          onFinish={() => handleFormSubmit(interactionId)}
          style={{ marginBottom: 12 }}
        >
          {title && (
            <Form.Item>
              <div
                style={{
                  fontSize: 14,
                  fontWeight: 600,
                  marginBottom: 16,
                  color: "#1f1f1f",
                }}
              >
                {title}
              </div>
            </Form.Item>
          )}
          {renderChildren(component)}
          {!hasSubmitButton && (
            <Form.Item>
              <Space>
                <Button
                  type="primary"
                  htmlType="submit"
                  loading={submitting}
                  style={{ borderRadius: 6, padding: "6px 16px" }}
                >
                  提交
                </Button>
              </Space>
            </Form.Item>
          )}
        </Form>
      );
    }

    case "Icon": {
      const iconName = safeRenderText(component.text) || component.id || "";
      const icon = iconMap[iconName] || <PushpinOutlined />;
      return <span style={{ fontSize: 16 }}>{icon}</span>;
    }

    case "Rating": {
      const binding = component.dataBinding || "rating.value";
      const maxValue = (component.props?.maxValue as number) || 5;
      return (
        <div style={{ marginBottom: 12 }}>
          <Rate
            count={maxValue}
            onChange={(value) => handleDataChange(binding, value)}
            style={{ fontSize: 28 }}
          />
        </div>
      );
    }

    case "Chart": {
      const chartType = component.props?.chartType as string || "bar";
      const chartData = component.props?.data as any || {};
      const chartOptions = component.props?.options as any || {};
      return (
        <A2UIChart
          chartType={chartType}
          data={chartData}
          options={chartOptions}
        />
      );
    }

    default:
      return renderChildren(component);
  }
};

const A2UIRenderer: React.FC<A2UIRendererProps> = ({
  surfaces,
  pendingInteractions,
  onAction,
}) => {
  const handleAction = useCallback(
    async (action: string, data?: Record<string, any>) => {
      try {
        const response = await fetch("/api/a2ui/action", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action, data }),
        });
        if (!response.ok) {
          throw new Error(`Action failed: ${response.status}`);
        }
        if (onAction) {
          await onAction(action, data);
        }
      } catch (err) {
        console.error("A2UI action error:", err);
        message.error("操作失败，请重试。");
        throw err;
      }
    },
    [onAction]
  );

  const handleFormSubmit = useCallback(
    async (interactionId: string, formData: Record<string, any>) => {
      try {
        const response = await fetch("/api/a2ui/action", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            action: "form:submit",
            data: { interactionId, ...formData },
          }),
        });
        if (!response.ok) {
          throw new Error(`Form submission failed: ${response.status}`);
        }
        message.success("表单提交成功！");
      } catch (err) {
        console.error("Form submission error:", err);
        message.error("表单提交失败，请重试。");
        throw err;
      }
    },
    []
  );

  if (!surfaces || surfaces.length === 0) {
    console.log("[A2UI_DEBUG] A2UIRenderer returning null - no surfaces");
    return null;
  }

  console.log("[A2UI_DEBUG] A2UIRenderer rendering:", {
    surfacesCount: surfaces.length,
    surfaceDetails: surfaces.map(s => ({
      surfaceId: s.surfaceId,
      componentCount: s.components?.length || 0,
      componentTypes: s.components?.map(c => c.component) || [],
    })),
  });

  return (
    <ConfigProvider>
      <div className="a2ui-renderer">
        {surfaces.map((surface) => (
          <div
            key={surface.surfaceId}
            className="a2ui-surface"
            style={{ marginBottom: 16 }}
          >
            {surface.components.map((comp) => (
              <A2UIComponentRenderer
                key={comp.id}
                component={comp}
                dataModel={surface.dataModel}
                onAction={handleAction}
                onFormSubmit={handleFormSubmit}
                surfaceId={surface.surfaceId}
                surfaceCatalog={surface.catalog}
              />
            ))}
          </div>
        ))}
      </div>
    </ConfigProvider>
  );
};

interface A2UIChatMessageProps {
  surfaces?: A2UISurface[];
  pendingInteractions?: HITLInteraction[];
  onAction?: (action: string, data?: Record<string, any>) => Promise<void> | void;
  messageId?: string;
}

export const A2UIChatMessage: React.FC<A2UIChatMessageProps> = ({
  surfaces,
  pendingInteractions,
  onAction,
  messageId,
}) => {
  console.log("[A2UI_DEBUG] A2UIChatMessage render:", {
    hasSurfaces: !!(surfaces && surfaces.length > 0),
    surfacesCount: surfaces?.length || 0,
    pendingInteractionsCount: pendingInteractions?.length || 0,
    messageId,
  });
  if (
    (!surfaces || surfaces.length === 0) &&
    (!pendingInteractions || pendingInteractions.length === 0)
  ) {
    console.log("[A2UI_DEBUG] A2UIChatMessage returning null - no surfaces or interactions");
    return null;
  }

  return (
    <div className="a2ui-chat-message" style={{ marginTop: 12 }}>
      {pendingInteractions && pendingInteractions.length > 0 && (
        <div className="a2ui-pending-interactions" style={{ marginBottom: 12 }}>
          {pendingInteractions.map((interaction) => (
            <Tag
              key={interaction.interaction_id}
              color="orange"
              style={{ marginBottom: 8 }}
            >
              待处理交互: {interaction.prompt || interaction.interaction_id}
            </Tag>
          ))}
        </div>
      )}
      <A2UIRenderer
        surfaces={surfaces || []}
        pendingInteractions={pendingInteractions}
        onAction={onAction}
        messageId={messageId}
      />
    </div>
  );
};

export default A2UIRenderer;
