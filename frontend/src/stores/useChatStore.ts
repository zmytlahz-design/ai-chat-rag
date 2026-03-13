import { create } from 'zustand'
import type { SourceDocument, Conversation, SSEDoneEvent } from '../api/chat'
import { chatApi } from '../api/chat'

// ==================== 类型定义 ====================

/**
 * 前端消息实体（区别于后端 ChatMessageData）
 *
 * 前端需要额外的字段：
 *   - localId: React key，保证 DOM 稳定，避免 map 用 index 导致的问题
 *   - isStreaming: 当前消息是否正在流式输出（显示打字动画）
 *   - sources: 引用来源（assistant 消息完成后赋值）
 *   - from_cache: 是否来自 Redis 缓存（用于展示缓存标识）
 */
export interface ChatMessage {
  localId: string           // 本地唯一 ID，用作 React key
  dbId?: number             // 后端数据库 ID（流结束后设置）
  role: 'user' | 'assistant'
  content: string
  sources?: SourceDocument[]
  from_cache?: boolean
  cache_level?: string
  isStreaming?: boolean      // 是否正在流式输出
  created_at: string
}

// ==================== State & Actions 类型 ====================

interface ChatState {
  /** 当前 KB 下的对话列表（侧边栏展示） */
  conversations: Conversation[]
  /** 当前选中的对话 ID（null = 未选择 / 新对话模式） */
  currentConversationId: number | null
  /** 当前对话的消息列表（聊天区展示） */
  messages: ChatMessage[]
  /** 是否正在流式请求中（禁止发送新消息） */
  isStreaming: boolean
  /** 是否正在加载历史消息 */
  isLoadingMessages: boolean
  /** 错误信息 */
  error: string | null
}

interface ChatActions {
  /** 加载某知识库下的对话列表 */
  fetchConversations: (kbId: number) => Promise<void>
  /** 选择对话（同时加载该对话的历史消息） */
  selectConversation: (id: number) => Promise<void>
  /** 新建对话（清空消息区，不发 API 请求，等发送第一条消息时自动创建） */
  newConversation: () => void
  /** 删除对话 */
  deleteConversation: (id: number, kbId: number) => Promise<void>
  /** 发送消息（流式）—— 核心方法 */
  sendMessage: (kbId: number, question: string) => Promise<void>
  /** 取消流式请求（目前通过 AbortController 实现，store 中只重置状态） */
  cancelStreaming: () => void
  /** 清除错误 */
  clearError: () => void
  /** 清空当前消息列表（切换 KB 时调用） */
  clearMessages: () => void
}

// ==================== 流式请求取消器（store 外部保存） ====================
// 用模块级变量保存 AbortController，避免放入 Zustand state 引发 proxy 问题
let streamAbortController: AbortController | null = null

// ==================== Store 实现 ====================

