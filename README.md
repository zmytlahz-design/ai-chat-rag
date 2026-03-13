# AI 知识库对话系统
<img width="1920" height="945" alt="image" src="https://github.com/user-attachments/assets/29718453-55c4-4687-8cd3-da7074472388" />

基于 RAG（检索增强生成）技术的多轮对话知识库系统。上传 PDF/TXT/Markdown 文档，通过向量检索 + LLM 实现智能问答，支持多知识库管理、对话历史、SSE 流式输出和多级 Redis 缓存。

## 技术栈

| 层级 | 技术选型 |
|------|---------|
| 后端框架 | Python 3.11 + FastAPI（异步）|
| 前端框架 | React 18 + TypeScript + Vite |
| UI 样式 | Tailwind CSS |
| 状态管理 | Zustand |
| 向量数据库 | PostgreSQL 15 + pgvector 扩展 |
| 缓存 | Redis 7（语义缓存 + 精确缓存 + 热门统计）|
| ORM | SQLAlchemy 2.x（asyncpg 异步驱动）|
| LLM | DeepSeek API（OpenAI 兼容格式）|
| Embedding | 智谱 AI / DeepSeek（OpenAI 兼容）|
| RAG 框架 | LangChain + langchain-postgres（PGVector）|
| 流式传输 | SSE（Server-Sent Events）|
| 部署 | Docker + docker-compose + Nginx |

## 快速启动

### 前置条件

- Docker >= 24.0
- docker-compose >= 2.20（Compose V2）
- 有效的 LLM API Key（DeepSeek / 智谱 / OpenAI 等）

### 1. 克隆项目

```bash
git clone <repository-url>
cd ai-chat-rag
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`，至少填写以下必填项：

```env
POSTGRES_PASSWORD=your_strong_password    # 数据库密码
LLM_API_KEY=sk-your-api-key              # LLM 接口密钥
EMBEDDING_API_KEY=sk-your-api-key        # Embedding 接口密钥
```

### 3. 一键启动

```bash
docker-compose up -d
```

首次启动会自动：
- 拉取 `pgvector/pgvector:pg15`、`redis:7-alpine`、`nginx:1.25-alpine` 镜像
- 构建后端（Python 依赖约需 2-3 分钟）
- 构建前端（Node.js 编译约需 1-2 分钟）
- 等待 PostgreSQL 和 Redis 健康就绪后再启动后端

### 4. 访问服务

默认端口为 **3080**（可在 `.env` 中设置 `NGINX_PORT`）。若使用默认配置：

| 地址 | 说明 |
|------|------|
| http://localhost:3080 | 前端界面（React）|
| http://localhost:3080/api/v1/docs | FastAPI 交互文档（Swagger UI）|
| http://localhost:3080/api/v1/redoc | FastAPI 文档（ReDoc）|
| http://localhost:3080/health | Nginx 健康检查 |

### 5. 常用命令

```bash
# 查看所有服务状态
docker-compose ps

# 查看实时日志（所有服务）
docker-compose logs -f

# 只看后端日志
docker-compose logs -f backend

# 重新构建并启动（修改代码后）
docker-compose up -d --build

# 停止所有服务（保留数据）
docker-compose down

# 停止并清除所有数据（慎用！）
docker-compose down -v

# 进入后端容器调试
docker exec -it rag_backend bash

# 进入数据库
docker exec -it rag_postgres psql -U rag_user -d rag_db
```

### 6. 初始化使用

1. 打开 http://localhost:3080（或你配置的端口）
2. 点击"知识库管理" → 创建第一个知识库
3. 进入"文档管理" → 拖拽上传 PDF/TXT/MD 文件
4. 等待文档处理完成（状态变为"已完成"）
5. 回到主页面开始对话

### 7. 将本项目上传到 GitHub

本地已初始化 Git 并完成首次提交后，按以下步骤推到 GitHub：

