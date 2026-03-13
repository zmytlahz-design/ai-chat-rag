import axios from 'axios'

// 创建 axios 实例，统一配置所有 HTTP 请求
// baseURL 优先级：环境变量 > 当前页面 origin（保证与访问端口一致，避免请求发到 80）
const getBaseURL = (): string => {
  const env = import.meta.env.VITE_API_BASE_URL
  if (env && typeof env === 'string' && env.trim() !== '') return env.trim()
  if (typeof window !== 'undefined') return window.location.origin
  return ''
}
const apiClient = axios.create({
  baseURL: getBaseURL(),
  headers: { 'Content-Type': 'application/json' },
  timeout: 30000, // 30 秒超时，避免长时间挂起
})

// 响应拦截器：统一处理 HTTP 错误
// 将后端返回的 { detail: "xxx" } 错误信息提取为 Error 对象
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    // axios 把非 2xx 状态码包装在 error.response 中
    const detail = error.response?.data?.detail
    const message = typeof detail === 'string'
      ? detail
      : Array.isArray(detail)
        ? detail.map((d: { msg: string }) => d.msg).join('; ')
        : error.message || '请求失败'
    return Promise.reject(new Error(message))
  },
)

export default apiClient
