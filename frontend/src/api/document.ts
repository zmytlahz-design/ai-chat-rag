import apiClient from './client'

// ==================== 类型定义 ====================

/** 文档处理状态枚举 */
export type DocumentStatus = 'pending' | 'processing' | 'completed' | 'failed'

/** 文档实体，对应后端 Document ORM 模型 */
export interface Document {
  id: number
  kb_id: number
  filename: string
  file_type: string | null
  file_size: number | null   // 字节数
  chunk_count: number
  status: DocumentStatus
  error_message: string | null
  created_at: string
  updated_at: string
}

/** 文档列表分页响应 */
export interface DocumentListResponse {
  total: number
  items: Document[]
}

// ==================== API 函数 ====================

const BASE = '/api/v1/documents'

export const documentApi = {
  /**
   * 上传文档到知识库
   * @param kbId 目标知识库 ID
   * @param file 要上传的文件对象
   * @param onProgress 上传进度回调 (0-100)
   */
  upload(
    kbId: number,
    file: File,
    onProgress?: (percent: number) => void,
  ): Promise<Document> {
    // 使用 FormData 传递文件 + kb_id（multipart/form-data）
    const form = new FormData()
    form.append('kb_id', String(kbId))
    form.append('file', file)

    return apiClient
      .post(`${BASE}/upload`, form, {
        headers: { 'Content-Type': 'multipart/form-data' },
        // axios onUploadProgress 回调，实时获取上传字节数
        onUploadProgress: (event) => {
          if (onProgress && event.total) {
            onProgress(Math.round((event.loaded / event.total) * 100))
          }
        },
      })
      .then(r => r.data)
  },

  /** 获取知识库下的所有文档（分页） */
  list(kbId: number, skip = 0, limit = 50): Promise<DocumentListResponse> {
    return apiClient.get(`${BASE}/kb/${kbId}`, { params: { skip, limit } }).then(r => r.data)
  },

  /** 查询单个文档详情（可用于轮询处理状态） */
  get(docId: number): Promise<Document> {
    return apiClient.get(`${BASE}/${docId}`).then(r => r.data)
  },

  /** 删除文档及其向量数据 */
  delete(docId: number): Promise<void> {
    return apiClient.delete(`${BASE}/${docId}`).then(() => undefined)
  },
}
