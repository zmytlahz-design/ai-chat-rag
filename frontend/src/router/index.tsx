import { createBrowserRouter } from 'react-router-dom'
import ChatPage from '../pages/ChatPage'
import KnowledgeBasePage from '../pages/KnowledgeBase'
import DocumentManage from '../pages/DocumentManage'

/**
 * router：应用的路由配置。
 *
 * 使用 createBrowserRouter（HTML5 History API），支持嵌套路由和数据加载。
 * 相比 BrowserRouter，可以更好地与 React Router v6.4+ 的 loader/action 配合。
 *
 * 路由结构：
 *   /                       → ChatPage（对话主页面）
 *   /knowledge-base         → KnowledgeBasePage（知识库管理）
 *   /kb/:kbId/documents     → DocumentManage（文档管理，按知识库 ID 区分）
 */
export const router = createBrowserRouter([
  {
    path: '/',
    element: <ChatPage />,
  },
  {
    path: '/knowledge-base',
    element: <KnowledgeBasePage />,
  },
  {
    path: '/kb/:kbId/documents',
    element: <DocumentManage />,
  },
])
