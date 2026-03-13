import { useState, useCallback } from 'react'
import { useDropzone, type FileRejection } from 'react-dropzone'
import { UploadCloud, File, AlertCircle, CheckCircle2, Loader2 } from 'lucide-react'

import { documentApi, type Document } from '@/api/document'
import { Progress } from '@/components/ui/progress'
import { useToast } from '@/components/ui/use-toast'
import { cn } from '@/lib/utils'

interface DocumentUploadProps {
  kbId: number
  onUploadComplete?: () => void
}

interface UploadTask {
  id: string
  file: File
  progress: number
  docId?: number
  status: 'uploading' | 'processing' | 'completed' | 'failed'
  errorMessage?: string
}

const ACCEPTED_TYPES = {
  'application/pdf': ['.pdf'],
  'text/plain': ['.txt'],
  'text/markdown': ['.md'],
}
const MAX_FILE_SIZE = 50 * 1024 * 1024 // 50MB

export function DocumentUpload({ kbId, onUploadComplete }: DocumentUploadProps) {
  const { toast } = useToast()
  const [tasks, setTasks] = useState<UploadTask[]>([])

  const updateTask = useCallback((id: string, patch: Partial<UploadTask>) => {
    setTasks(prev => prev.map(t => t.id === id ? { ...t, ...patch } : t))
  }, [])

  const pollDocumentStatus = useCallback(async (taskId: string, docId: number) => {
    let retries = 0
    const maxRetries = 40

    const poll = async () => {
      if (retries >= maxRetries) {
        updateTask(taskId, { status: 'failed', errorMessage: '处理超时' })
        return
      }

      try {
        const doc = await documentApi.get(docId)
        if (doc.status === 'completed') {
          updateTask(taskId, { status: 'completed' })
          toast({ title: "处理完成", description: `${doc.filename} 已加入知识库` })
          onUploadComplete?.()
        } else if (doc.status === 'failed') {
          updateTask(taskId, {
            status: 'failed',
            errorMessage: doc.error_message || '处理失败',
          })
        } else {
          updateTask(taskId, { status: 'processing' })
          retries++
          setTimeout(poll, 1500)
        }
      } catch {
        retries++
        setTimeout(poll, 3000)
      }
    }
    await poll()
  }, [updateTask, onUploadComplete, toast])

  const uploadFile = useCallback(async (file: File) => {
    const taskId = `${Date.now()}-${Math.random()}`
    const newTask: UploadTask = {
      id: taskId,
      file,
      progress: 0,
      status: 'uploading',
    }
    setTasks(prev => [...prev, newTask])

    try {
      const doc = await documentApi.upload(
        kbId,
        file,
        (percent) => updateTask(taskId, { progress: percent })
      )
      updateTask(taskId, { docId: doc.id, status: 'processing', progress: 100 })
      pollDocumentStatus(taskId, doc.id)
    } catch (err) {
      updateTask(taskId, {
        status: 'failed',
        errorMessage: (err as Error).message,
      })
    }
  }, [kbId, updateTask, pollDocumentStatus])

  const onDrop = useCallback(
    (acceptedFiles: File[], rejectedFiles: FileRejection[]) => {
      rejectedFiles.forEach(({ file, errors }) => {
        toast({
          variant: "destructive",
          title: "文件被拒绝",
          description: `${file.name}: ${errors.map(e => e.message).join(', ')}`,
        })
      })
      acceptedFiles.forEach(file => uploadFile(file))
    },
    [uploadFile, toast]
  )

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: ACCEPTED_TYPES,
    maxSize: MAX_FILE_SIZE,
    multiple: true,
  })

  return (
    <div className="space-y-4">
      <div
        {...getRootProps()}
        className={cn(
          "border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-colors",
          isDragActive
            ? "border-primary bg-primary/5"
            : "border-muted-foreground/25 hover:border-primary/50 hover:bg-muted/50"
        )}
      >
        <input {...getInputProps()} />
        <div className="flex flex-col items-center gap-2">
          <UploadCloud className="h-10 w-10 text-muted-foreground" />
          <div className="space-y-1">
            <p className="text-sm font-medium">
              拖拽文件到这里，或点击上传
            </p>
            <p className="text-xs text-muted-foreground">
              支持 PDF, TXT, Markdown (最大 50MB)
            </p>
          </div>
        </div>
      </div>

      {tasks.length > 0 && (
        <div className="space-y-3">
          {tasks.map(task => (
            <div key={task.id} className="bg-card border rounded-lg p-3 space-y-2">
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2 overflow-hidden">
                  <File className="h-4 w-4 shrink-0 text-muted-foreground" />
                  <span className="text-sm truncate font-medium">{task.file.name}</span>
                </div>
                {task.status === 'uploading' && <span className="text-xs text-muted-foreground">{task.progress}%</span>}
                {task.status === 'processing' && <Loader2 className="h-4 w-4 animate-spin text-yellow-500" />}
                {task.status === 'completed' && <CheckCircle2 className="h-4 w-4 text-green-500" />}
                {task.status === 'failed' && <AlertCircle className="h-4 w-4 text-destructive" />}
              </div>
              
              <Progress 
                value={task.status === 'uploading' ? task.progress : 100} 
                className={cn(
                  "h-1.5",
                  task.status === 'failed' && "bg-destructive/20",
                  task.status === 'processing' && "animate-pulse"
                )}
              />
              
              {task.status === 'failed' && (
                <p className="text-xs text-destructive">{task.errorMessage}</p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
