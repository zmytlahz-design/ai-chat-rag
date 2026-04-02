import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Vite 配置
// 开发模式下通过 proxy 把 /api 请求转发到后端，绕开浏览器跨域限制
// 生产 Docker 下由 frontend 容器内转发 /api，同源无需此处代理
export default defineConfig({
  plugins: [react()],

  server: {
    port: 5173,
    // 代理配置：所有 /api 开头的请求转发到后端 8000 端口
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true, // 修改 Host 请求头，防止后端拒绝
      },
    },
  },

  // 路径别名：@ 指向 src 目录，避免长相对路径 ../../xxx
  resolve: {
    alias: {
      '@': '/src',
    },
  },
})
