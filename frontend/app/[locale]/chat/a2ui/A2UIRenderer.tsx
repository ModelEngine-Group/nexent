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
  FontSizeOutlined,
  FormOutlined,
  CheckSquareOutlined,
  PushpinOutlined,
} from "@ant-design/icons";
import type { A2UIComponent, A2UISurface, HITLInteraction } from "@/types/chat";

const { TextArea } = Input;
const { Title, Text, Paragraph } = Typography;

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
}

const iconMap: Record<string, React.ReactNode> = {
  pushpin: <PushpinOutlined />,
  form: <FormOutlined />,
  checkbox: <CheckSquareOutlined />,
  textfield: <FontSizeOutlined />,
};

const A2UIComponentRenderer: React.FC<A2UIComponentRendererProps> = ({
  component,
  dataModel,
  onAction,
  onDataChange,
  formData,
  onFormSubmit,
}) => {
  // Debug: log each component being rendered
  console.log("[A2UIComponentRenderer] rendering:", component.component, "text:", component.text, "variant:", component.variant);

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
        />
      ));
    }
    return null;
  };

  switch (component.component) {
    case "Row": {
      const distribution = component.distribution || "start";
      const alignment = component.alignment || "stretch";
      return (
        <Row
          gutter={component.spacing ?? 12}
          wrap={component.wrap ?? true}
          justify={distribution as any}
          align={alignment as any}
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
      const cardTitle = component.text || component.label || "";
      const titleIsHtml = /<[a-z][\s\S]*>/i.test(cardTitle);
      const titleEl = titleIsHtml ? (
        <span dangerouslySetInnerHTML={{ __html: cardTitle }} />
      ) : (
        cardTitle || undefined
      );
      return (
        <Card
          title={titleEl}
          variant={component.variant === "borderless" ? "borderless" : "outlined"}
          style={{ marginBottom: 12 }}
        >
          {renderChildren(component)}
        </Card>
      );
    }

    case "Text": {
      const textContent = component.text || "";
      const isHtml = /<[a-z][\s\S]*>/i.test(textContent);

      if (isHtml) {
        if (component.variant === "h3" || component.variant === "title") {
          return <h4 style={{ margin: 0 }} dangerouslySetInnerHTML={{ __html: textContent }} />;
        }
        if (component.variant === "subtitle") {
          return <h5 style={{ margin: 0 }} dangerouslySetInnerHTML={{ __html: textContent }} />;
        }
        if (component.variant === "paragraph") {
          return <p style={{ margin: 0 }} dangerouslySetInnerHTML={{ __html: textContent }} />;
        }
        return <div dangerouslySetInnerHTML={{ __html: textContent }} />;
      }

      if (component.variant === "h3" || component.variant === "title") {
        return <Title level={4}>{textContent}</Title>;
      }
      if (component.variant === "subtitle") {
        return <Title level={5}>{textContent}</Title>;
      }
      if (component.variant === "paragraph") {
        return <Paragraph>{textContent}</Paragraph>;
      }
      if (component.variant === "secondary") {
        return <Text type="secondary">{textContent}</Text>;
      }
      return <Text>{textContent}</Text>;
    }

    case "Button": {
      const variant = component.variant || "primary";
      const actionName = component.action?.event?.name || component.action;
      const actionPayload = component.action?.event?.payload;
      const isFormSubmit = typeof actionName === "string" && actionName.startsWith("form:submit");
      return (
        <Button
          type={variant === "primary" ? "primary" : variant === "dashed" ? "dashed" : "default"}
          danger={component.variant === "danger"}
          loading={submitting && isFormSubmit}
          onClick={() => {
            if (isFormSubmit && component.dataBinding) {
              handleFormSubmit(component.dataBinding);
            } else if (actionName) {
              handleAction(actionName, actionPayload || formData);
            }
          }}
          style={{ marginRight: 8, marginBottom: 8 }}
        >
          {(() => {
            const btnText = component.text || component.label || "";
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
      const label = (component.props?.label as string) || component.label || "";
      const placeholder = (component.props?.placeholder as string) || component.placeholder || "";
      const required = (component.props?.required as boolean) ?? component.required ?? false;
      const defaultValue =
        (dataModel?.[binding] as string) || component.value || "";
      return (
        <div style={{ marginBottom: 8 }}>
          {label && <label style={{ display: "block", marginBottom: 4, fontSize: 14 }}>{label}{required && <span style={{ color: "red" }}> *</span>}</label>}
          <Input
            placeholder={placeholder}
            defaultValue={defaultValue}
            required={required}
            onChange={(e) => handleDataChange(binding, e.target.value)}
          />
        </div>
      );
    }

    case "TextArea": {
      const binding = component.dataBinding || component.id;
      const label = (component.props?.label as string) || component.label || "";
      const placeholder = (component.props?.placeholder as string) || component.placeholder || "";
      const required = (component.props?.required as boolean) ?? component.required ?? false;
      const defaultValue =
        (dataModel?.[binding] as string) || component.value || "";
      return (
        <div style={{ marginBottom: 8 }}>
          {label && <label style={{ display: "block", marginBottom: 4, fontSize: 14 }}>{label}{required && <span style={{ color: "red" }}> *</span>}</label>}
          <TextArea
            placeholder={placeholder}
            defaultValue={defaultValue}
            required={required}
            onChange={(e) => handleDataChange(binding, e.target.value)}
            autoSize={{ minRows: 2, maxRows: 6 }}
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
          {component.text || component.label}
        </Checkbox>
      );
    }

    case "Form": {
      const interactionId = component.dataBinding || component.id;
      const title = component.text || component.label || "Form";
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
              <Title level={5} style={{ marginBottom: 16 }}>
                {title}
              </Title>
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
                >
                  Submit
                </Button>
              </Space>
            </Form.Item>
          )}
        </Form>
      );
    }

    case "Icon": {
      const iconName = component.text || component.id;
      const icon = iconMap[iconName] || <PushpinOutlined />;
      return <span style={{ fontSize: 16 }}>{icon}</span>;
    }

    case "Rating": {
      const binding = component.dataBinding || "rating.value";
      const maxValue = (component.props?.maxValue as number) || 5;
      return (
        <div style={{ marginBottom: 8 }}>
          <Rate
            count={maxValue}
            onChange={(value) => handleDataChange(binding, value)}
          />
        </div>
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
        message.error("Action failed. Please try again.");
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
        message.success("Form submitted successfully.");
      } catch (err) {
        console.error("Form submission error:", err);
        message.error("Form submission failed.");
        throw err;
      }
    },
    []
  );

  if (!surfaces || surfaces.length === 0) {
    return null;
  }

  return (
    <ConfigProvider>
      <div className="a2ui-renderer">
        {surfaces.map((surface) => (
          <div key={surface.surfaceId} className="a2ui-surface" style={{ marginBottom: 16 }}>
            {surface.components.map((comp) => (
              <A2UIComponentRenderer
                key={comp.id}
                component={comp}
                dataModel={surface.dataModel}
                onAction={handleAction}
                onFormSubmit={handleFormSubmit}
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
  // Debug: log surfaces data to help diagnose rendering issues
  console.log("[A2UIChatMessage] surfaces:", surfaces, "messageId:", messageId);

  if ((!surfaces || surfaces.length === 0) && (!pendingInteractions || pendingInteractions.length === 0)) {
    return null;
  }

  return (
    <div className="a2ui-chat-message" style={{ marginTop: 12, border: "2px dashed #1890ff", padding: 8, borderRadius: 8 }}>
      {pendingInteractions && pendingInteractions.length > 0 && (
        <div className="a2ui-pending-interactions" style={{ marginBottom: 12 }}>
          {pendingInteractions.map((interaction) => (
            <Tag
              key={interaction.interaction_id}
              color="orange"
              style={{ marginBottom: 8 }}
            >
              Pending interaction: {interaction.prompt || interaction.interaction_id}
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