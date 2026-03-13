import { useState, useRef, useCallback, type KeyboardEvent } from 'react'
import { Send, StopCircle } from 'lucide-react'
import { Textarea } from '@/components/ui/textarea'
import { Button } from '@/components/ui/button'

interface ChatInputProps {
  onSubmit: (text: string) => void
  onCancel?: () => void
  disabled?: boolean
  isStreaming?: boolean
  placeholder?: string
}

export function ChatInput({
  onSubmit,
  onCancel,
  disabled = false,
  isStreaming = false,
  placeholder = '向知识库提问...',
}: ChatInputProps) {
  const [value, setValue] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const handleSubmit = useCallback(() => {
    const trimmed = value.trim()
    if (!trimmed || disabled || isStreaming) return
    onSubmit(trimmed)
    setValue('')
    // 重置高度（Textarea 组件内部样式已处理 resize，但高度需要手动重置）
    // 简单的做法是利用 key 或者 ref 操作，这里暂时保留原样
  }, [value, disabled, isStreaming, onSubmit])

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault()
        handleSubmit()
      }
    },
    [handleSubmit],
  )

  const canSubmit = value.trim().length > 0 && !disabled && !isStreaming

  return (
    <div className="relative flex items-end w-full p-2 border rounded-xl shadow-sm bg-background focus-within:ring-1 focus-within:ring-ring">
      <Textarea
        ref={textareaRef}
        value={value}
        onChange={e => setValue(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        className="min-h-[44px] max-h-[200px] w-full resize-none border-0 shadow-none focus-visible:ring-0 p-3"
        style={{ height: 'auto' }} // 实际上要实现 autosize 需要额外库或 useEffect，这里简化
        disabled={disabled && !isStreaming}
      />
      
      <div className="flex pb-2 pr-2">
        {isStreaming ? (
          <Button
            size="icon"
            variant="destructive"
            className="h-8 w-8 rounded-lg"
            onClick={onCancel}
          >
            <StopCircle className="h-4 w-4" />
          </Button>
        ) : (
          <Button
            size="icon"
            className="h-8 w-8 rounded-lg"
            disabled={!canSubmit}
            onClick={handleSubmit}
          >
            <Send className="h-4 w-4" />
          </Button>
        )}
      </div>
    </div>
  )
}
