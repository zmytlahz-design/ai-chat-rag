# ==============================================================================
# frontend/Dockerfile — React 前端多阶段构建
#
# 阶段一（builder）：Node.js 环境，执行 npm install + npm run build
# 阶段二（production）：仅包含 Nginx + 构建产物，体积极小（约 25MB）
#
# 多阶段构建的优点：
#   最终镜像不含 Node.js / node_modules，安全性高，体积比单阶段小 90%+
# ==============================================================================

# =============================================================================
# 阶段一：构建阶段
# =============================================================================
FROM node:20-alpine AS builder

# 设置构建时可注入的环境变量
# VITE_API_BASE_URL：API 基础地址，留空时由 Vite 代理（开发）或 Nginx 反代（生产）处理
ARG VITE_API_BASE_URL=""
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}

# 设置工作目录
WORKDIR /app

# 先单独复制 package*.json
# 利用 Docker layer cache：只要依赖文件不变，npm ci 这层就不会重新执行
COPY package.json package-lock.json* ./

# npm ci：比 npm install 更快更可靠
# - 严格按照 package-lock.json 安装，保证版本一致
# - --omit=dev：生产构建不需要 devDependencies（此处为了 vite/tsc 保留，不加此参数）
RUN npm ci

# 复制所有源码
COPY . .

# 执行生产构建（TypeScript 编译 + Vite 打包 + Tailwind purge）
# 输出到 /app/dist 目录
RUN npm run build

# =============================================================================
# 阶段二：生产阶段（轻量 Nginx 镜像）
# =============================================================================
FROM nginx:1.25-alpine AS production

# 从构建阶段复制编译产物到 Nginx 静态文件目录
# 只复制 dist/，不包含 node_modules / src 等源码
COPY --from=builder /app/dist /usr/share/nginx/html

# 覆盖 Nginx 默认配置（支持 SPA 路由回退、Gzip 等）
COPY nginx.conf /etc/nginx/conf.d/default.conf

# 移除 Nginx 默认配置文件，避免与自定义配置冲突
RUN rm -f /etc/nginx/conf.d/default.conf.default

# 声明容器监听端口
EXPOSE 80

# 启动 Nginx（-g daemon off 以前台模式运行，Docker 必须）
CMD ["nginx", "-g", "daemon off;"]
