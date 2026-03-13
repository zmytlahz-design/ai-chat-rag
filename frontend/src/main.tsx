import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'

// 全局样式：Tailwind 基础层 + highlight.js 代码高亮主题
import './index.css'

// ReactDOM.createRoot 是 React 18 的并发模式根节点
// StrictMode 在开发环境下会故意渲染两次以检测副作用
ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
