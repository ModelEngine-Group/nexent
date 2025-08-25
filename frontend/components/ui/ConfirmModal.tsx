import React from 'react'
import { App } from 'antd'
import i18next from 'i18next'

interface StaticConfirmProps {
  title: string
  content: React.ReactNode
  okText?: string
  cancelText?: string
  danger?: boolean
  onConfirm?: () => void
  onCancel?: () => void
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
