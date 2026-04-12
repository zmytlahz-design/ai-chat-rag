import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Bot, MessageSquarePlus, Library, Settings, FileText } from 'lucide-react'

import { useKnowledgeStore } from '@/stores/useKnowledgeStore'
import { useChatStore } from '@/stores/useChatStore'
import { KnowledgeList } from '@/components/KnowledgeList'
import { ConversationList } from '@/components/ConversationList'
import { ChatMessage } from '@/components/ChatMessage'
import { ChatInput } from '@/components/ChatInput'
import { useAutoScroll } from '@/hooks/useAutoScroll'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Separator } from '@/components/ui/separator'

/**
 * ChatPage：对话主页面。
 * 布局（两栏）：左侧侧边栏 + 右侧对话区
 */
export default function ChatPage() {
  const navigate = useNavigate()
  const { knowledgeBases, currentKbId, isLoading: kbLoading, fetchKbs } = useKnowledgeStore()
  const {
    messages,
    isStreaming,
    isLoadingMessages,
    currentConversationId,
    fetchConversations,
    sendMessage,
    cancelStreaming,
    newConversation,
  } = useChatStore()

  const { scrollRef } = useAutoScroll([messages, isStreaming])

  // 初始化加载知识库
  useEffect(() => {
    fetchKbs()
  }, [fetchKbs])

  // 切换 KB 时加载对话
  useEffect(() => {
    if (currentKbId) {
      fetchConversations(currentKbId)
    }
  }, [currentKbId, fetchConversations])

  const handleSend = (text: string) => {
    if (!currentKbId) return
    sendMessage(currentKbId, text)
  }

  const safeKnowledgeBases = Array.isArray(knowledgeBases) ? knowledgeBases : []
  const currentKb = safeKnowledgeBases.find(kb => kb.id === currentKbId)

  return (
    <div className="flex h-screen bg-background overflow-hidden">
      {/* ======== 左侧侧边栏 ======== */}
      <aside className="w-[260px] flex-shrink-0 bg-muted/30 border-r flex flex-col overflow-hidden">
        {/* Logo / 标题区 */}
        <div className="flex items-center gap-2 px-4 py-4 h-14 border-b">
          <div className="w-8 h-8 rounded-lg bg-primary flex items-center justify-center flex-shrink-0">
            <Bot className="w-5 h-5 text-primary-foreground" />
          </div>
          <span className="font-semibold text-sm">AI 知识库对话</span>
        </div>

        {/* 侧边栏内容 */}
        <ScrollArea className="flex-1">
          <div className="p-2 space-y-4">
            {kbLoading ? (
              <div className="px-4 py-8 text-xs text-muted-foreground text-center">加载中...</div>
            ) : (
              <KnowledgeList />
            )}
            <ConversationList />
          </div>
        </ScrollArea>

        {/* 底部工具栏 */}
        <div className="p-2 border-t bg-muted/30">
          <div className="space-y-1">
            <Button
              variant="ghost"
              className="w-full justify-start text-muted-foreground hover:text-foreground"
              onClick={() => currentKbId && navigate(`/kb/${currentKbId}/documents`)}
              disabled={!currentKbId}
            >
              <FileText className="mr-2 h-4 w-4" />
              文档管理
            </Button>
            <Button
              variant="ghost"
              className="w-full justify-start text-muted-foreground hover:text-foreground"
              onClick={() => navigate('/knowledge-base')}
            >
              <Settings className="mr-2 h-4 w-4" />
              知识库管理
            </Button>
          </div>
        </div>
      </aside>

      {/* ======== 右侧主内容区 ======== */}
      <main className="flex-1 flex flex-col min-w-0 bg-background">
        {/* 顶部 Header */}
        <header className="flex-shrink-0 h-14 flex items-center justify-between px-6 border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
          <div className="flex items-center gap-2 overflow-hidden">
            <Library className="w-4 h-4 text-muted-foreground flex-shrink-0" />
            <h1 className="text-sm font-medium truncate">
              {currentKb ? currentKb.name : '请选择知识库'}
            </h1>
            {currentConversationId && (
              <>
                <Separator orientation="vertical" className="h-4 mx-1" />
                <span className="text-xs text-muted-foreground">
                  对话 #{currentConversationId}
                </span>
              </>
            )}
          </div>

          <Button
            variant="outline"
            size="sm"
            onClick={newConversation}
            disabled={!currentKbId}
            className="h-8"
          >
            <MessageSquarePlus className="mr-2 h-4 w-4" />
            新对话
          </Button>
        </header>

        {/* 消息区域 */}
        <div className="flex-1 overflow-hidden relative">
          <div ref={scrollRef} className="h-full overflow-y-auto p-4 scroll-smooth">
            {isLoadingMessages ? (
              <LoadingMessages />
            ) : messages.length === 0 ? (
              <EmptyState kbName={currentKb?.name} />
            ) : (
              <div className="max-w-3xl mx-auto py-6 space-y-6">
                {messages.map(msg => (
                  <ChatMessage key={msg.localId} message={msg} />
                ))}
              </div>
            )}
          </div>
        </div>

        {/* 输入框区域 */}
        <div className="p-4 border-t bg-background">
          <div className="max-w-3xl mx-auto">
            <ChatInput
              onSubmit={handleSend}
              onCancel={cancelStreaming}
              disabled={!currentKbId}
              isStreaming={isStreaming}
              placeholder={
                currentKbId
                  ? '向知识库提问... (Enter 发送，Shift+Enter 换行)'
                  : '请先在左侧选择一个知识库'
              }
            />
            <p className="text-center text-[10px] text-muted-foreground mt-2">
              AI 生成内容可能不准确，请核实重要信息。
            </p>
          </div>
        </div>
      </main>
    </div>
  )
}

// ==================== 子组件 ====================

function EmptyState({ kbName }: { kbName?: string }) {
  return (
    <div className="flex flex-col items-center justify-center h-full text-center px-4">
      <div className="w-16 h-16 rounded-2xl bg-muted flex items-center justify-center mb-6">
        <Bot className="w-8 h-8 text-muted-foreground" />
      </div>
      <h2 className="text-lg font-semibold mb-2">
        {kbName ? `问问「${kbName}」` : '欢迎使用'}
      </h2>
      <p className="text-sm text-muted-foreground mb-8 max-w-sm">
        {kbName
          ? '我可以根据该知识库的内容回答你的问题，支持引用来源追踪。'
          : '请在左侧选择一个知识库开始对话。'}
      </p>
    </div>
  )
}

function LoadingMessages() {
  return (
    <div className="max-w-3xl mx-auto space-y-8 py-10">
      {[1, 2, 3].map(i => (
        <div key={i} className={`flex gap-4 ${i % 2 === 0 ? 'flex-row-reverse' : ''}`}>
          <div className="w-8 h-8 rounded-full bg-muted flex-shrink-0" />
          <div className="space-y-2 max-w-[60%] w-full">
            <div className="h-4 bg-muted rounded w-full" />
            <div className="h-4 bg-muted rounded w-[80%]" />
          </div>
        </div>
      ))}
    </div>
  )
}
