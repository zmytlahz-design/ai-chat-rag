import { useState } from 'react'
import type { SourceDocument } from '../api/chat'

interface SourceReferenceProps {
  /** 引用来源列表（来自 done 事件的 sources 字段） */
  sources: SourceDocument[]
}

/**
 * SourceReference：展示 RAG 检索到的引用来源文档片段。
 *
 * 设计：
 *   - 默认折叠，点击展开（避免占用太多聊天空间）
 *   - 每个 source 卡片展示文件名、chunk 序号和文本预览
 *   - 预览超过 150 字的内容截断并显示"展开"按钮
 */
export function SourceReference({ sources }: SourceReferenceProps) {
  // 控制整个来源列表是否展开
  const [isExpanded, setIsExpanded] = useState(false)
  // 记录哪些 chunk 展开了完整内容
  const [expandedChunks, setExpandedChunks] = useState<Set<number>>(new Set())

  if (!sources || sources.length === 0) return null

  const toggleChunk = (idx: number) => {
    setExpandedChunks(prev => {
      const next = new Set(prev)
      next.has(idx) ? next.delete(idx) : next.add(idx)
      return next
    })
  }

  return (
    <div className="mt-3 border-t border-gray-100 pt-3">
      {/* 折叠/展开触发按钮 */}
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-gray-700 transition-colors"
      >
        {/* 展开/折叠箭头图标 */}
        <svg
          className={`w-3.5 h-3.5 transition-transform ${isExpanded ? 'rotate-90' : ''}`}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
        </svg>
        <span>
          参考来源 ({sources.length} 个片段)
        </span>
      </button>

      {/* 来源卡片列表（展开时显示） */}
      {isExpanded && (
        <div className="mt-2 space-y-2">
          {sources.map((src, idx) => {
            const isChunkExpanded = expandedChunks.has(idx)
            const preview = src.content.length > 150 && !isChunkExpanded
              ? src.content.slice(0, 150) + '...'
              : src.content

            return (
              <div
                key={idx}
                className="bg-gray-50 border border-gray-200 rounded-lg p-3 text-xs"
              >
                {/* 来源头部：文件名 + chunk 序号 */}
                <div className="flex items-center justify-between mb-1.5">
                  <div className="flex items-center gap-1.5">
                    {/* 文档图标 */}
                    <svg className="w-3.5 h-3.5 text-blue-500 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                        d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                    </svg>
                    <span className="font-medium text-gray-700 truncate max-w-[200px]">
                      {src.filename}
                    </span>
                  </div>
                  {/* chunk 序号徽章 */}
                  <span className="bg-blue-100 text-blue-600 px-1.5 py-0.5 rounded text-[10px] flex-shrink-0">
                    片段 #{src.chunk_index + 1}
                  </span>
                </div>

                {/* 文本内容预览 */}
                <p className="text-gray-600 leading-relaxed whitespace-pre-wrap">{preview}</p>

                {/* 展开/收起长内容 */}
                {src.content.length > 150 && (
                  <button
                    onClick={() => toggleChunk(idx)}
                    className="mt-1 text-blue-500 hover:text-blue-700"
                  >
                    {isChunkExpanded ? '收起' : '展开全文'}
                  </button>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