export const useChatStore = create<ChatState & ChatActions>((set, get) => ({
  // ---- 初始状态 ----
  conversations: [],
  currentConversationId: null,
  messages: [],
  isStreaming: false,
  isLoadingMessages: false,
  error: null,

  // ---- Actions ----

  /** 从后端拉取对话列表（切换知识库或刷新时调用） */
  fetchConversations: async (kbId: number) => {
    try {
      const result = await chatApi.listConversations(kbId)
      set({ conversations: result.items })
    } catch (err) {
      console.error('加载对话列表失败:', err)
    }
  },

  /** 点击对话历史记录：加载该对话的所有消息 */
  selectConversation: async (id: number) => {
    set({ currentConversationId: id, isLoadingMessages: true, messages: [] })
    try {
      const detail = await chatApi.getConversation(id)
      // 将后端消息格式转换为前端格式
      const messages: ChatMessage[] = detail.messages.map(m => ({
        localId: `db-${m.id}`,        // 前缀 db- 区分本地生成的消息
        dbId: m.id,
        role: m.role,
        content: m.content,
        created_at: m.created_at,
        isStreaming: false,
      }))
      set({ messages, isLoadingMessages: false })
    } catch (err) {
      set({ error: (err as Error).message, isLoadingMessages: false })
    }
  },

  /** 点击"新建对话"按钮：重置状态，等待用户发送第一条消息 */
  newConversation: () => {
    set({ currentConversationId: null, messages: [] })
  },

  /** 删除对话：调用 API 后从本地列表移除 */
  deleteConversation: async (id: number, kbId: number) => {
    await chatApi.deleteConversation(id)
    const { currentConversationId } = get()
    // 若删除的是当前对话，清空消息区
    if (currentConversationId === id) {
      set({ currentConversationId: null, messages: [] })
    }
    // 重新拉取对话列表
    await get().fetchConversations(kbId)
  },

  /**
   * sendMessage：发送消息并通过 SSE 接收流式回复。
   *
   * 流程：
   *   1. 立即把用户消息加入 messages（乐观更新，界面立即响应）
   *   2. 添加空的 assistant 占位消息（isStreaming=true，显示打字动画）
   *   3. 通过 fetch + ReadableStream 连接 /api/v1/chat/stream
   *   4. 收到 start 事件 → 更新 conversationId
   *   5. 收到 token 事件 → 追加 content 到占位消息
   *   6. 收到 done 事件 → 设置 sources、dbId，关闭流
   *   7. 收到 error 事件 → 显示错误信息
   */
  sendMessage: async (kbId: number, question: string) => {
    const { currentConversationId, isStreaming } = get()

    // 避免重复发送
    if (isStreaming) return

    // ---- 步骤1：乐观更新用户消息 ----
    const userMsg: ChatMessage = {
      localId: `local-user-${Date.now()}`,
      role: 'user',
      content: question,
      created_at: new Date().toISOString(),
    }

    // ---- 步骤2：添加 assistant 占位消息 ----
    const assistantLocalId = `local-assistant-${Date.now()}`
    const assistantPlaceholder: ChatMessage = {
      localId: assistantLocalId,
      role: 'assistant',
      content: '',
      isStreaming: true,
      created_at: new Date().toISOString(),
    }

    set(state => ({
      messages: [...state.messages, userMsg, assistantPlaceholder],
      isStreaming: true,
      error: null,
    }))

    // ---- 步骤3：建立 SSE 连接 ----
    streamAbortController = new AbortController()

    try {
      const response = await fetch('/api/v1/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          kb_id: kbId,
          question,
          conversation_id: currentConversationId ?? undefined,
        }),
        signal: streamAbortController.signal,
      })

      if (!response.ok || !response.body) {
        throw new Error(`HTTP ${response.status}`)
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder('utf-8')
      let buffer = ''

      // ---- 步骤4-7：逐块读取并解析 SSE 事件 ----
      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''

        for (const line of lines) {
          const trimmed = line.trim()
          if (!trimmed.startsWith('data: ')) continue

          const jsonStr = trimmed.slice(6)
          if (!jsonStr) continue

          try {
            const event = JSON.parse(jsonStr)

            switch (event.type) {
              // start：后端确认收到请求，返回 conversation_id
              case 'start':
                set({ currentConversationId: event.conversation_id })
                break

              // token：逐字追加到占位消息的 content
              case 'token':
                set(state => ({
                  messages: state.messages.map(m =>
                    m.localId === assistantLocalId
                      ? { ...m, content: m.content + event.content }
                      : m,
                  ),
                }))
                break

              // done：流结束，更新 sources 和 dbId，关闭 streaming 状态
              case 'done': {
                const doneEvent = event as SSEDoneEvent
                set(state => ({
                  messages: state.messages.map(m =>
                    m.localId === assistantLocalId
                      ? {
                          ...m,
                          isStreaming: false,
                          dbId: doneEvent.message_id ?? undefined,
                          sources: doneEvent.sources,
                          from_cache: doneEvent.from_cache,
                          cache_level: doneEvent.cache_level,
                        }
                      : m,
                  ),
                  isStreaming: false,
                }))
                // 刷新对话列表（标题可能已由后端自动生成）
                get().fetchConversations(kbId)
                break
              }

              // error：将错误信息写入占位消息的 content
              case 'error':
                set(state => ({
                  messages: state.messages.map(m =>
                    m.localId === assistantLocalId
                      ? { ...m, content: `❌ 请求失败：${event.message}`, isStreaming: false }
                      : m,
                  ),
                  isStreaming: false,
                }))
                break
            }
          } catch {
            // 忽略解析失败的行
          }
        }
      }
    } catch (err) {
      if (err instanceof Error && err.name === 'AbortError') {
        // 主动取消：更新消息状态
        set(state => ({
          messages: state.messages.map(m =>
            m.localId === assistantLocalId
              ? { ...m, isStreaming: false }
              : m,
          ),
          isStreaming: false,
        }))
        return
      }
      // 其他错误
      set(state => ({
        messages: state.messages.map(m =>
          m.localId === assistantLocalId
            ? { ...m, content: `❌ 网络错误：${(err as Error).message}`, isStreaming: false }
            : m,
        ),
        isStreaming: false,
        error: (err as Error).message,
      }))
    }
  },

  /** 取消当前流式请求 */
  cancelStreaming: () => {
    streamAbortController?.abort()
    set({ isStreaming: false })
  },

  /** 清空消息列表（切换 KB 时调用） */
  clearMessages: () => {
    set({ messages: [], currentConversationId: null, conversations: [] })
  },

  /** 清除错误 */
  clearError: () => set({ error: null }),
}))
