import { useEffect, useRef, useCallback } from 'react'

/**
 * useAutoScroll：消息区域自动滚动到底部的 Hook。
 *
 * 核心行为：
 *   - 当 deps 中的依赖变化时（如新消息加入、token 追加），自动滚动到底部
 *   - 如果用户主动向上滚动（查看历史消息），暂停自动滚动
 *   - 用户滚动回底部后，恢复自动滚动
 *
 * 使用方式：
 *   const { scrollRef, scrollToBottom } = useAutoScroll([messages, isStreaming])
 *   <div ref={scrollRef} className="overflow-y-auto">...</div>
 */
export function useAutoScroll(deps: unknown[]) {
  // 绑定到可滚动容器的 ref
  const scrollRef = useRef<HTMLDivElement>(null)

  // 标记用户是否"固定在底部"，初始为 true（自动滚动）
  const isPinnedToBottomRef = useRef(true)

  /** 手动滚动到底部 */
  const scrollToBottom = useCallback((behavior: ScrollBehavior = 'smooth') => {
    const el = scrollRef.current
    if (!el) return
    el.scrollTo({ top: el.scrollHeight, behavior })
  }, [])

  // 监听滚动事件：判断用户是否接近底部
  useEffect(() => {
    const el = scrollRef.current
    if (!el) return

    const handleScroll = () => {
      // distanceFromBottom：距离底部的像素数
      const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight
      // 距离底部 60px 以内视为"固定在底部"
      isPinnedToBottomRef.current = distanceFromBottom < 60
    }

    el.addEventListener('scroll', handleScroll, { passive: true })
    return () => el.removeEventListener('scroll', handleScroll)
  }, [])

  // 当依赖变化时（新消息/新 token），若固定在底部则自动滚动
  useEffect(() => {
    if (isPinnedToBottomRef.current) {
      scrollToBottom('smooth')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  return { scrollRef, scrollToBottom }
}