1. 在 [GitHub](https://github.com/new) 新建仓库（Repository name 如 `ai-chat-rag`，可设为 Public，**不要**勾选 “Add a README”）。
2. 在项目根目录执行（将 `YOUR_USERNAME` 和 `ai-chat-rag` 换成你的用户名和仓库名）：

```bash
git remote add origin https://github.com/YOUR_USERNAME/ai-chat-rag.git
git push -u origin main
```

若使用 SSH：

```bash
git remote add origin git@github.com:YOUR_USERNAME/ai-chat-rag.git
git push -u origin main
```

---

## 项目结构

```
ai-chat-rag/
├── docker-compose.yml          # 5 服务编排配置
├── .env.example                # 环境变量模板（复制为 .env 后填写）
├── .gitignore
├── README.md
│
├── backend/                    # FastAPI 后端
│   ├── main.py                 # 应用入口，注册路由和中间件
│   ├── config.py               # pydantic-settings 配置（读取 .env）
│   ├── database.py             # SQLAlchemy 异步数据库连接
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── models/                 # ORM 数据库模型
│   │   ├── knowledge_base.py   # 知识库表
│   │   ├── document.py         # 文档表（含处理状态）
│   │   ├── conversation.py     # 对话表
│   │   └── message.py          # 消息表
│   ├── routers/                # API 路由层
│   │   ├── knowledge_base.py   # 知识库 CRUD + 热门问题 + 缓存管理
│   │   ├── document.py         # 文档上传/列表/删除
│   │   ├── chat.py             # 流式对话 + 普通对话
│   │   └── conversation.py     # 对话历史管理
│   └── services/               # 业务逻辑层
│       ├── document_service.py # 文档解析 → 切块 → 向量化 → 存储
│       ├── rag_service.py      # RAG 链路（问题压缩 + 检索 + LLM 生成）
│       ├── chat_service.py     # 对话管理 + 多级缓存调度
│       └── redis_service.py    # 精确缓存 + 语义缓存 + 热门统计
│
├── frontend/                   # React 前端
│   ├── Dockerfile              # 多阶段构建（Node → Nginx）
│   ├── nginx.conf              # 前端容器 Nginx 配置（SPA 路由回退）
│   ├── package.json
│   ├── vite.config.ts          # Vite 配置（开发代理）
│   └── src/
│       ├── api/                # HTTP 请求层
│       ├── hooks/              # 自定义 Hooks（useSSE / useAutoScroll）
│       ├── utils/              # 工具函数（Markdown 渲染配置）
│       ├── stores/             # Zustand 状态管理
│       ├── components/         # 可复用组件
│       ├── pages/              # 页面组件
│       └── router/             # React Router 路由配置
│
└── nginx/
    └── nginx.conf              # 外层反向代理配置（统一入口）
```

---

## API 接口文档概览

> 完整交互文档：http://localhost/api/v1/docs

### 知识库管理 `/api/v1/knowledge-bases`

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 获取知识库列表（分页）|
| POST | `/` | 创建知识库 |
| GET | `/{kb_id}` | 获取知识库详情 |
| PUT | `/{kb_id}` | 更新知识库信息 |
| DELETE | `/{kb_id}` | 删除知识库（含文档和对话）|
| GET | `/{kb_id}/hot-questions` | 热门问题 Top-N |
| DELETE | `/{kb_id}/hot-questions` | 重置热门问题统计 |
| DELETE | `/{kb_id}/cache` | 清空 RAG 答案缓存 |

### 文档管理 `/api/v1/documents`

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/upload` | 上传文档（multipart/form-data，异步处理）|
| GET | `/kb/{kb_id}` | 获取知识库下的文档列表 |
| GET | `/{doc_id}` | 查询文档详情（用于轮询处理状态）|
| DELETE | `/{doc_id}` | 删除文档及其向量数据 |

### 对话接口 `/api/v1/chat`

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/stream` | **流式对话**（SSE，逐 token 推送）|
| POST | `/normal` | 普通对话（等待完整响应）|

**流式对话请求体：**
```json
{
  "kb_id": 1,
  "question": "这个知识库的主要内容是什么？",
  "conversation_id": null
}
```

**SSE 事件格式：**
```
data: {"type": "start", "conversation_id": 5}
data: {"type": "token", "content": "根"}
data: {"type": "token", "content": "据"}
data: {"type": "done", "conversation_id": 5, "message_id": 23, "sources": [...], "from_cache": false}
```

### 对话历史 `/api/v1/conversations`

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 获取对话列表（按 kb_id 过滤）|
| GET | `/{conv_id}` | 获取对话详情（含消息列表）|
| PUT | `/{conv_id}` | 更新对话标题 |
| DELETE | `/{conv_id}` | 删除对话及消息 |

---

## 缓存策略说明

系统实现三级缓存，按优先级依次命中：

```
用户提问
    ↓
L1 精确缓存（Redis String，MD5 hash，TTL 24h）
    ↓ 未命中
L2 语义缓存（Redis Hash，余弦相似度 > 0.95，TTL 24h）
    ↓ 未命中
L3 RAG 完整链路（向量检索 + DeepSeek LLM）
    ↓ 生成后存入 L1 + L2
```

- **L1 精确匹配**：完全相同的问题直接命中，响应 < 10ms
- **L2 语义相似**：语义近似的问题命中，避免重复调用 LLM
- **热门问题统计**：使用 Redis Sorted Set 记录问题频次，提供 Top-N 分析

---

## 开发模式启动

不使用 Docker，本地直接运行：

```bash
# 后端（需要本地 Python 3.11 + PostgreSQL + Redis）
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# 前端（另开终端）
cd frontend
npm install
npm run dev   # 访问 http://localhost:5173
# Vite 会自动将 /api 代理到 http://localhost:8000
```

---

## 环境变量说明

| 变量名 | 必填 | 默认值 | 说明 |
|--------|------|--------|------|
| `POSTGRES_PASSWORD` | ✅ | — | 数据库密码 |
| `POSTGRES_USER` | | `rag_user` | 数据库用户名 |
| `POSTGRES_DB` | | `rag_db` | 数据库名 |
| `REDIS_PASSWORD` | | 空（不认证）| Redis 密码 |
| `LLM_API_KEY` | ✅ | — | LLM API 密钥 |
| `LLM_BASE_URL` | | DeepSeek | LLM 接口地址 |
| `LLM_MODEL` | | `deepseek-chat` | LLM 模型名 |
| `EMBEDDING_API_KEY` | ✅ | — | Embedding API 密钥 |
| `EMBEDDING_BASE_URL` | | 智谱 AI | Embedding 接口地址 |
| `EMBEDDING_MODEL` | | `embedding-3` | Embedding 模型名 |
| `NGINX_PORT` | | `80` | 对外暴露端口 |
| `CHUNK_SIZE` | | `500` | 文档分块大小（字符数）|
| `CHUNK_OVERLAP` | | `50` | 分块重叠大小（字符数）|

---

## 常见问题

**Q: 后端启动失败，日志显示数据库连接错误？**
> 等待 postgres 完全就绪后重试：`docker-compose restart backend`

**Q: 上传文档后状态一直是"处理中"？**
> 检查 Embedding API 配置是否正确：`docker-compose logs backend | grep -i embedding`

**Q: SSE 流式对话没有逐字效果，一次性返回？**
> 检查是否在 Nginx 和浏览器之间有额外代理开启了缓冲。生产环境确认 `proxy_buffering off` 生效。

**Q: 80 端口被占用？**
> 在 `.env` 中设置 `NGINX_PORT=8080`，然后重启：`docker-compose up -d`
