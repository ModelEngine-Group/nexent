import React from "react"
import { useAuth } from "@/hooks/useAuth"
import { Modal, Tabs, Collapse, List, Button, Switch, Pagination, Dropdown, Input, App } from "antd"
import { CaretRightOutlined, DownOutlined } from "@ant-design/icons"
import {
  MessageSquarePlus,
  Eraser,
  MessageSquareOff,
  UsersRound,
  UserRound,
  Bot,
  Share2,
  Settings,
  MessageSquareDashed,
  Check,
  X
} from "lucide-react"
import { useMemory } from "@/hooks/useMemory"
import MemoryDeleteModal from "./memoryDeleteModal"
import { useTranslation } from "react-i18next"

interface MemoryManageModalProps {
  visible: boolean
  onClose: () => void
  userRole?: "admin" | "user"
}

/**
 * 记忆管理弹窗，仅负责 UI 渲染。
 * 复杂状态逻辑由 hooks/useMemory.ts 管理。
 */
const MemoryManageModal: React.FC<MemoryManageModalProps> = ({ visible, onClose, userRole }) => {
  // 获取认证上下文中的用户角色
  const { user } = useAuth()
  const { message } = App.useApp()
  const role: "admin" | "user" = (userRole ?? (user?.role === "admin" ? "admin" : "user")) as "admin" | "user"

  // 真实业务场景可从其他 hooks / context 中获取
  const currentUserId = "user1"
  const currentTenantId = "tenant1"

  const memory = useMemory({ visible, currentUserId, currentTenantId, message })
  const { t } = useTranslation('common')

  // ====================== 清空记忆确认弹框 ======================
  const [clearConfirmVisible, setClearConfirmVisible] = React.useState(false)
  const [clearTarget, setClearTarget] = React.useState<{ key: string; title: string } | null>(null)

  const handleClearConfirm = (groupKey: string, groupTitle: string) => {
    setClearTarget({ key: groupKey, title: groupTitle })
    setClearConfirmVisible(true)
  }

  const handleClearConfirmOk = async () => {
    if (clearTarget) {
      await memory.handleClearMemory(clearTarget.key, clearTarget.title)
      setClearConfirmVisible(false)
      setClearTarget(null)
    }
  }

  const handleClearConfirmCancel = () => {
    setClearConfirmVisible(false)
    setClearTarget(null)
  }

  // ====================== UI 渲染函数 ======================
  const renderBaseSettings = () => {
    const shareOptionLabels: Record<"always" | "ask" | "never", string> = {
      always: t('memoryManageModal.shareOption.always'),
      ask: t('memoryManageModal.shareOption.ask'),
      never: t('memoryManageModal.shareOption.never'),
    }
    const dropdownItems = [
      { label: shareOptionLabels.always, key: "always" },
      { label: shareOptionLabels.ask, key: "ask" },
      { label: shareOptionLabels.never, key: "never" },
    ]

    const handleMenuClick = ({ key }: { key: string }) => {
      memory.setShareOption(key as "always" | "ask" | "never")
    }

    return (
      <div className="pt-4 pb-4 space-y-6 px-6 py-6">
        <div className="flex items-center justify-between">
          <span className="text-sm font-medium">{t('memoryManageModal.memoryAbility')}</span>
          <div className="flex inline-flex items-center gap-4">
            <Switch checked={memory.memoryEnabled} onChange={memory.setMemoryEnabled} />
          </div>
        </div>

        {memory.memoryEnabled && (
          <div className="flex items-center justify-between mb-10">
            <span className="text-sm font-medium">{t('memoryManageModal.agentMemoryShare')}</span>
            <Dropdown
              menu={{ items: dropdownItems, onClick: handleMenuClick, selectable: true, defaultSelectedKeys: [memory.shareOption] }}
              trigger={["click"]}
              placement="bottomRight"
            >
              <span className="flex items-center cursor-pointer select-none gap-4">
                <span>{shareOptionLabels[memory.shareOption]}</span>
                <DownOutlined className="mr-2" />
              </span>
            </Dropdown>
          </div>
        )}
      </div>
    )
  }

  // 渲染新增记忆输入框
  const renderAddMemoryInput = (groupKey: string) => {
    if (memory.addingMemoryKey !== groupKey) return null

    return (
      <List.Item className="border-b border-gray-100">
        <div className="flex items-center w-full gap-3 mb-4">
          <Input.TextArea
            value={memory.newMemoryContent}
            onChange={(e) => memory.setNewMemoryContent(e.target.value)}
            placeholder={t('memoryManageModal.inputPlaceholder')}
            maxLength={500}
            showCount
            onPressEnter={memory.confirmAddingMemory}
            disabled={memory.isAddingMemory}
            className="flex-1"
            autoSize={{ minRows: 2, maxRows: 5 }}
          />
          <Button
            type="primary"
            variant="outlined"
            size="small"
            shape="circle"
            color="red"
            className={memory.isAddingMemory ? "" : "hover:!bg-red-50"}
            icon={<X className={ "size-4" }/>}
            onClick={memory.cancelAddingMemory}
            disabled={memory.isAddingMemory}
            style={{border: "none", backgroundColor: "transparent", boxShadow: "none"}}
          />
          <Button
            type="primary"
            variant="outlined"
            size="small"
            shape="circle"
            color="green"
            className={!memory.newMemoryContent.trim() ? "" : "hover:!bg-green-50"}
            icon={<Check className={ "size-4" }/>}
            onClick={memory.confirmAddingMemory}
            loading={memory.isAddingMemory}
            disabled={!memory.newMemoryContent.trim()}
            style={{border: "none", backgroundColor: "transparent", boxShadow: "none"}}
          />
        </div>
      </List.Item>
    )
  }

  // 渲染空状态
  const renderEmptyState = (groupKey: string) => {
    const groups = memory.getGroupsForTab(memory.activeTabKey)
    const currentGroup = groups.find(g => g.key === groupKey)
    
    if (currentGroup && currentGroup.items.length === 0) {
      return (
        <div className="flex flex-col items-center justify-center py-8 text-gray-500">
          <MessageSquareDashed className="size-8 mb-2 opacity-50" />
          <p className="text-sm mb-4">{t('memoryManageModal.noMemory')}</p>
        </div>
      )
    }
    return null
  }

  const renderCollapseGroups = (
    groups: { title: string; key: string; items: any[] }[],
    showSwitch = false,
    tabKey?: string
  ) => {
    const paginated = tabKey === "agentShared" || tabKey === "userAgent"
    const currentPage = paginated ? memory.pageMap[tabKey!] || 1 : 1
    const startIdx = (currentPage - 1) * memory.pageSize
    const sliceGroups = paginated ? groups.slice(startIdx, startIdx + memory.pageSize) : groups

    // 若尚未加载到任何分组（如接口仍在请求中），直接渲染空状态，避免出现白屏
    if (sliceGroups.length === 0) {
      return (
        <div className="flex flex-col items-center justify-center py-8 text-gray-500">
          <MessageSquareDashed className="size-8 mb-2 opacity-50" />
          <p className="text-sm mb-4">{t('memoryManageModal.noMemory')}</p>
        </div>
      )
    }

    // 单分组场景，不可折叠（租户共享、用户个性化页签）
    const isFixedSingle = sliceGroups.length === 1 && (tabKey === "tenant" || tabKey === "userPersonal")

    if (isFixedSingle) {
      return (
        <div style={{ maxHeight: "70vh", overflow: "auto" }}>
          {sliceGroups.map((g) => (
            <div key={g.key} className="memory-modal-panel mb-2">
              <div className="flex items-center justify-between w-full text-base font-semibold px-4 py-3" style={{ cursor: "default" }}>
                <span>{g.title}</span>
                <div className="flex items-center gap-2 pr-4">
                  <Button
                    type="primary"
                    variant="outlined"
                    size="small"
                    shape="round"
                    color="green"
                    title={t('memoryManageModal.addMemory')}
                    onClick={() => memory.startAddingMemory(g.key)}
                    icon={<MessageSquarePlus className="size-4" />}
                    className="hover:!bg-green-50"
                    style={{ border: "none", backgroundColor: "transparent", boxShadow: "none" }}
                  />
                  <Button
                    type="primary"
                    variant="outlined"
                    size="small"
                    shape="round"
                    color="red"
                    title={t('memoryManageModal.clearMemory')}
                    onClick={() => !(/-placeholder$/.test(g.key)) && handleClearConfirm(g.key, g.title)}
                    icon={<MessageSquareOff className="size-4" />}
                    className="hover:!bg-red-50"
                    style={{ border: "none", backgroundColor: "transparent", boxShadow: "none", visibility: g.items.length > 0 ? "visible" : "hidden" }}
                    disabled={g.items.length === 0}
                  />
                </div>
              </div>
              {(g.items.length === 0 && memory.addingMemoryKey !== g.key) ? (
                <div className="flex flex-col items-center justify-center py-8 text-gray-500">
                  <MessageSquareDashed className="size-8 mb-2 opacity-50" />
                  <p className="text-sm mb-4">{t('memoryManageModal.noMemory')}</p>
                </div>
              ) : (
                <List
                  className="memory-modal-list"
                  dataSource={g.items}
                  style={{ maxHeight: "35vh", overflowY: "auto", scrollbarGutter: "stable" }}
                  size="small"
                  locale={{ emptyText: renderEmptyState(g.key) }}
                  renderItem={(item) => (
                    <List.Item
                      actions={[
                        <Button
                          key="delete"
                          type="text"
                          size="small"
                          title={t('memoryManageModal.deleteMemory')}
                          danger
                          style={{ background: "transparent" }}
                          icon={<Eraser className="size-4" />}                        onClick={() => memory.handleDeleteMemory(item.id, g.key)}
                        />,
                      ]}
                    >
                      <div className="flex flex-col text-sm pl-2">{item.memory}</div>
                    </List.Item>
                  )}
                >
                  {renderAddMemoryInput(g.key)}
                </List>
              )}
            </div>
          ))}
        </div>
      )
    }

    return (
      <>
        <Collapse
          accordion
          ghost
          expandIcon={({ isActive }) => <CaretRightOutlined rotate={isActive ? 90 : 0} />}
          activeKey={memory.openKey}
          onChange={(key) => {
            if (Array.isArray(key)) {
              memory.setOpenKey(key[0] as string)
            } else if (key) {
              memory.setOpenKey(key as string)
            }
          }}
          style={{ maxHeight: "70vh", overflow: "auto" }}
          items={sliceGroups.map((g) => {
            const isPlaceholder = /-placeholder$/.test(g.key)
            const disabled = !isPlaceholder && !!memory.disabledGroups[g.key]
            return {
              key: g.key,
              label: (
                <div
                  className="flex items-center justify-between w-full text-base font-semibold"
                  style={{ cursor: disabled ? "default" : "pointer" }}
                >
                  <span>{g.title}</span>
                  <div className="flex items-center gap-2 pr-4" onClick={(e) => e.stopPropagation()}>
                    {showSwitch && !isPlaceholder && (
                      <Switch
                        size="small"
                        className="mr-2"
                        checked={!disabled}
                        onChange={(val) => memory.toggleGroup(g.key, val)}
                      />
                    )}
                    {/* 如果分组无数据，则隐藏“清空记忆”按钮，保持界面简洁 */}
                    <Button
                      type="primary"
                      variant="outlined"
                      size="small"
                      shape="round"
                      color="green"
                      title={t('memoryManageModal.addMemory')}
                      onClick={(e) => {
                        e.stopPropagation()
                        memory.startAddingMemory(g.key)
                      }}
                      icon={<MessageSquarePlus className="size-4" />}
                      className={disabled ? "" : "hover:!bg-green-50"}
                      style={{ cursor: disabled ? "default" : "pointer", border: "none", backgroundColor: "transparent", boxShadow: "none" }}
                      disabled={disabled}
                    />
                    <Button
                      type="primary"
                      variant="outlined"
                      size="small"
                      shape="round"
                      color="red"
                      className={disabled ? "" : "hover:!bg-red-50"}
                      title={t('memoryManageModal.clearMemory')}
                      onClick={(e) => {
                        e.stopPropagation()
                        !(/-placeholder$/.test(g.key)) && handleClearConfirm(g.key, g.title)
                      }}
                      icon={<MessageSquareOff className="size-4" />}
                      style={{ cursor: disabled ? "default" : "pointer", border: "none", backgroundColor: "transparent", boxShadow: "none", visibility: g.items.length > 0 ? "visible" : "hidden" }}
                      disabled={disabled || g.items.length === 0}
                    />
                  </div>
                </div>
              ),
              collapsible: disabled ? "disabled" : undefined,
              children: (
                <List
                  className="memory-modal-list"
                  dataSource={g.items}
                  style={{ maxHeight: "35vh", overflowY: "auto", scrollbarGutter: "stable" }}
                  size="small"
                  locale={{ emptyText: renderEmptyState(g.key) }}
                  renderItem={(item) => (
                    <List.Item
                      actions={[
                        <Button
                          key="delete"
                          type="text"
                          size="small"
                          title={t('memoryManageModal.deleteMemory')}
                          danger
                          style={{ background: "transparent" }}
                          icon={<Eraser className="size-4" />}
                          disabled={disabled}
                          onClick={() => memory.handleDeleteMemory(item.id, g.key)}
                        />,
                      ]}
                    >
                      <div className="flex flex-col text-sm pl-2">{item.memory}</div>
                    </List.Item>
                  )}
                >
                  {renderAddMemoryInput(g.key)}
                </List>
              ),
              showArrow: true,
              className: "memory-modal-panel",
            }
          })}
        />
        {paginated && groups.length > memory.pageSize && (
          <div className="flex justify-center mt-2">
            <Pagination
              current={currentPage}
              pageSize={memory.pageSize}
              total={groups.length}
              onChange={(page) => memory.setPageMap((prev) => ({ ...prev, [tabKey!]: page }))}
              showSizeChanger={false}
            />
          </div>
        )}
      </>
    )
  }

  const labelWithIcon = (Icon: React.ElementType, text: string) => (
    <span className="inline-flex items-center gap-2">
      <Icon className="size-3" />
      {text}
    </span>
  )

  const tabItems = [
    {
      key: "base",
      label: labelWithIcon(Settings, t('memoryManageModal.baseSettings')),
      children: renderBaseSettings(),
    },
    ...(role === "admin"
      ? [
          {
            key: "tenant",
            label: labelWithIcon(UsersRound, t('memoryManageModal.tenantShareTab')),
            children: renderCollapseGroups([memory.tenantSharedGroup], false, "tenant"),
            disabled: !memory.memoryEnabled,
          },
          {
            key: "agentShared",
            label: labelWithIcon(Share2, t('memoryManageModal.agentShareTab')),
            children: renderCollapseGroups(memory.agentSharedGroups, true, "agentShared"),
            disabled: !memory.memoryEnabled || memory.shareOption === "never",
          },
        ]
      : []),
    {
      key: "userPersonal",
      label: labelWithIcon(UserRound, t('memoryManageModal.userPersonalTab')),
      children: renderCollapseGroups([memory.userPersonalGroup], false, "userPersonal"),
      disabled: !memory.memoryEnabled,
    },
    {
      key: "userAgent",
      label: labelWithIcon(Bot, t('memoryManageModal.userAgentTab')),
      children: renderCollapseGroups(memory.userAgentGroups, true, "userAgent"),
      disabled: !memory.memoryEnabled,
    },
  ]

  return (
    <>
      <Modal
        open={visible}
        title={t('memoryManageModal.title')}
        footer={null}
        onCancel={onClose}
        width={760}
        destroyOnClose
        styles={{ body: { maxHeight: "80vh", overflowY: "clip" } }}
      >
        <Tabs size="large" items={tabItems} activeKey={memory.activeTabKey} onChange={(key) => memory.setActiveTabKey(key)} />
      </Modal>

      {/* 清空记忆确认弹框 */}
      <MemoryDeleteModal
        visible={clearConfirmVisible}
        targetTitle={clearTarget?.title ?? ""}
        onOk={handleClearConfirmOk}
        onCancel={handleClearConfirmCancel}
      />
    </>
  )
}

export default MemoryManageModal

