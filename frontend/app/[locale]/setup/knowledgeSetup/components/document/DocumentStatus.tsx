import React from 'react'
import { useTranslation } from 'react-i18next'

interface DocumentStatusProps {
  status: string
  showIcon?: boolean
}

export const DocumentStatus: React.FC<DocumentStatusProps> = ({ 
  status, 
  showIcon = false, 
}) => {
  const { t } = useTranslation();

  // Map API status to display status
  const getDisplayStatus = (apiStatus: string): string => {
    switch (apiStatus) {
      case 'WAIT_FOR_PROCESSING':
        return t('document.status.waitForProcessing')
      case 'WAIT_FOR_FORWARDING':
        return t('document.status.waitForForwarding')
      case 'PROCESSING':
        return t('document.status.processing')
      case 'FORWARDING': 
        return t('document.status.forwarding')
      case 'COMPLETED':
        return t('document.status.completed')
      case 'PROCESS_FAILED':
        return t('document.status.processFailed')
      case 'FORWARD_FAILED':
        return t('document.status.forwardFailed')
      default:
        return apiStatus
    }
  }

  // Get status type and corresponding styles
  const getStatusStyles = (): { bgColor: string, textColor: string, borderColor: string } => {
    switch (status) {
      case 'COMPLETED':
        return { 
          bgColor: 'bg-green-100', 
          textColor: 'text-green-800', 
          borderColor: 'border-green-200' 
        }
      case 'PROCESSING':
      case 'FORWARDING':
        return { 
          bgColor: 'bg-blue-100', 
          textColor: 'text-blue-800', 
          borderColor: 'border-blue-200' 
        }
      case 'PROCESS_FAILED':
      case 'FORWARD_FAILED':
        return { 
          bgColor: 'bg-red-100', 
          textColor: 'text-red-800', 
          borderColor: 'border-red-200' 
        }
      case 'WAIT_FOR_PROCESSING':
      case 'WAIT_FOR_FORWARDING':
        return { 
          bgColor: 'bg-yellow-100', 
          textColor: 'text-yellow-800', 
          borderColor: 'border-yellow-200' 
        }
      default:
        return { 
          bgColor: 'bg-gray-100', 
          textColor: 'text-gray-800', 
          borderColor: 'border-gray-200' 
        }
    }
  }

  // Get status icon
  const getStatusIcon = () => {
    if (!showIcon) return null

    switch (status) {
      case 'COMPLETED':
        return '✓'
      case 'PROCESSING':
      case 'FORWARDING':
        return '⟳'
      case 'PROCESS_FAILED':
      case 'FORWARD_FAILED':
        return '✗'
      case 'WAIT_FOR_PROCESSING':
      case 'WAIT_FOR_FORWARDING':
        return '⏱'
      default:
        return null
    }
  }

  const { bgColor, textColor, borderColor } = getStatusStyles();
  const displayStatus = getDisplayStatus(status);

  return (
    <span className={`inline-flex items-center px-1.5 py-0.5 rounded-md text-xs font-medium ${bgColor} ${textColor} border ${borderColor} whitespace-nowrap`}>
      {showIcon && <span className="mr-1">{getStatusIcon()}</span>}
      {displayStatus}
    </span>
  )
}

export default DocumentStatus 