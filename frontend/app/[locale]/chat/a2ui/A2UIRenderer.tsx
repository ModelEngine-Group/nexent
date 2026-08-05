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
  message,
  ConfigProvider,
} from "antd";
import {
  TextFieldOutlined,
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
  textfield: <TextFieldOutlined />,
};

const A2UIComponentRenderer: React.FC<A2UIComponentRendererProps> = ({
  component,
  dataModel,
  onAction,
  onDataChange,
  formData,
  onFormSubmit,
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
      return (
        <Card
          title={component.text || component.label}
          variant={component.variant === "borderless" ? "borderless" : "outlined"}
          style={{ marginBottom: 12 }}
        >
          {renderChildren(component)}
        </Card>
      );
    }

    case "Text": {
      if (component.variant === "title") {
        return <Title level={4}>{component.text}</Title>;
      }
      if (component.variant === "paragraph") {
        return <Paragraph>{component.text}</Paragraph>;
      }
      if (component.variant === "secondary") {
        return <Text type="secondary">{component.text}</Text>;
      }
      return <Text>{component.text}</Text>;
    }

    case "Button": {
      const variant = component.variant || "primary";
      const isFormSubmit = component.action?.startsWith("form:submit");
      return (
        <Button
          type={variant === "primary" ? "primary" : variant === "dashed" ? "dashed" : "default"}
          danger={component.variant === "danger"}
          loading={submitting && isFormSubmit}
          onClick={() => {
            if (isFormSubmit && component.dataBinding) {
              handleFormSubmit(component.dataBinding);
            } else if (component.action) {
              handleAction(component.action, formData);
            }
          }}
          style={{ marginRight: 8, marginBottom: 8 }}
        >
          {component.text || component.label}
        </Button>
      );
    }

    case "TextField": {
      const binding = component.dataBinding || component.id;
      const placeholder = component.placeholder || "";
      const defaultValue =
        (dataModel?.[binding] as string) || component.value || "";
      return (
        <Input
          placeholder={placeholder}
          defaultValue={defaultValue}
          required={component.required}
          onChange={(e) => handleDataChange(binding, e.target.value)}
          style={{ marginBottom: 8 }}
        />
      );
    }

    case "TextArea": {
      const binding = component.dataBinding || component.id;
      const placeholder = component.placeholder || "";
      const defaultValue =
        (dataModel?.[binding] as string) || component.value || "";
      return (
        <TextArea
          placeholder={placeholder}
          defaultValue={defaultValue}
          required={component.required}
          onChange={(e) => handleDataChange(binding, e.target.value)}
          autoSize={{ minRows: 2, maxRows: 6 }}
          style={{ marginBottom: 8 }}
        />
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
      return (
        <Form
          layout="vertical"
          onFinish={() => handleFormSubmit(interactionId)}
          style={{ marginBottom: 12 }}
        >
          <Form.Item>
            <Title level={5} style={{ marginBottom: 16 }}>
              {title}
            </Title>
          </Form.Item>
          {renderChildren(component)}
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
        </Form>
      );
    }

    case "Icon": {
      const iconName = component.text || component.id;
      const icon = iconMap[iconName] || <PushpinOutlined />;
      return <span style={{ fontSize: 16 }}>{icon}</span>;
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
  if ((!surfaces || surfaces.length === 0) && (!pendingInteractions || pendingInteractions.length === 0)) {
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