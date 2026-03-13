import { RouterProvider } from 'react-router-dom'
import { router } from './router'
import { Toaster } from '@/components/ui/toaster'

// App 是整个应用的根组件，只负责挂载路由
// 业务逻辑和状态管理放在各页面和 Zustand stores 中
export default function App() {
  return (
    <>
      <RouterProvider router={router} />
      <Toaster />
    </>
  )
}
