import { Modal } from "antd";

interface JsonPreviewModalProps {
  open: boolean;
  title: string;
  json: string;
  onCancel: () => void;
}

export default function JsonPreviewModal({
  open,
  title,
  json,
  onCancel,
}: JsonPreviewModalProps) {
  if (!open) return null;
  return (
    <Modal
      open
      footer={null}
      closable
      centered
      width={720}
      onCancel={onCancel}
      title={title}
      styles={{ body: { paddingTop: 8 } }}
      destroyOnHidden
    >
      <div className="rounded-md border border-slate-200 bg-slate-50">
        <pre className="max-h-[65vh] overflow-auto p-4 font-mono text-xs leading-relaxed text-slate-800">
          {json}
        </pre>
      </div>
    </Modal>
  );
}

