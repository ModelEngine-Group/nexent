import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Modal, Input, Badge, Button, Space } from "antd";

export interface ExpandEditModalProps {
  open: boolean;
  title: string;
  content: string;
  onClose: () => void;
  onSave: (content: string) => void;
  readOnly?: boolean;
}

export default function ExpandEditModal({
  open,
  title,
  content,
  onClose,
  onSave,
  readOnly = false,
}:ExpandEditModalProps) {
  const { t } = useTranslation("common");
  const [editContent, setEditContent] = useState(content);

  // Update editContent when content prop changes
  useEffect(() => {
    setEditContent(content);
  }, [content]);

  const handleSave = () => {
    if (!readOnly) {
      onSave(editContent);
    }
    onClose();
  };

  const handleClose = () => {
    // Close without saving changes
    onClose();
  };
  return (
    <Modal
      title={
        <div className="flex justify-between items-center">
          <div className="flex items-center">
            <Badge className="mr-3" />
            <span className="text-base font-medium">{title}</span>
          </div>
        </div>
      }
      open={open}
      onCancel={handleClose}
      footer={
        readOnly ? (
          <Button onClick={handleClose}>
            {t("common.close")}
          </Button>
        ) : (
          <Space>
            <Button onClick={handleClose}>
              {t("common.cancel")}
            </Button>
            <Button type="primary" onClick={handleSave}>
              {t("common.confirm")}
            </Button>
          </Space>
        )
      }
      width={1000}
      styles={{
        body: { padding: "20px" }
      }}
    >
      <div
      >
        <div className="flex-1 min-h-0">
          <Input.TextArea
            value={editContent}
            onChange={(e) => {
              if (!readOnly) {
                setEditContent(e.target.value);
              }
            }}
            style={{
              width: "100%",
              minHeight: "400px",
              resize: "vertical"
            }}
            bordered={true}
            readOnly={readOnly}
          />
        </div>
      </div>
    </Modal>
  );
}