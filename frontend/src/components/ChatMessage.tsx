import ReactMarkdown from 'react-markdown'
import type { ChatMessage as ChatMessageType } from '../stores/useChatStore'
import { SourceReference } from './SourceReference'
import { remarkPlugins, rehypePlugins, markdownComponents } from '../utils/markdown.tsx'

interface ChatMessageProps {
  message: ChatMessageType
}

/**
 * ChatMessage：单条消息气泡组件。
 *
 * 支持两种角色：
 *   - user：蓝色气泡，靠右对齐，纯文本显示
 *   - assistant：白色卡片，靠左对齐，Markdown 渲染 + 来源展示
 *
 * 状态：
 *   - isStreaming=true：显示"正在思考..."动画（content 为空时）
 *                       或正常显示内容 + 光标闪烁（content 非空时）
 */
export function ChatMessage({ message }: ChatMessageProps) {
  const isUser = message.role === 'user'

  if (isUser) {
    return <UserMessage message={message} />
  }
  return <AssistantMessage message={message} />
}

// ==================== 用户消息 ====================

function UserMessage({ message }: { message: ChatMessageType }) {
  return (
    <div className="flex justify-end mb-4 px-4">
      <div className="flex flex-col items-end max-w-[75%]">
        {/* 气泡 */}
        <div className="bg-blue-600 text-white rounded-2xl rounded-tr-sm px-4 py-3 text-sm leading-relaxed shadow-sm">
          {/* 用户消息直接显示纯文本，不渲染 Markdown（避免误转义） */}
          <p className="whitespace-pre-wrap break-words">{message.content}</p>
        </div>
        {/* 时间戳（悬停显示） */}
        <span className="text-[10px] text-gray-400 mt-1 opacity-0 hover:opacity-100 transition-opacity">
          {formatTime(message.created_at)}
        </span>
      </div>
    </div>
  )
}

// ==================== AI 助手消息 ====================

function AssistantMessage({ message }: { message: ChatMessageType }) {
  const { content, isStreaming, sources } = message
  const isEmpty = !content && isStreaming

  return (
    <div className="flex justify-start mb-4 px-4">
      <div className="flex gap-3 max-w-[85%] w-full">
        {/* AI 头像 */}
        <div className="flex-shrink-0 w-8 h-8 rounded-full bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center shadow-sm">
          <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
              d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17H4a2 2 0 01-2-2V5a2 2 0 012-2h16a2 2 0 012 2v10a2 2 0 01-2 2h-1" />
          </svg>
        </div>

        <div className="flex-1 min-w-0">
          {/* 消息卡片 */}
          <div className="bg-white border border-gray-200 rounded-2xl rounded-tl-sm px-4 py-3 shadow-sm">
            {/* 内容区域 */}
            {isEmpty ? (
              // 正在思考：三个点动画
              <ThinkingIndicator />
            ) : (
              <>
                {/* Markdown 渲染 */}
                <div className="markdown-body">
                  <ReactMarkdown
                    remarkPlugins={remarkPlugins as never}
                    rehypePlugins={rehypePlugins as never}
                    components={markdownComponents}
                  >
                    {content}
                  </ReactMarkdown>
                </div>

                {/* 流式光标（还在输出时显示） */}
                {isStreaming && (
                  <span className="inline-block w-0.5 h-4 bg-gray-600 ml-0.5 animate-pulse align-text-bottom" />
                )}
              </>
            )}
          </div>

          {/* 来源引用（仅非流式状态显示） */}
          {!isStreaming && sources && sources.length > 0 && (
            <div className="px-4">
              <SourceReference sources={sources} />
            </div>
          )}

          {/* 时间戳 */}
          {!isStreaming && (
            <span className="text-[10px] text-gray-400 ml-1 mt-1 block">
              {formatTime(message.created_at)}
            </span>
          )}
        </div>
      </div>
    </div>
  )
}

// ==================== 思考中动画 ====================

function ThinkingIndicator() {
  return (
    <div className="flex items-center gap-1 py-1">
      <span className="text-sm text-gray-500 mr-1">正在思考</span>
      {/* 三个依次闪烁的点，delay 由 index.css 的 animation-delay 控制 */}
      <span className="thinking-dot" />
      <span className="thinking-dot" />
      <span className="thinking-dot" />
    </div>
  )
}

// ==================== 工具函数 ====================

/** 格式化时间戳为 HH:mm 格式 */
function formatTime(isoString: string): string {
  try {
    return new Date(isoString).toLocaleTimeString('zh-CN', {
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return ''
  }
}
