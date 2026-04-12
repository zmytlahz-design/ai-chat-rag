import { MessageSquare, MoreHorizontal, Trash2 } from 'lucide-react'
import { useChatStore } from '@/stores/useChatStore'
import { useKnowledgeStore } from '@/stores/useKnowledgeStore'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { cn } from '@/lib/utils'

export function ConversationList() {
  const { currentKbId } = useKnowledgeStore()
  const {
    conversations,
    currentConversationId,
    selectConversation,
    deleteConversation,
  } = useChatStore()
  const safeConversations = Array.isArray(conversations) ? conversations : []

  if (!currentKbId) return null

  return (
    <div className="space-y-2 pt-4">
      <div className="px-2">
        <h2 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
          历史对话
        </h2>
      </div>

      <div className="space-y-1">
        {safeConversations.length === 0 ? (
          <p className="px-2 text-xs text-muted-foreground">暂无记录</p>
        ) : (
          safeConversations.map(conv => (
            <div
              key={conv.id}
              className={cn(
                "group flex items-center gap-2 rounded-md px-2 py-1.5 text-sm font-medium hover:bg-accent hover:text-accent-foreground cursor-pointer transition-colors",
                conv.id === currentConversationId ? "bg-accent text-accent-foreground" : "text-muted-foreground"
              )}
              onClick={() => selectConversation(conv.id)}
            >
              <MessageSquare className="h-4 w-4 shrink-0" />
              <span className="flex-1 truncate">{conv.title || '新对话'}</span>

              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-6 w-6 opacity-0 group-hover:opacity-100"
                    onClick={e => e.stopPropagation()}
                  >
                    <MoreHorizontal className="h-3 w-3" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem
                    className="text-destructive focus:text-destructive"
                    onClick={async (e) => {
                      e.stopPropagation()
                      if (confirm('确认删除此对话？')) {
                        await deleteConversation(conv.id, currentKbId)
                      }
                    }}
                  >
                    <Trash2 className="mr-2 h-4 w-4" />
                    删除
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          ))
        )}
      </div>
    </div>
  )
}
