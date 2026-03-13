import { useEffect, useState, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { DocumentUpload } from '../components/DocumentUpload'
import { documentApi, type Document } from '../api/document'
import { knowledgeApi, type KnowledgeBase } from '../api/knowledge'

/**
 * DocumentManage：文档管理页面。
 *
 * 路由参数：kbId（知识库 ID）
 *
 * 功能：
 *   - 展示知识库下的所有文档列表
 *   - 文档状态显示（pending / processing / completed / failed）
 *   - 上传新文档（集成 DocumentUpload 组件）
 *   - 删除文档（含向量数据）
 *   - 文档状态轮询（页面可见时每 5 秒刷新一次）
 */
export default function DocumentManage() {
  const { kbId: kbIdStr } = useParams<{ kbId: string }>()
  const kbId = Number(kbIdStr)
  const navigate = useNavigate()

  const [kb, setKb] = useState<KnowledgeBase | null>(null)
  const [documents, setDocuments] = useState<Document[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  // 是否显示上传区域
  const [showUpload, setShowUpload] = useState(false)

  /** 加载知识库信息和文档列表 */
  const loadData = useCallback(async () => {
    if (!kbId) return
    try {
      const [kbData, docData] = await Promise.all([
        knowledgeApi.get(kbId),
        documentApi.list(kbId, 0, 100),
      ])
      setKb(kbData)
      setDocuments(docData.items)
      setError(null)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setIsLoading(false)
    }
  }, [kbId])

  // 初始化加载
  useEffect(() => {
    loadData()
  }, [loadData])

  // 定期刷新（每 5 秒）：用于更新处理中文档的状态
  // 只有当存在 pending/processing 状态的文档时才轮询
  useEffect(() => {
    const hasProcessing = documents.some(
      d => d.status === 'pending' || d.status === 'processing',
    )
    if (!hasProcessing) return

    const timer = setInterval(loadData, 5000)
    return () => clearInterval(timer)
  }, [documents, loadData])

  /** 删除文档 */
  const handleDelete = async (doc: Document) => {
    if (!confirm(`确认删除文档「${doc.filename}」？\n同时会删除该文档的所有向量数据，不可恢复。`)) return
    try {
      await documentApi.delete(doc.id)
      setDocuments(prev => prev.filter(d => d.id !== doc.id))
    } catch (err) {
      alert(`删除失败：${(err as Error).message}`)
    }
  }

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="w-8 h-8 border-4 border-blue-500 border-t-transparent rounded-full animate-spin" />
      </div>
    )
  }

  if (error || !kb) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center">
          <p className="text-red-500 mb-4">{error || '知识库不存在'}</p>
          <button onClick={() => navigate('/knowledge-base')} className="text-blue-600 hover:underline text-sm">
            返回知识库列表
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gray-50">
      {/* 顶部导航栏 */}
      <header className="bg-white border-b border-gray-200 px-6 py-4">
        <div className="max-w-4xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            <button
              onClick={() => navigate('/knowledge-base')}
              className="text-gray-400 hover:text-gray-600 transition-colors"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
              </svg>
            </button>
            <div>
              <h1 className="text-lg font-semibold text-gray-900">{kb.name}</h1>
              <p className="text-xs text-gray-500">文档管理</p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {/* 跳转对话 */}
            <button
              onClick={() => navigate('/')}
              className="flex items-center gap-1.5 text-sm text-gray-600 hover:text-gray-900 px-3 py-2 rounded-lg hover:bg-gray-100 transition-colors"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
              </svg>
              开始对话
            </button>
            {/* 上传文档 */}
            <button
              onClick={() => setShowUpload(!showUpload)}
              className="flex items-center gap-1.5 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
              </svg>
              上传文档
            </button>
          </div>
        </div>
      </header>

      {/* 主内容 */}
      <main className="max-w-4xl mx-auto px-6 py-6 space-y-6">
        {/* 上传区域（可折叠） */}
        {showUpload && (
          <div className="bg-white border border-gray-200 rounded-xl p-6">
            <h2 className="text-sm font-semibold text-gray-800 mb-4">上传新文档</h2>
            <DocumentUpload
              kbId={kbId}
              onUploadComplete={() => {
                loadData()
                // 上传完成后不自动收起，方便用户继续上传
              }}
            />
          </div>
        )}

        {/* 统计卡片 */}
        <div className="grid grid-cols-4 gap-3">
          <StatCard label="全部" value={documents.length} color="text-gray-700" />
          <StatCard
            label="已完成"
            value={documents.filter(d => d.status === 'completed').length}
            color="text-green-600"
          />
          <StatCard
            label="处理中"
            value={documents.filter(d => d.status === 'processing' || d.status === 'pending').length}
            color="text-yellow-600"
          />
          <StatCard
            label="失败"
            value={documents.filter(d => d.status === 'failed').length}
            color="text-red-600"
          />
        </div>

        {/* 文档列表 */}
        <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-gray-800">
              文档列表 ({documents.length})
            </h2>
            <button
              onClick={loadData}
              className="text-xs text-gray-500 hover:text-gray-700 flex items-center gap-1"
            >
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
              </svg>
              刷新
            </button>
          </div>

          {documents.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16">
              <svg className="w-12 h-12 text-gray-300 mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                  d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
              <p className="text-sm text-gray-500">暂无文档，点击"上传文档"开始</p>
            </div>
          ) : (
            <div className="divide-y divide-gray-100">
              {documents.map(doc => (
                <DocumentRow key={doc.id} doc={doc} onDelete={handleDelete} />
              ))}
            </div>
          )}
        </div>
      </main>
    </div>
  )
}

