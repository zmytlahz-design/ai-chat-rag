import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Plus, MoreHorizontal, Settings, Trash2, MessageSquare, FileText, BarChart3, Database } from 'lucide-react'

import { useKnowledgeStore } from '@/stores/useKnowledgeStore'
import { knowledgeApi, type KnowledgeBase, type HotQuestionItem } from '@/api/knowledge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  DropdownMenuSeparator,
} from '@/components/ui/dropdown-menu'
import { useToast } from '@/components/ui/use-toast'

export default function KnowledgeBasePage() {
  const navigate = useNavigate()
  const { toast } = useToast()
  const { knowledgeBases, isLoading, fetchKbs, createKb, updateKb, deleteKb, selectKb } =
    useKnowledgeStore()

  const [createOpen, setCreateOpen] = useState(false)
  const [editOpen, setEditOpen] = useState(false)
  const [editingKb, setEditingKb] = useState<KnowledgeBase | null>(null)
  
  // 表单状态
  const [name, setName] = useState('')
  const [desc, setDesc] = useState('')
  const [loading, setLoading] = useState(false)

  // 热门问题
  const [hotOpen, setHotOpen] = useState(false)
  const [hotQuestions, setHotQuestions] = useState<HotQuestionItem[]>([])
  const [hotLoading, setHotLoading] = useState(false)
  const [currentHotKb, setCurrentHotKb] = useState<string>('')

  useEffect(() => {
    fetchKbs()
  }, [fetchKbs])

  const openCreate = () => {
    setName('')
    setDesc('')
    setCreateOpen(true)
  }

  const openEdit = (kb: KnowledgeBase) => {
    setEditingKb(kb)
    setName(kb.name)
    setDesc(kb.description || '')
    setEditOpen(true)
  }

  const handleCreate = async () => {
    if (!name.trim()) return
    setLoading(true)
    try {
      await createKb({ name, description: desc })
      setCreateOpen(false)
      toast({ title: "创建成功" })
    } catch (err) {
      toast({ variant: "destructive", title: "创建失败", description: (err as Error).message })
    } finally {
      setLoading(false)
    }
  }

  const handleUpdate = async () => {
    if (!editingKb || !name.trim()) return
    setLoading(true)
    try {
      await updateKb(editingKb.id, { name, description: desc })
      setEditOpen(false)
      toast({ title: "更新成功" })
    } catch (err) {
      toast({ variant: "destructive", title: "更新失败", description: (err as Error).message })
    } finally {
      setLoading(false)
    }
  }

  const handleViewHot = async (kbId: number, kbName: string) => {
    setCurrentHotKb(kbName)
    setHotOpen(true)
    setHotLoading(true)
    try {
      const res = await knowledgeApi.getHotQuestions(kbId)
      setHotQuestions(res.items)
    } catch (err) {
      toast({ variant: "destructive", title: "获取失败", description: (err as Error).message })
    } finally {
      setHotLoading(false)
    }
  }

  const handleClearCache = async (kbId: number) => {
    if (!confirm('确认清空 RAG 缓存？')) return
    try {
      await knowledgeApi.clearCache(kbId)
      toast({ title: "缓存已清空" })
    } catch (err) {
      toast({ variant: "destructive", title: "操作失败", description: (err as Error).message })
    }
  }

  return (
    <div className="min-h-screen bg-muted/30 p-8">
      <div className="max-w-6xl mx-auto space-y-8">
        <div className="flex items-center justify-between">
          <div className="space-y-1">
            <h1 className="text-3xl font-bold tracking-tight">知识库管理</h1>
            <p className="text-muted-foreground">
              创建和管理你的知识库，上传文档并配置对话设置。
            </p>
          </div>
          <Button onClick={openCreate}>
            <Plus className="mr-2 h-4 w-4" />
            新建知识库
          </Button>
        </div>

        {isLoading ? (
          <div className="grid place-items-center py-20">加载中...</div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {knowledgeBases.map(kb => (
              <Card key={kb.id} className="group hover:shadow-md transition-shadow">
                <CardHeader className="flex flex-row items-start justify-between space-y-0 pb-2">
                  <div className="flex items-center gap-2">
                    <div className="p-2 bg-primary/10 rounded-lg">
                      <Database className="h-5 w-5 text-primary" />
                    </div>
                    <div>
                      <CardTitle className="text-base">{kb.name}</CardTitle>
                      <CardDescription className="text-xs mt-1">
                        {new Date(kb.created_at).toLocaleDateString()}
                      </CardDescription>
                    </div>
                  </div>
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button variant="ghost" size="icon" className="-mr-2 h-8 w-8 opacity-0 group-hover:opacity-100">
                        <MoreHorizontal className="h-4 w-4" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      <DropdownMenuItem onClick={() => openEdit(kb)}>
                        <Settings className="mr-2 h-4 w-4" /> 编辑信息
                      </DropdownMenuItem>
                      <DropdownMenuItem onClick={() => handleViewHot(kb.id, kb.name)}>
                        <BarChart3 className="mr-2 h-4 w-4" /> 热门问题
                      </DropdownMenuItem>
                      <DropdownMenuItem onClick={() => handleClearCache(kb.id)}>
                        <Database className="mr-2 h-4 w-4" /> 清空缓存
                      </DropdownMenuItem>
                      <DropdownMenuSeparator />
                      <DropdownMenuItem 
                        className="text-destructive focus:text-destructive"
                        onClick={async () => {
                          if (confirm('确认删除？此操作不可恢复。')) await deleteKb(kb.id)
                        }}
                      >
                        <Trash2 className="mr-2 h-4 w-4" /> 删除
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </CardHeader>
                <CardContent>
                  <p className="text-sm text-muted-foreground line-clamp-2 min-h-[2.5em]">
                    {kb.description || "暂无描述"}
                  </p>
                </CardContent>
                <CardFooter className="grid grid-cols-2 gap-3">
                  <Button 
                    variant="outline" 
                    className="w-full" 
                    onClick={() => {
                      selectKb(kb.id)
                      navigate('/')
                    }}
                  >
                    <MessageSquare className="mr-2 h-4 w-4" /> 对话
                  </Button>
                  <Button 
                    variant="secondary" 
                    className="w-full"
                    onClick={() => navigate(`/kb/${kb.id}/documents`)}
                  >
                    <FileText className="mr-2 h-4 w-4" /> 文档
                  </Button>
                </CardFooter>
              </Card>
            ))}
          </div>
        )}
      </div>

      {/* 创建/编辑 Modal */}
      <Dialog open={createOpen || editOpen} onOpenChange={(v) => { if (!v) { setCreateOpen(false); setEditOpen(false) } }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{editOpen ? '编辑知识库' : '新建知识库'}</DialogTitle>
            <DialogDescription>
              配置知识库的基本信息。
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <div className="grid gap-2">
              <Label htmlFor="name">名称</Label>
              <Input id="name" value={name} onChange={e => setName(e.target.value)} />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="desc">描述</Label>
              <Textarea id="desc" value={desc} onChange={e => setDesc(e.target.value)} />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => { setCreateOpen(false); setEditOpen(false) }}>取消</Button>
            <Button onClick={editOpen ? handleUpdate : handleCreate} disabled={loading}>
              {loading ? '处理中...' : '确认'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 热门问题 Modal */}
      <Dialog open={hotOpen} onOpenChange={setHotOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>热门问题 - {currentHotKb}</DialogTitle>
          </DialogHeader>
          <div className="py-4">
            {hotLoading ? (
              <div className="text-center text-sm text-muted-foreground">加载中...</div>
            ) : hotQuestions.length === 0 ? (
              <div className="text-center text-sm text-muted-foreground">暂无数据</div>
            ) : (
              <div className="space-y-4">
                {hotQuestions.map((q) => (
                  <div key={q.rank} className="flex items-start gap-4 p-3 rounded-lg bg-muted/50">
                    <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary text-xs font-bold text-primary-foreground">
                      {q.rank}
                    </span>
                    <div className="space-y-1">
                      <p className="text-sm font-medium leading-none">{q.question}</p>
                      <p className="text-xs text-muted-foreground">提问 {q.count} 次</p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
