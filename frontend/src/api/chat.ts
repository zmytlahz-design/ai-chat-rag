import apiClient from './client'

// ==================== 类型定义 ====================

/** 引用来源文档片段 */
export interface SourceDocument {
  doc_id: number | null
  filename: string
  chunk_index: number
  content: string           // 片段原始文本（用于展示）
}

/** 对话历史中的单条消息（从后端加载时使用） */
export interface ChatMessageData {
  id: number
  conversation_id: number
  role: 'user' | 'assistant'
  content: string
  token_count: number | null
  created_at: string
}

/** 对话实体 */
export interface Conversation {
  id: number
  kb_id: number
  title: string
  created_at: string
  last_active_at: string
}

/** 对话详情（包含消息列表） */
export interface ConversationDetail extends Conversation {
  messages: ChatMessageData[]
}

/** 对话列表分页响应 */
export interface ConversationListResponse {
  total: number
  items: Conversation[]
}

/** 普通（非流式）对话请求体 */
export interface ChatNormalRequest {
  kb_id: number
  question: string
  conversation_id?: number
}

/** 普通对话响应体 */
export interface ChatNormalResponse {
  conversation_id: number
  message_id: number | null
  content: string
  sources: SourceDocument[]
  token_count: number | null
}

// ==================== SSE 事件类型（流式对话）====================
// 后端通过 SSE（Server-Sent Events）逐块推送以下格式的 JSON

/** 流开始事件：携带对话 ID */
export interface SSEStartEvent {
  type: 'start'
  conversation_id: number
}

/** Token 块事件：携带单个文字片段 */
export interface SSETokenEvent {
  type: 'token'
  content: string
}

/** 流结束事件：携带完整 sources 和消息 ID */
export interface SSEDoneEvent {
  type: 'done'
  conversation_id: number
  message_id: number | null
  sources: SourceDocument[]
}

/** 错误事件 */
export interface SSEErrorEvent {
  type: 'error'
  message: string
}

/** SSE 事件联合类型，供 useSSE Hook 使用 */
export type SSEEvent = SSEStartEvent | SSETokenEvent | SSEDoneEvent | SSEErrorEvent

// ==================== API 函数 ====================

const CHAT_BASE = '/api/v1/chat'
const CONV_BASE = '/api/v1/conversations'

export const chatApi = {
  /** 普通（非流式）对话 */
  normal(req: ChatNormalRequest): Promise<ChatNormalResponse> {
    return apiClient.post(`${CHAT_BASE}/normal`, req).then(r => r.data)
  },

  /** 获取某知识库下的对话列表（分页） */
  listConversations(kbId: number, skip = 0, limit = 50): Promise<ConversationListResponse> {
    return apiClient
      .get(CONV_BASE, { params: { kb_id: kbId, skip, limit } })
      .then(r => r.data)
  },

  /** 获取对话详情（含消息列表） */
  getConversation(convId: number): Promise<ConversationDetail> {
    return apiClient.get(`${CONV_BASE}/${convId}`).then(r => r.data)
  },

  /** 删除对话及其所有消息 */
  deleteConversation(convId: number): Promise<void> {
    return apiClient.delete(`${CONV_BASE}/${convId}`).then(() => undefined)
  },

  /** 更新对话标题 */
  updateConversationTitle(convId: number, title: string): Promise<Conversation> {
    return apiClient.put(`${CONV_BASE}/${convId}`, { title }).then(r => r.data)
  },
}
