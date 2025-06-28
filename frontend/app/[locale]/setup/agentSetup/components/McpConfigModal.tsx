"use client"

import { useState, useEffect } from 'react'
import { Modal, Button, Input, Table, message, Space, Typography, Card, Divider, Tag } from 'antd'
import { DeleteOutlined, EyeOutlined, PlusOutlined, LoadingOutlined, ExpandAltOutlined, CompressOutlined, RedoOutlined } from '@ant-design/icons'
import { getMcpServerList, addMcpServer, deleteMcpServer, getMcpTools, updateToolList, recoverMcpServers, McpServer, McpTool } from '@/services/mcpService'

const { Text, Title } = Typography

interface McpConfigModalProps {
  visible: boolean
  onCancel: () => void
}

export default function McpConfigModal({ visible, onCancel }: McpConfigModalProps) {
  const [serverList, setServerList] = useState<McpServer[]>([])
  const [loading, setLoading] = useState(false)
  const [addingServer, setAddingServer] = useState(false)
  const [newServerName, setNewServerName] = useState('')
  const [newServerUrl, setNewServerUrl] = useState('')
  const [toolsModalVisible, setToolsModalVisible] = useState(false)
  const [currentServerTools, setCurrentServerTools] = useState<McpTool[]>([])
  const [currentServerName, setCurrentServerName] = useState('')
  const [loadingTools, setLoadingTools] = useState(false)
  const [expandedDescriptions, setExpandedDescriptions] = useState<Set<string>>(new Set())
  const [recovering, setRecovering] = useState(false)
  const [updatingTools, setUpdatingTools] = useState(false)

  // 加载MCP服务器列表
  const loadServerList = async () => {
    setLoading(true)
    try {
      const result = await getMcpServerList()
      if (result.success) {
        setServerList(result.data)
      } else {
        message.error(result.message)
      }
    } catch (error) {
      message.error('加载服务器列表失败')
    } finally {
      setLoading(false)
    }
  }

  // 添加MCP服务器
  const handleAddServer = async () => {
    if (!newServerName.trim() || !newServerUrl.trim()) {
      message.error('请填写完整的服务器名称和URL')
      return
    }

    // 验证服务器名称格式
    const serverName = newServerName.trim()
    const nameRegex = /^[a-zA-Z0-9]+$/
    
    if (!nameRegex.test(serverName)) {
      message.error('服务器名称只能包含英文字母和数字')
      return
    }
    
    if (serverName.length > 20) {
      message.error('服务器名称长度不能超过20个字符')
      return
    }

    // 检查是否已存在相同的服务器
    const exists = serverList.some(
      server => server.service_name === serverName || server.mcp_url === newServerUrl.trim()
    )
    if (exists) {
      message.error('服务器名称或URL已存在')
      return
    }

    setAddingServer(true)
    try {
      const result = await addMcpServer(newServerUrl.trim(), serverName)
      if (result.success) {
        message.success('添加MCP服务器成功，正在自动更新工具列表...')
        setNewServerName('')
        setNewServerUrl('')
        await loadServerList() // 重新加载列表
        
        // 设置工具更新状态并自动刷新工具列表
        setUpdatingTools(true)
        try {
          const updateResult = await updateToolList()
          if (updateResult.success) {
            message.success('MCP服务器添加成功，工具列表已更新')
            // 通知父组件更新工具列表
            window.dispatchEvent(new CustomEvent('toolsUpdated'))
          } else {
            message.warning('MCP服务器添加成功，但工具列表更新失败')
          }
        } catch (updateError) {
          console.log('自动更新工具列表失败:', updateError)
          message.warning('MCP服务器添加成功，但工具列表更新失败')
        } finally {
          setUpdatingTools(false)
        }
      } else {
        message.error(result.message)
      }
    } catch (error) {
      message.error('添加服务器失败')
    } finally {
      setAddingServer(false)
    }
  }

  // 删除MCP服务器
  const handleDeleteServer = async (server: McpServer) => {
    Modal.confirm({
      title: '确认删除',
      content: `确定要删除MCP服务器 "${server.service_name}" 吗？`,
      okType: 'danger',
      cancelButtonProps: { disabled: updatingTools },
      okButtonProps: { disabled: updatingTools, loading: updatingTools },
      onOk: async () => {
        try {
          const result = await deleteMcpServer(server.mcp_url, server.service_name)
          if (result.success) {
            message.success('删除MCP服务器成功')
            await loadServerList() // 重新加载列表
            
            // 删除成功后立即关闭确认弹窗，然后异步更新工具列表
            setTimeout(async () => {
              message.info('正在自动更新工具列表...')
              setUpdatingTools(true)
              try {
                const updateResult = await updateToolList()
                if (updateResult.success) {
                  message.success('工具列表已更新')
                  // 通知父组件更新工具列表
                  window.dispatchEvent(new CustomEvent('toolsUpdated'))
                } else {
                  message.warning('工具列表更新失败')
                }
              } catch (updateError) {
                console.log('自动更新工具列表失败:', updateError)
                message.warning('工具列表更新失败')
              } finally {
                setUpdatingTools(false)
              }
            }, 100) // 给确认弹窗关闭一点时间
          } else {
            message.error(result.message)
          }
        } catch (error) {
          message.error('删除服务器失败')
        }
      }
    })
  }

  // 查看服务器工具
  const handleViewTools = async (server: McpServer) => {
    setCurrentServerName(server.service_name)
    setLoadingTools(true)
    setToolsModalVisible(true)
    setExpandedDescriptions(new Set()) // 重置展开状态
    
    try {
      const result = await getMcpTools(server.service_name, server.mcp_url)
      if (result.success) {
        setCurrentServerTools(result.data)
      } else {
        message.error(result.message)
        setCurrentServerTools([])
      }
    } catch (error) {
      message.error('获取工具列表失败')
      setCurrentServerTools([])
    } finally {
      setLoadingTools(false)
    }
  }

  // 切换描述展开状态
  const toggleDescription = (toolName: string) => {
    const newExpanded = new Set(expandedDescriptions)
    if (newExpanded.has(toolName)) {
      newExpanded.delete(toolName)
    } else {
      newExpanded.add(toolName)
    }
    setExpandedDescriptions(newExpanded)
  }

  // 重新挂载所有MCP服务器
  const handleRecoverServers = async () => {
    setRecovering(true)
    try {
      const result = await recoverMcpServers()
      if (result.success) {
        message.success('重新挂载MCP服务器成功')
      } else {
        message.error(result.message)
      }
    } catch (error) {
      message.error('重新挂载MCP服务器失败')
    } finally {
      setRecovering(false)
    }
  }

  // 服务器列表表格列定义
  const columns = [
    {
      title: '服务器名称',
      dataIndex: 'service_name',
      key: 'service_name',
      width: '25%',
      ellipsis: true,
    },
    {
      title: 'URL',
      dataIndex: 'mcp_url',
      key: 'mcp_url',
      width: '45%',
      ellipsis: true,
    },
    {
      title: '操作',
      key: 'action',
      width: '30%',
      render: (_: any, record: McpServer) => (
        <Space size="small">
          <Button
            type="link"
            icon={<EyeOutlined />}
            onClick={() => handleViewTools(record)}
            size="small"
            disabled={updatingTools}
          >
            查看工具
          </Button>
          <Button
            type="link"
            danger
            icon={<DeleteOutlined />}
            onClick={() => handleDeleteServer(record)}
            size="small"
            disabled={updatingTools}
          >
            删除
          </Button>
        </Space>
      ),
    },
  ]

  // 工具列表表格列定义
  const toolColumns = [
    {
      title: '工具名称',
      dataIndex: 'name',
      key: 'name',
      width: '30%',
    },
    {
      title: '描述',
      dataIndex: 'description',
      key: 'description',
      width: '70%',
      render: (text: string, record: McpTool) => {
        const isExpanded = expandedDescriptions.has(record.name)
        const maxLength = 100 // 描述超过100字符时显示展开按钮
        const needsExpansion = text && text.length > maxLength
        
        return (
          <div>
            <div style={{ marginBottom: needsExpansion ? 8 : 0 }}>
              {needsExpansion && !isExpanded 
                ? `${text.substring(0, maxLength)}...` 
                : text}
            </div>
            {needsExpansion && (
              <Button
                type="link"
                size="small"
                icon={isExpanded ? <CompressOutlined /> : <ExpandAltOutlined />}
                onClick={() => toggleDescription(record.name)}
                style={{ padding: 0, height: 'auto' }}
              >
                {isExpanded ? '收起' : '展开'}
              </Button>
            )}
          </div>
        )
      },
    },
  ]

  // 打开弹窗时加载数据
  useEffect(() => {
    if (visible) {
      loadServerList()
    }
  }, [visible])

  return (
    <>
      <Modal
        title="MCP服务器配置"
        open={visible}
        onCancel={updatingTools ? undefined : onCancel}
        width={800}
        closable={!updatingTools}
        maskClosable={!updatingTools}
        footer={[
          <Button key="cancel" onClick={onCancel} disabled={updatingTools}>
            {updatingTools ? '正在更新工具列表...' : '关闭'}
          </Button>
        ]}
      >
        <div style={{ padding: '0 0 16px 0' }}>
          {/* 工具更新状态提示 */}
          {updatingTools && (
            <div style={{ 
              marginBottom: 16, 
              padding: 12, 
              backgroundColor: '#f6ffed', 
              border: '1px solid #b7eb8f', 
              borderRadius: 6,
              display: 'flex',
              alignItems: 'center'
            }}>
              <LoadingOutlined style={{ marginRight: 8, color: '#52c41a' }} />
              <Text style={{ color: '#52c41a' }}>正在自动更新工具列表，请勿关闭页面或取消操作...</Text>
            </div>
          )}
          {/* 添加服务器区域 */}
          <Card size="small" style={{ marginBottom: 16 }}>
            <Title level={5} style={{ margin: '0 0 12px 0' }}>
              <PlusOutlined style={{ marginRight: 8 }} />
              添加MCP服务器
            </Title>
            <Space direction="vertical" style={{ width: '100%' }}>
              <div style={{ display: 'flex', gap: 8 }}>
                <Input
                  placeholder="服务器名称（仅支持英文、数字，最多20字符）"
                  value={newServerName}
                  onChange={(e) => setNewServerName(e.target.value)}
                  style={{ flex: 1 }}
                  maxLength={20}
                  disabled={updatingTools || addingServer}
                />
                <Input
                  placeholder="服务器URL (如: http://localhost:3001/sse)，目前仅支持sse协议"
                  value={newServerUrl}
                  onChange={(e) => setNewServerUrl(e.target.value)}
                  style={{ flex: 2 }}
                  disabled={updatingTools || addingServer}
                />
                <Button
                  type="primary"
                  onClick={handleAddServer}
                  loading={addingServer || updatingTools}
                  icon={(addingServer || updatingTools) ? <LoadingOutlined /> : <PlusOutlined />}
                  disabled={updatingTools}
                >
                  {updatingTools ? '更新中...' : '添加'}
                </Button>
              </div>
            </Space>
          </Card>

          <Divider style={{ margin: '16px 0' }} />

          {/* 服务器列表 */}
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
              <Title level={5} style={{ margin: 0 }}>
                已配置的MCP服务器
              </Title>
              <Button
                type="text"
                size="small"
                icon={recovering ? <LoadingOutlined /> : <RedoOutlined />}
                onClick={handleRecoverServers}
                loading={recovering}
                disabled={recovering || loading || updatingTools}
                className="text-orange-500 hover:text-orange-600 hover:bg-orange-50"
                title="重新挂载所有MCP服务器"
              >
                重新挂载
              </Button>
            </div>
            <Table
              columns={columns}
              dataSource={serverList}
              rowKey={(record) => `${record.service_name}-${record.mcp_url}`}
              loading={loading}
              size="small"
              pagination={false}
              locale={{ emptyText: '暂无MCP服务器' }}
              scroll={{ y: 300 }}
              style={{ width: '100%' }}
            />
          </div>
        </div>
      </Modal>

      {/* 工具列表弹窗 */}
      <Modal
        title={`${currentServerName} - 可用工具`}
        open={toolsModalVisible}
        onCancel={() => setToolsModalVisible(false)}
        width={1000}
        footer={[
          <Button key="close" onClick={() => setToolsModalVisible(false)}>
            关闭
          </Button>
        ]}
      >
        <div style={{ padding: '0 0 16px 0' }}>
          {loadingTools ? (
            <div style={{ textAlign: 'center', padding: '40px 0' }}>
              <LoadingOutlined style={{ fontSize: 24, marginRight: 8 }} />
              <Text>正在加载工具列表...</Text>
            </div>
          ) : (
            <Table
              columns={toolColumns}
              dataSource={currentServerTools}
              rowKey="name"
              size="small"
              pagination={false}
              locale={{ emptyText: '该服务器暂无可用工具' }}
              scroll={{ y: 500 }}
              style={{ width: '100%' }}
            />
          )}
        </div>
      </Modal>
    </>
  )
}