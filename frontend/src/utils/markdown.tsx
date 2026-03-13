import type { Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeHighlight from 'rehype-highlight'

// ==================== remark 插件（Markdown 语法扩展）====================

/**
 * remarkPlugins：Markdown 语法解析扩展
 * remark-gfm：支持 GitHub Flavored Markdown（表格、任务列表、删除线、自动链接）
 */
export const remarkPlugins = [remarkGfm] as const

// ==================== rehype 插件（HTML 转换）====================

/**
 * rehypePlugins：HTML 处理扩展
 * rehype-highlight：对代码块应用 highlight.js 语法高亮
 * detect: true → 自动检测语言
 * ignoreMissing: true → 找不到语言定义时不报错
 */
export const rehypePlugins = [
  [rehypeHighlight, { detect: true, ignoreMissing: true }],
] as const

// ==================== 自定义组件覆盖（必须是 .tsx 文件，包含 JSX）====================

/**
 * markdownComponents：覆盖 react-markdown 默认渲染的 HTML 元素
 * 主要处理代码块样式，区分内联代码（`code`）和代码块（```）
 */
export const markdownComponents: Components = {
  // 覆盖 <code> 标签：区分内联代码和代码块内部的 code
  code({ className, children, ...props }) {
    // 如果有 language-xxx className，说明是代码块（来自 ```lang 语法）
    const isBlock = Boolean(className)

    if (isBlock) {
      // 代码块：样式由 rehype-highlight 的 pre > code 负责
      return (
        <code className={className} {...props}>
          {children}
        </code>
      )
    }

    // 内联代码（单反引号）：红色小字体
    return (
      <code
        className="bg-gray-100 text-red-600 px-1.5 py-0.5 rounded text-xs font-mono"
        {...props}
      >
        {children}
      </code>
    )
  },

  // 覆盖 <pre> 标签：代码块容器样式
  pre({ children, ...props }) {
    return (
      <pre
        className="bg-gray-50 border border-gray-200 rounded-lg p-4 my-3 overflow-x-auto text-sm"
        {...props}
      >
        {children}
      </pre>
    )
  },

  // 链接：在新标签页打开，防止跳出当前页面
  a({ href, children, ...props }) {
    return (
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className="text-blue-600 hover:underline"
        {...props}
      >
        {children}
      </a>
    )
  },
}
