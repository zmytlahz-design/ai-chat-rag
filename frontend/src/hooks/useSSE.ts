import { useCallback, useRef, useState } from 'react'
import type { SSEEvent } from '../api/chat'

// ==================== 类型定义 ====================

/** useSSE 的回调选项 */
export interface SSECallbacks {
  /** 流开始（收到 start 事件）时触发 */
  onStart?: (conversationId: number, fromCache?: boolean) => void
  /** 收到 token 片段时触发（用于逐字渲染） */
  onToken?: (content: string) => void
  /** 流结束时触发（携带完整 sources） */
  onDone?: (event: Extract<SSEEvent, { type: 'done' }>) => void
  /** 发生错误时触发 */
  onError?: (message: string) => void
}

/** useSSE 返回值 */
export interface UseSSEReturn {
  isStreaming: boolean
  /** 开始一个 SSE 流式请求 */
  startStream: (url: string, body: object, callbacks: SSECallbacks) => Promise<void>
  /** 中止当前流式请求 */
  stopStream: () => void
}

// ==================== Hook 实现 ====================

/**
 * useSSE：封装 fetch + ReadableStream 实现服务端推送事件（SSE）的 POST 请求。
 *
 * 为什么不用 EventSource？
 *   - 原生 EventSource 只支持 GET 请求，无法携带请求体（body）
 *   - 本项目的 chat/stream 接口需要 POST + JSON body
 *   - 用 fetch + ReadableStream 可以完整控制请求方式和请求头
 *
 * 协议约定（后端 SSE 格式）：
 *   每行格式：data: <JSON字符串>\n\n
 *   JSON 中有 type 字段：start / token / done / error
 */
export function useSSE(): UseSSEReturn {
  // isStreaming：是否有正在进行的流式请求
  const [isStreaming, setIsStreaming] = useState(false)

  // 用 ref 保存 AbortController，使其在 startStream 回调中保持引用不变
  const abortControllerRef = useRef<AbortController | null>(null)

  /** 中止当前流 */
  const stopStream = useCallback(() => {
    abortControllerRef.current?.abort()
  }, [])

  /**
   * 开始流式请求
   * @param url     后端 SSE 接口地址（如 /api/v1/chat/stream）
   * @param body    POST 请求体（JSON 序列化后发送）
   * @param callbacks 各事件回调
   */
  const startStream = useCallback(
    async (url: string, body: object, callbacks: SSECallbacks) => {
      // 如果有上一个未结束的流，先中止
      abortControllerRef.current?.abort()

      // 创建新的 AbortController 用于取消请求
      const controller = new AbortController()
      abortControllerRef.current = controller

      setIsStreaming(true)

      try {
        // 发起 POST 请求，不等待完整响应体（流式读取）
        const response = await fetch(url, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
          signal: controller.signal, // 绑定取消信号
        })

        if (!response.ok) {
          throw new Error(`HTTP ${response.status}: ${response.statusText}`)
        }

        if (!response.body) {
          throw new Error('响应体为空，服务器未返回流数据')
        }

        // 获取流式读取器
        const reader = response.body.getReader()
        // TextDecoder 将二进制字节转换为 UTF-8 字符串
        const decoder = new TextDecoder('utf-8')
        // buffer 用于处理跨块的行
        let buffer = ''

        // 循环读取数据块
        while (true) {
          const { done, value } = await reader.read()
          if (done) break // 流结束

          // decode(value, { stream: true }) 表示还未完整，保留多字节字符的末尾字节
          buffer += decoder.decode(value, { stream: true })

          // 按换行符切割，处理完整的行
          const lines = buffer.split('\n')
          // 最后一行可能不完整，保留到下次循环处理
          buffer = lines.pop() ?? ''

          for (const line of lines) {
            const trimmed = line.trim()
            // SSE 格式：以 "data: " 开头的行才包含数据
            if (!trimmed.startsWith('data: ')) continue

            const jsonStr = trimmed.slice(6) // 去掉 "data: " 前缀
            if (!jsonStr) continue

            try {
              const event = JSON.parse(jsonStr) as SSEEvent

              // 根据事件类型调用对应回调
              switch (event.type) {
                case 'start':
                  callbacks.onStart?.(event.conversation_id, event.from_cache)
                  break

                case 'token':
                  callbacks.onToken?.(event.content)
                  break

                case 'done':
                  callbacks.onDone?.(event)
                  break

                case 'error':
                  callbacks.onError?.(event.message)
                  break
              }
            } catch {
              // 忽略 JSON 解析失败（可能是空行或心跳包）
              console.debug('[useSSE] 忽略非 JSON SSE 行:', trimmed)
            }
          }
        }
      } catch (err) {
        if (err instanceof Error) {
          // AbortError 是主动取消，不作为错误处理
          if (err.name === 'AbortError') return
          callbacks.onError?.(err.message)
        }
      } finally {
        // 无论成功/失败/取消，都重置流状态
        setIsStreaming(false)
      }
    },
    [],
  )

  return { isStreaming, startStream, stopStream }
}
