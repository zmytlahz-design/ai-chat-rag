import { create } from 'zustand'
import type { KnowledgeBase, KnowledgeBaseCreateInput } from '../api/knowledge'
import { knowledgeApi } from '../api/knowledge'

// ==================== State 类型定义 ====================

interface KnowledgeState {
  /** 知识库列表 */
  knowledgeBases: KnowledgeBase[]
  /** 当前选中的知识库 ID（null = 未选择） */
  currentKbId: number | null
  /** 是否正在加载知识库列表 */
  isLoading: boolean
  /** 错误信息 */
  error: string | null
}

interface KnowledgeActions {
  /** 从后端加载知识库列表 */
  fetchKbs: () => Promise<void>
  /** 选择当前知识库（切换时清空对话） */
  selectKb: (id: number) => void
  /** 创建新知识库 */
  createKb: (data: KnowledgeBaseCreateInput) => Promise<KnowledgeBase>
  /** 更新知识库信息 */
  updateKb: (id: number, data: Partial<KnowledgeBaseCreateInput>) => Promise<KnowledgeBase>
  /** 删除知识库 */
  deleteKb: (id: number) => Promise<void>
  /** 清除错误信息 */
  clearError: () => void
}

// ==================== Store 实现 ====================

/**
 * useKnowledgeStore：管理知识库列表和当前选中知识库的全局状态。
 *
 * Zustand 特点：
 *   - 比 Redux 轻量，不需要 Provider/Reducer/Action
 *   - create() 返回一个 Hook，直接在组件中调用
 *   - set() 做浅合并（类似 setState），无需手动展开整个对象
 */
export const useKnowledgeStore = create<KnowledgeState & KnowledgeActions>((set, get) => ({
  // ---- 初始状态 ----
  knowledgeBases: [],
  currentKbId: null,
  isLoading: false,
  error: null,

  // ---- Actions ----

  /** 从后端拉取知识库列表，应用启动时或需要刷新时调用 */
  fetchKbs: async () => {
    set({ isLoading: true, error: null })
    try {
      const result = await knowledgeApi.list()
      const items = Array.isArray((result as { items?: unknown })?.items)
        ? ((result as { items: KnowledgeBase[] }).items)
        : []
      set({ knowledgeBases: items, isLoading: false })

      // 如果当前没有选中的知识库，且列表不为空，自动选中第一个
      const { currentKbId, knowledgeBases } = get()
      if (!currentKbId && knowledgeBases.length > 0) {
        set({ currentKbId: knowledgeBases[0].id })
      }
    } catch (err) {
      set({ error: (err as Error).message, isLoading: false })
    }
  },

  /** 切换当前知识库 */
  selectKb: (id: number) => {
    set({ currentKbId: id })
  },

  /** 创建知识库：调用 API 后将新记录追加到列表 */
  createKb: async (data: KnowledgeBaseCreateInput) => {
    const newKb = await knowledgeApi.create(data)
    set(state => ({
      knowledgeBases: [...(Array.isArray(state.knowledgeBases) ? state.knowledgeBases : []), newKb],
      currentKbId: newKb.id, // 创建后自动切换到新知识库
    }))
    return newKb
  },

  /** 更新知识库：替换列表中对应的记录 */
  updateKb: async (id: number, data: Partial<KnowledgeBaseCreateInput>) => {
    const updated = await knowledgeApi.update(id, data)
    set(state => ({
      knowledgeBases: (Array.isArray(state.knowledgeBases) ? state.knowledgeBases : []).map(kb =>
        kb.id === id ? updated : kb,
      ),
    }))
    return updated
  },

  /** 删除知识库：从列表中移除，并在必要时切换当前 KB */
  deleteKb: async (id: number) => {
    await knowledgeApi.delete(id)
    set(state => {
      const currentList = Array.isArray(state.knowledgeBases) ? state.knowledgeBases : []
      const remaining = currentList.filter(kb => kb.id !== id)
      return {
        knowledgeBases: remaining,
        // 若删除的是当前选中的 KB，切换到列表第一个（或 null）
        currentKbId:
          state.currentKbId === id
            ? (remaining[0]?.id ?? null)
            : state.currentKbId,
      }
    })
  },

  /** 清除错误信息 */
  clearError: () => set({ error: null }),
}))
