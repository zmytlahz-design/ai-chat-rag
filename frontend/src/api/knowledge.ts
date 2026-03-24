import apiClient from './client'

// ==================== 类型定义 ====================

/** 知识库实体，对应后端 KnowledgeBase ORM 模型 */
export interface KnowledgeBase {
  id: number
  name: string
  description: string | null
  created_at: string
  updated_at: string
}

/** 知识库列表分页响应 */
export interface KnowledgeBaseListResponse {
  total: number
  items: KnowledgeBase[]
}

/** 创建/更新知识库请求体 */
export interface KnowledgeBaseCreateInput {
  name: string
  description?: string
}

// ==================== API 函数 ====================

const BASE = '/api/v1/knowledge-bases'

export const knowledgeApi = {
  /** 获取知识库列表（分页） */
  list(skip = 0, limit = 50): Promise<KnowledgeBaseListResponse> {
    return apiClient.get(BASE, { params: { skip, limit } }).then(r => r.data)
  },

  /** 获取单个知识库详情 */
  get(id: number): Promise<KnowledgeBase> {
    return apiClient.get(`${BASE}/${id}`).then(r => r.data)
  },

  /** 创建知识库 */
  create(data: KnowledgeBaseCreateInput): Promise<KnowledgeBase> {
    return apiClient.post(BASE, data).then(r => r.data)
  },

  /** 更新知识库（部分更新） */
  update(id: number, data: Partial<KnowledgeBaseCreateInput>): Promise<KnowledgeBase> {
    return apiClient.put(`${BASE}/${id}`, data).then(r => r.data)
  },

  /** 删除知识库（同时删除其下所有文档和对话） */
  delete(id: number): Promise<void> {
    return apiClient.delete(`${BASE}/${id}`).then(() => undefined)
  },
}
