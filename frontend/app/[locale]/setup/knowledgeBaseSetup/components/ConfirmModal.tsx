import React from 'react'
import { Modal, App } from 'antd'
import { useTranslation } from 'react-i18next'
import i18next from 'i18next'

interface ConfirmModalProps {
  title: string
  content: React.ReactNode
  okText?: string
  cancelText?: string
  danger?: boolean
  visible: boolean
  onConfirm: () => void
  onCancel: () => void
}

interface StaticConfirmProps {
  title: string
  content: React.ReactNode
  okText?: string
  cancelText?: string
  danger?: boolean
  onConfirm?: () => void
  onCancel?: () => void
}

// 组件定义
const ConfirmModal: React.FC<ConfirmModalProps> = ({ 
  title,
  content,
  okText,
  cancelText,
  danger = false,
  visible,
  onConfirm,
  onCancel
}) => {
  const { t } = useTranslation()

  return (
    <Modal
      title={title}
      open={visible}
      onOk={onConfirm}
      onCancel={onCancel}
      okText={okText || t('common.confirm')}
      cancelText={cancelText || t('common.cancel')}
      okButtonProps={{ danger }}
    >
      {content}
    </Modal>
  )
}

// 提供一个 hook 来获取 confirm 方法
export const useConfirmModal = () => {
  const { modal } = App.useApp()
  
  const confirm = ({
    title,
    content,
    okText,
    cancelText,
    danger = false,
    onConfirm,
    onCancel
  }: StaticConfirmProps) => {
    return modal.confirm({
      title,
      content,
      okText: okText || i18next.t('common.confirm'),
      cancelText: cancelText || i18next.t('common.cancel'),
      okButtonProps: { danger },
      onOk: onConfirm,
      onCancel
    })
  }
  
  return { confirm }
}

export default ConfirmModal