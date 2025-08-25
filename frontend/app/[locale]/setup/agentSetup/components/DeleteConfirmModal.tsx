"use client"

import { Modal, Typography } from 'antd'
import { useTranslation } from 'react-i18next'
import { Agent } from '@/types/agent'

interface DeleteConfirmModalProps {
  isOpen: boolean;
  agentToDelete: Agent | null;
  onCancel: () => void;
  onConfirm: () => void;
}

/**
 * Delete Confirmation Modal Component
 */
export default function DeleteConfirmModal({
  isOpen,
  agentToDelete,
  onCancel,
  onConfirm
}: DeleteConfirmModalProps) {
  const { t } = useTranslation('common');

  return (
    <Modal
      title={t('businessLogic.config.modal.deleteTitle')}
      open={isOpen}
      onCancel={onCancel}
      footer={
        <div className="flex justify-end gap-2">
          <button 
            onClick={onCancel}
            className="px-4 py-1.5 rounded-md flex items-center justify-center text-sm bg-gray-100 text-gray-700 hover:bg-gray-200"
            style={{ border: "none" }}
          >
            {t('businessLogic.config.modal.button.cancel')}
          </button>
          <button 
            onClick={onConfirm}
            className="px-4 py-1.5 rounded-md flex items-center justify-center text-sm bg-red-500 text-white hover:bg-red-600"
            style={{ border: "none" }}
          >
            {t('businessLogic.config.modal.button.confirm')}
          </button>
        </div>
      }
      width={400}
    >
      <div className="py-4">
        <Typography.Text>
          {t('businessLogic.config.modal.deleteContent', { name: agentToDelete?.name })}
        </Typography.Text>
      </div>
    </Modal>
  )
} 