// ==================== 子组件 ====================

/** 统计卡片 */
function StatCard({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div className="bg-white border border-gray-200 rounded-xl px-4 py-3 text-center">
      <p className={`text-2xl font-bold ${color}`}>{value}</p>
      <p className="text-xs text-gray-500 mt-0.5">{label}</p>
    </div>
  )
}

/** 文档行 */
function DocumentRow({ doc, onDelete }: { doc: Document; onDelete: (doc: Document) => void }) {
  const statusConfig = {
    pending:    { label: '等待处理', bg: 'bg-gray-100',   text: 'text-gray-600' },
    processing: { label: '向量化中', bg: 'bg-yellow-100', text: 'text-yellow-700' },
    completed:  { label: '已完成',   bg: 'bg-green-100',  text: 'text-green-700' },
    failed:     { label: '处理失败', bg: 'bg-red-100',    text: 'text-red-700'   },
  }

  const { label, bg, text } = statusConfig[doc.status]

  return (
    <div className="flex items-center gap-4 px-5 py-4 hover:bg-gray-50 transition-colors">
      {/* 文件图标 */}
      <div className="w-9 h-9 rounded-lg bg-gray-100 flex items-center justify-center flex-shrink-0">
        <svg className="w-5 h-5 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
            d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
        </svg>
      </div>

      {/* 文件名和元信息 */}
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-gray-800 truncate">{doc.filename}</p>
        <div className="flex items-center gap-3 mt-0.5">
          <span className="text-xs text-gray-400">
            {doc.file_size ? formatFileSize(doc.file_size) : '—'}
          </span>
          {doc.chunk_count > 0 && (
            <span className="text-xs text-gray-400">{doc.chunk_count} 个片段</span>
          )}
          <span className="text-xs text-gray-400">
            {new Date(doc.created_at).toLocaleString('zh-CN', {
              month: 'numeric',
              day: 'numeric',
              hour: '2-digit',
              minute: '2-digit',
            })}
          </span>
        </div>
        {/* 错误信息 */}
        {doc.status === 'failed' && doc.error_message && (
          <p className="text-xs text-red-500 mt-1 truncate">{doc.error_message}</p>
        )}
      </div>

      {/* 状态徽章 */}
      <span className={`text-xs px-2.5 py-1 rounded-full font-medium ${bg} ${text} flex-shrink-0`}>
        {label}
        {doc.status === 'processing' && (
          <span className="ml-1 inline-block w-1.5 h-1.5 bg-yellow-500 rounded-full animate-pulse" />
        )}
      </span>

      {/* 删除按钮 */}
      <button
        onClick={() => onDelete(doc)}
        title="删除文档"
        className="text-gray-400 hover:text-red-500 transition-colors flex-shrink-0"
      >
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
            d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
        </svg>
      </button>
    </div>
  )
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}
