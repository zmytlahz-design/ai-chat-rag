import { useState } from 'react'
import { Plus, MoreHorizontal, Trash2, Database } from 'lucide-react'

import { useKnowledgeStore } from '@/stores/useKnowledgeStore'
import { useChatStore } from '@/stores/useChatStore'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { cn } from '@/lib/utils'

export function KnowledgeList() {
  const { knowledgeBases, currentKbId, selectKb, createKb, deleteKb } = useKnowledgeStore()
  const { fetchConversations, clearMessages } = useChatStore()
  const safeKnowledgeBases = Array.isArray(knowledgeBases) ? knowledgeBases : []

  const [createOpen, setCreateOpen] = useState(false)
  const [name, setName] = useState('')
  const [desc, setDesc] = useState('')
  const [loading, setLoading] = useState(false)

  const handleSelect = (id: number) => {
    if (id === currentKbId) return
    selectKb(id)
    clearMessages()
    fetchConversations(id)
  }

  const handleCreate = async () => {
    if (!name.trim()) return
    setLoading(true)
    try {
      const kb = await createKb({ name, description: desc })
      setCreateOpen(false)
      setName('')
      setDesc('')
      // 自动切换
      handleSelect(kb.id)
    } catch (err) {
      // 实际项目中建议用 toast
      alert('创建失败: ' + (err as Error).message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between px-2">
        <h2 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
          知识库
        </h2>
        <Dialog open={createOpen} onOpenChange={setCreateOpen}>
          <DialogTrigger asChild>
            <Button variant="ghost" size="icon" className="h-5 w-5">
              <Plus className="h-4 w-4" />
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>新建知识库</DialogTitle>
              <DialogDescription>
                创建一个新的知识库来存储文档和进行对话。
              </DialogDescription>
            </DialogHeader>
            <div className="grid gap-4 py-4">
              <div className="grid gap-2">
                <Label htmlFor="name">名称</Label>
                <Input
                  id="name"
                  value={name}
                  onChange={e => setName(e.target.value)}
                  placeholder="例如：产品手册"
                />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="desc">描述（可选）</Label>
                <Input
                  id="desc"
                  value={desc}
                  onChange={e => setDesc(e.target.value)}
                  placeholder="简短描述..."
                />
              </div>
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => setCreateOpen(false)}>取消</Button>
              <Button onClick={handleCreate} disabled={loading || !name.trim()}>
                {loading ? '创建中...' : '创建'}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>

      <div className="space-y-1">
        {safeKnowledgeBases.map(kb => (
          <div
            key={kb.id}
            className={cn(
              "group flex items-center gap-2 rounded-md px-2 py-1.5 text-sm font-medium hover:bg-accent hover:text-accent-foreground cursor-pointer transition-colors",
              kb.id === currentKbId ? "bg-accent text-accent-foreground" : "text-muted-foreground"
            )}
            onClick={() => handleSelect(kb.id)}
          >
            <Database className="h-4 w-4 shrink-0" />
            <span className="flex-1 truncate">{kb.name}</span>
            
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-6 w-6 opacity-0 group-hover:opacity-100"
                  onClick={e => e.stopPropagation()} // 阻止触发选择
                >
                  <MoreHorizontal className="h-3 w-3" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem
                  className="text-destructive focus:text-destructive"
                  onClick={async (e) => {
                    e.stopPropagation()
                    if (confirm(`确认删除「${kb.name}」？`)) {
                      await deleteKb(kb.id)
                    }
                  }}
                >
                  <Trash2 className="mr-2 h-4 w-4" />
                  删除
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        ))}
      </div>
    </div>
  )
}
