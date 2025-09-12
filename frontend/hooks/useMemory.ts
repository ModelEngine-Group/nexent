import { useState, useEffect, useCallback, useRef } from "react"
import { useTranslation } from "react-i18next"

import {
  loadMemoryConfig,
  setMemorySwitch,
  setMemoryAgentShare,
  fetchTenantSharedGroup,
  fetchAgentSharedGroups,
  fetchUserPersonalGroup,
  fetchUserAgentGroups,
  addDisabledAgentId,
  removeDisabledAgentId,
  addDisabledUserAgentId,
  removeDisabledUserAgentId,
  addMemory,
  clearMemory,
  deleteMemory,
} from "@/services/memoryService"

import { pageSize, MemoryGroup, UseMemoryOptions } from "@/types/memory"
import log from "@/lib/logger";

export function useMemory({ visible, currentUserId, currentTenantId, message }: UseMemoryOptions) {
  const { t } = useTranslation()
  /* ----------------------- Basic Settings State ----------------------- */
  const [memoryEnabled, setMemoryEnabledState] = useState<boolean>(true)
  const [shareOption, setShareOptionState] = useState<"always" | "ask" | "never">("always")

  /* ------------------------- Original Logic State ------------------------- */
  // Group disabled state (only effective for Agent shared, user Agent tabs)
  const [disabledGroups, setDisabledGroups] = useState<Record<string, boolean>>({})

  const disableAgentIdSet = useRef<Set<string>>(new Set())
  const disableUserAgentIdSet = useRef<Set<string>>(new Set())

  const [openKey, setOpenKey] = useState<string>()

  // Currently active Tab
  const [activeTabKey, setActiveTabKey] = useState<string>("base")

  // Pagination state
  const [pageMap, setPageMap] = useState<Record<string, number>>({ agentShared: 1, userAgent: 1 })

  /* ------------------------------ Data Groups ------------------------------ */
  const [tenantSharedGroup, setTenantSharedGroup] = useState<MemoryGroup>({ title: "", key: "tenant", items: [] })
  const [agentSharedGroups, setAgentSharedGroups] = useState<MemoryGroup[]>([])
  const [userPersonalGroup, setUserPersonalGroup] = useState<MemoryGroup>({ title: "", key: "user-personal", items: [] })
  const [userAgentGroups, setUserAgentGroups] = useState<MemoryGroup[]>([])

  /* ------------------------------ New Memory State ------------------------------ */
  const [addingMemoryKey, setAddingMemoryKey] = useState<string | null>(null)
  const [newMemoryContent, setNewMemoryContent] = useState<string>("")
  const [isAddingMemory, setIsAddingMemory] = useState<boolean>(false)

  /* --------------------------- Initialization Loading --------------------------- */
  useEffect(() => {
    if (!visible) return

    // 1. Load configuration
    loadMemoryConfig().then((cfg) => {
      setMemoryEnabledState(cfg.memoryEnabled)
      setShareOptionState(cfg.shareOption)
      disableAgentIdSet.current = new Set(cfg.disableAgentIds)
      disableUserAgentIdSet.current = new Set(cfg.disableUserAgentIds)
    }).catch((e) => {
      log.error("Failed to load memory config:", e)
      message.error(t('useMemory.loadConfigError'))
    })
  }, [visible, message])

  /* --------------------------- Load Group Data --------------------------- */
  useEffect(() => {
    if (!visible || !memoryEnabled) return

    const loadGroupsForActiveTab = async () => {
      try {
        if (activeTabKey === "tenant") {
          const tenantGrp = await fetchTenantSharedGroup()
          setTenantSharedGroup(tenantGrp)
        } else if (activeTabKey === "agentShared") {
          const agentGrps = await fetchAgentSharedGroups()
          setAgentSharedGroups(agentGrps)

          // Sync disabled state
          const newDisabled: Record<string, boolean> = {}
          agentGrps.forEach((g) => {
            const id = g.key.replace(/^agent-/, "")
            if (disableAgentIdSet.current.has(id)) newDisabled[g.key] = true
          })
          setDisabledGroups((prev) => ({ ...prev, ...newDisabled }))
        } else if (activeTabKey === "userPersonal") {
          const userGrp = await fetchUserPersonalGroup()
          setUserPersonalGroup(userGrp)
        } else if (activeTabKey === "userAgent") {
          const userAgentGrps = await fetchUserAgentGroups()
          setUserAgentGroups(userAgentGrps)

          // Sync disabled state
          const newDisabled: Record<string, boolean> = {}
          userAgentGrps.forEach((g) => {
            const id = g.key.replace(/^user-agent-/, "")
            if (disableUserAgentIdSet.current.has(id)) newDisabled[g.key] = true
          })
          setDisabledGroups((prev) => ({ ...prev, ...newDisabled }))
        }
      } catch (e) {
        log.error("load groups error", e)
        const errorMessage = e instanceof Error ? e.message : "Failed to load memory data"
        if (errorMessage.includes("Authentication") || errorMessage.includes("ElasticSearch") || errorMessage.includes("connection")) {
          message.error(t('useMemory.memoryServiceConnectionError'))
        } else {
          message.error(t('useMemory.loadDataError'))
        }
      }
    }

    loadGroupsForActiveTab()
  }, [visible, memoryEnabled, activeTabKey, currentTenantId, currentUserId])

  /* --------------------------- Utility Methods --------------------------- */
  const toggleGroup = useCallback((key: string, enabled: boolean) => {
    setDisabledGroups((prev) => ({ ...prev, [key]: !enabled }))

    const isAgentGroup = key.startsWith("agent-")
    const isUserAgentGroup = key.startsWith("user-agent-")
    const agentId = key.split("-").slice(-1)[0]

    if (!enabled) {
      // Disable -> Add to disabled list
      if (isAgentGroup) {
        addDisabledAgentId(agentId)
        disableAgentIdSet.current.add(agentId)
      } else if (isUserAgentGroup) {
        addDisabledUserAgentId(agentId)
        disableUserAgentIdSet.current.add(agentId)
      }
    } else {
      // Enable -> Remove from disabled list
      if (isAgentGroup) {
        removeDisabledAgentId(agentId)
        disableAgentIdSet.current.delete(agentId)
      } else if (isUserAgentGroup) {
        removeDisabledUserAgentId(agentId)
        disableUserAgentIdSet.current.delete(agentId)
      }
    }

    // Collapse panel when disabled
    if (!enabled) {
      setOpenKey((prev) => (prev === key ? undefined : prev))
    }
  }, [])

  const getGroupsForTab = (tabKey: string): MemoryGroup[] => {
    switch (tabKey) {
      case "tenant":
        return [tenantSharedGroup]
      case "agentShared":
        return agentSharedGroups
      case "userPersonal":
        return [userPersonalGroup]
      case "userAgent":
        return userAgentGroups
      default:
        return []
    }
  }

  /**
   * Compute memoryLevel and agentId according to current tab & group key.
   * Abstracted to avoid duplication.
   */
  const _computeMemoryParams = (tabKey: string, key: string): { memoryLevel: string; agentId?: string } => {
    switch (tabKey) {
      case "tenant":
        return { memoryLevel: "tenant" }
      case "agentShared":
        return { memoryLevel: "agent", agentId: key.replace(/^agent-/, "") }
      case "userPersonal":
        return { memoryLevel: "user" }
      case "userAgent":
        return { memoryLevel: "user_agent", agentId: key.replace(/^user-agent-/, "") }
      default:
        return { memoryLevel: "" }
    }
  }

  // Delay utility: Wait for backend index refresh before refetching data
  const delay = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms))

  /* ------------------------------ New Memory Related Methods ------------------------------ */
  const startAddingMemory = useCallback((groupKey: string) => {
    setAddingMemoryKey(groupKey)
    setNewMemoryContent("")
    setOpenKey(groupKey) // Ensure group is expanded
  }, [])

  const cancelAddingMemory = useCallback(() => {
    setAddingMemoryKey(null)
    setNewMemoryContent("")
  }, [])

  const confirmAddingMemory = useCallback(async () => {
    if (!addingMemoryKey || !newMemoryContent.trim()) return

    setIsAddingMemory(true)
    try {
      // Determine memory_level and agent_id based on current tab and group
      let memoryLevel = ""
      let agentId: string | undefined

      if (activeTabKey === "tenant") {
        memoryLevel = "tenant"
      } else if (activeTabKey === "agentShared") {
        memoryLevel = "agent"
        agentId = addingMemoryKey.replace(/^agent-/, "")
      } else if (activeTabKey === "userPersonal") {
        memoryLevel = "user"
      } else if (activeTabKey === "userAgent") {
        memoryLevel = "user_agent"
        agentId = addingMemoryKey.replace(/^user-agent-/, "")
      }

      const messages = [{ role: "user", content: newMemoryContent.trim() }]
      // Frontend manually triggers infer=False to avoid calling LLM
      await addMemory(messages, memoryLevel, agentId, false)

      await delay(600);
      message.success(t('useMemory.addMemorySuccess'))
      cancelAddingMemory()

      // Reload current tab data
      const loadGroupsForActiveTab = async () => {
        try {
          if (activeTabKey === "tenant") {
            const tenantGrp = await fetchTenantSharedGroup()
            setTenantSharedGroup(tenantGrp)
          } else if (activeTabKey === "agentShared") {
            const agentGrps = await fetchAgentSharedGroups()
            setAgentSharedGroups(agentGrps)
          } else if (activeTabKey === "userPersonal") {
            const userGrp = await fetchUserPersonalGroup()
            setUserPersonalGroup(userGrp)
          } else if (activeTabKey === "userAgent") {
            const userAgentGrps = await fetchUserAgentGroups()
            setUserAgentGroups(userAgentGrps)
          }
        } catch (e) {
          log.error("Reload groups error:", e)
        }
      }
      await loadGroupsForActiveTab()
    } catch (e) {
      log.error("Add memory error:", e)
      const errorMessage = e instanceof Error ? e.message : "Failed to add memory"
      if (errorMessage.includes("Authentication") || errorMessage.includes("ElasticSearch")) {
        message.error(t('useMemory.memoryServiceConnectionError'))
      } else {
        message.error(t('useMemory.addMemoryError'))
      }
    } finally {
      setIsAddingMemory(false)
    }
  }, [addingMemoryKey, newMemoryContent, activeTabKey, currentTenantId, currentUserId])

  /* ------------------------------ Clear Memory Related Methods ------------------------------ */
  const handleClearMemory = useCallback(async (groupKey: string, groupTitle: string) => {
    try {
      const { memoryLevel, agentId } = _computeMemoryParams(activeTabKey, groupKey)
      const result = await clearMemory(memoryLevel, agentId)
      await delay(300);
      message.success(t('useMemory.clearMemorySuccess', { groupTitle, count: result.deleted_count }))

      // Reload current tab data
      const loadGroupsForActiveTab = async () => {
        try {
          if (activeTabKey === "tenant") {
            const tenantGrp = await fetchTenantSharedGroup()
            setTenantSharedGroup(tenantGrp)
          } else if (activeTabKey === "agentShared") {
            const agentGrps = await fetchAgentSharedGroups()
            setAgentSharedGroups(agentGrps)
          } else if (activeTabKey === "userPersonal") {
            const userGrp = await fetchUserPersonalGroup()
            setUserPersonalGroup(userGrp)
          } else if (activeTabKey === "userAgent") {
            const userAgentGrps = await fetchUserAgentGroups()
            setUserAgentGroups(userAgentGrps)
          }
        } catch (e) {
          log.error("Reload groups error:", e)
        }
      }

      await loadGroupsForActiveTab()
    } catch (e) {
      log.error("Clear memory error:", e)
      const errorMessage = e instanceof Error ? e.message : "Failed to clear memory"
      if (errorMessage.includes("Authentication") || errorMessage.includes("ElasticSearch")) {
        message.error(t('useMemory.memoryServiceConnectionError'))
      } else {
        message.error(t('useMemory.clearMemoryError'))
      }
    }
  }, [activeTabKey, currentTenantId, currentUserId])

  /* ------------------- Delete Memory With Optimistic Update ------------------- */
  const handleDeleteMemory = useCallback(async (memoryId: string, groupKey: string) => {
    const { memoryLevel, agentId } = _computeMemoryParams(activeTabKey, groupKey)

    // Local optimistic removal
    const { removedItem, removedIndex } = _optimisticRemoveItem(memoryId, groupKey)

    // Call the backend to delete, if failed, rollback
    try {
      await deleteMemory(memoryId, memoryLevel, agentId)
      message.success(t('useMemory.deleteMemorySuccess'))
    } catch (e) {
      _rollbackRemoveItem(removedItem, removedIndex, groupKey)

      log.error("Delete memory error:", e)
      const errorMessage = e instanceof Error ? e.message : "memory delete failed"
      if (errorMessage.includes("Authentication") || errorMessage.includes("ElasticSearch")) {
        message.error(t('useMemory.memoryServiceConnectionError'))
      } else {
        message.error(t('useMemory.deleteMemoryError'))
      }
    }
  }, [activeTabKey, currentTenantId, currentUserId])

  /* ---------------------- Expand first group when tab switches ---------------------- */
  useEffect(() => {
    const groups = getGroupsForTab(activeTabKey).filter((g) => !disabledGroups[g.key])
    setOpenKey(groups.length ? groups[0].key : undefined)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTabKey, disabledGroups])

  /* ----------------- Expand first group of current tab when modal first opens ---------------- */
  useEffect(() => {
    if (visible) {
      const groups = getGroupsForTab(activeTabKey).filter((g) => !disabledGroups[g.key])
      setOpenKey(groups.length ? groups[0].key : undefined)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible, disabledGroups])

  /* ----------------- Handle when memoryEnabled or shareOption changes ---------------- */
  useEffect(() => {
    if (!memoryEnabled && activeTabKey !== "base") {
      setActiveTabKey("base")
    }
  }, [memoryEnabled])

  useEffect(() => {
    if (shareOption === "never" && activeTabKey === "agentShared") {
      setActiveTabKey("base")
    }
  }, [shareOption])

  // ----------------- Keep openKey valid after pagination switch -----------------
  useEffect(() => {
    if (activeTabKey === "agentShared" || activeTabKey === "userAgent") {
      const groups = getGroupsForTab(activeTabKey).filter((g) => !disabledGroups[g.key])
      const currentPage = pageMap[activeTabKey] || 1
      const startIdx = (currentPage - 1) * pageSize
      const visibleGroups = groups.slice(startIdx, startIdx + pageSize)
      if (visibleGroups.length && !visibleGroups.some((g) => g.key === openKey)) {
        setOpenKey(visibleGroups[0].key)
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTabKey, pageMap])

  /* ------------------- Wrapped setters ------------------- */
  const setMemoryEnabled = useCallback((enabled: boolean) => {
    setMemoryEnabledState(enabled)
    setMemorySwitch(enabled).catch((e) => {
      log.error("setMemorySwitch error:", e)
      message.error(t('useMemory.setMemorySwitchError'))
    })
  }, [])

  const setShareOption = useCallback((option: "always" | "ask" | "never") => {
    setShareOptionState(option)
    setMemoryAgentShare(option).catch((e) => {
      log.error("setMemoryAgentShare error:", e)
      message.error(t('useMemory.setMemoryShareOptionError'))
    })
  }, [message])

  /**
   * Optimistically remove a memory item from local state.
   * Returns the removed item and its index for rollback.
   */
  const _optimisticRemoveItem = (
    id: string,
    groupKey: string,
  ): { removedItem?: any; removedIndex: number } => {
    let removedItem: any | undefined
    let removedIndex = -1

    const process = (items: any[]): any[] => {
      const idx = items.findIndex((it: any) => it.id === id)
      if (idx !== -1) {
        removedItem = items[idx]
        removedIndex = idx
        return items.filter((it: any) => it.id !== id)
      }
      return items
    }

    if (activeTabKey === "tenant") {
      setTenantSharedGroup((prev) => ({ ...prev, items: process(prev.items) }))
    } else if (activeTabKey === "agentShared") {
      setAgentSharedGroups((prev) => prev.map((g) => (g.key === groupKey ? { ...g, items: process(g.items) } : g)))
    } else if (activeTabKey === "userPersonal") {
      setUserPersonalGroup((prev) => ({ ...prev, items: process(prev.items) }))
    } else if (activeTabKey === "userAgent") {
      setUserAgentGroups((prev) => prev.map((g) => (g.key === groupKey ? { ...g, items: process(g.items) } : g)))
    }

    return { removedItem, removedIndex }
  }

  /**
   * Rollback by re-inserting item at original index when optimistic update fails.
   */
  const _rollbackRemoveItem = (
    item: any,
    index: number,
    groupKey: string,
  ) => {
    if (!item || index < 0) return

    const insert = (items: any[]): any[] => {
      return [...items.slice(0, index), item, ...items.slice(index)]
    }

    if (activeTabKey === "tenant") {
      setTenantSharedGroup((prev) => ({ ...prev, items: insert(prev.items) }))
    } else if (activeTabKey === "agentShared") {
      setAgentSharedGroups((prev) => prev.map((g) => (g.key === groupKey ? { ...g, items: insert(g.items) } : g)))
    } else if (activeTabKey === "userPersonal") {
      setUserPersonalGroup((prev) => ({ ...prev, items: insert(prev.items) }))
    } else if (activeTabKey === "userAgent") {
      setUserAgentGroups((prev) => prev.map((g) => (g.key === groupKey ? { ...g, items: insert(g.items) } : g)))
    }
  }

  return {
    // state & setter
    memoryEnabled,
    setMemoryEnabled,
    shareOption,
    setShareOption,
    disabledGroups,
    toggleGroup,
    openKey,
    setOpenKey,
    activeTabKey,
    setActiveTabKey,
    pageMap,
    setPageMap,
    // computed
    tenantSharedGroup,
    agentSharedGroups,
    userPersonalGroup,
    userAgentGroups,
    pageSize,
    getGroupsForTab,
    // New memory related
    addingMemoryKey,
    newMemoryContent,
    setNewMemoryContent,
    isAddingMemory,
    startAddingMemory,
    cancelAddingMemory,
    confirmAddingMemory,
    // Clear memory related
    handleClearMemory,
    // Delete memory related
    handleDeleteMemory,
  }
}

// expose memory notification indicator to ChatHeader
export function useMemoryIndicator(modalVisible: boolean) {
  const [hasNewMemory, setHasNewMemory] = useState(false)

  // Reset indicator when memory modal is opened
  useEffect(() => {
    if (modalVisible) {
      setHasNewMemory(false)
    }
  }, [modalVisible])

  // Listen for backend event that notifies new memory addition
  useEffect(() => {
    const handler = () => setHasNewMemory(true)
    window.addEventListener("nexent:new-memory", handler as EventListener)
    return () => window.removeEventListener("nexent:new-memory", handler as EventListener)
  }, [])

  return hasNewMemory
}