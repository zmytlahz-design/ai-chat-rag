# Function Calling 多工具编排的闭环实现

当 LLM 需要「查知识库、算数、查天气、调 API」等多种能力时，单靠一个 RAG 或固定流程不够用，需要由模型自己决定**何时调用哪个工具、传什么参数**。OpenAI 的 **Function Calling**（以及兼容接口的 `tools` / `tool_choice`）就是为此设计的。本文给出一个**多工具编排的闭环实现**：从工具定义、绑定、到「调用 → 执行 → 再调用」的循环，直到模型不再请求工具并返回最终回答。

---

## 一、目标行为

- 用户输入一句话，模型可以：
  - 直接回答；或
  - 输出一个或多个 **tool_calls**（名称 + 参数）。
- 后端执行对应工具，把结果以 **tool result** 形式追加回对话。
- 再次调用模型，模型可以继续发起 tool_calls，或给出最终 **Answer**。
- 循环直到：没有 tool_calls，或达到最大轮数（防死循环）。

这就是「闭环」：**模型 → 工具 → 模型 → … → 最终回复**。

---

## 二、工具定义（OpenAI 风格 Schema）

每个工具需要：**名字**、**描述**（给模型看）、**参数 schema**（JSON Schema）。例如：

```python
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_kb",
            "description": "在知识库中检索与问题相关的文档片段，用于回答基于文档的问题。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "检索关键词或问题"}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "查询指定城市的当前天气。",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "城市名称，如北京、上海"}
                },
                "required": ["city"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "calculator",
            "description": "执行数学表达式计算，如 2+3*4。",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {"type": "string", "description": "数学表达式，仅数字与 +-*/()"}
                },
                "required": ["expression"]
            }
        }
    }
]
```

模型会根据 `description` 和 `parameters` 决定是否调用、以及传什么参数。

---

## 三、工具实现与映射

在服务端维护「名字 → 可调用对象」的映射，便于按 `tool_call.id` 和 `name` 执行：

```python
def search_kb(query: str) -> str:
    # 实际项目中这里调 rag_service 或 vector_store
    return f"检索结果（query={query}）：..."

def get_weather(city: str) -> str:
    # 实际可调天气 API
    return f"{city}：晴，15-25°C"

def calculator(expression: str) -> str:
    try:
        # 仅允许数字与四则运算，避免 eval 风险
        allowed = set("0123456789+-*/(). ")
        if not all(c in allowed for c in expression):
            return "非法表达式"
        return str(eval(expression))
    except Exception as e:
        return f"计算错误: {e}"

TOOL_IMPLS = {
    "search_kb": search_kb,
    "get_weather": get_weather,
    "calculator": calculator,
}
```

---

## 四、消息格式（OpenAI 兼容）

一轮对话中，除了 `system` / `user` / `assistant`，还要支持：

- **assistant** 消息里带 `tool_calls`：`[{ "id": "xxx", "type": "function", "function": { "name": "...", "arguments": "{\"query\":\"...\"}" } }]`
- **tool** 消息：`role="tool"`, `content` 为工具返回字符串，并带 `tool_call_id` 与之一一对应。

这样模型下次看到的是「你调了 A/B，结果是 …」，再决定继续调工具还是直接回答。

---

## 五、闭环循环（核心逻辑）

下面用「OpenAI 兼容 API」的伪代码写出闭环，不依赖 LangChain，方便接到任意兼容 `tools` / `tool_choice` 的 SDK。

```python
import json

def run_tool_loop(user_message: str, max_rounds: int = 5) -> str:
    messages = [
        {"role": "system", "content": "你是一个助手，可以调用工具。根据工具结果回答用户；若无需工具则直接回答。"},
        {"role": "user", "content": user_message}
    ]
    
    for round in range(max_rounds):
        response = client.chat.completions.create(
            model="gpt-4",
            messages=messages,
            tools=TOOLS,
            tool_choice="auto"
        )
        choice = response.choices[0]
        msg = choice.message
        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": getattr(msg, "tool_calls", None) or []
        })
        
        if not msg.tool_calls:
            return (msg.content or "").strip()
        
        for tc in msg.tool_calls:
            name = tc.function.name
            args = json.loads(tc.function.arguments)
            try:
                result = TOOL_IMPLS[name](**args)
            except Exception as e:
                result = f"工具执行错误: {e}"
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result
            })
    
    return "达到最大轮数，请简化问题或稍后重试。"
```

要点：

- 每次请求都带同一份 `tools` 和 `tool_choice="auto"`（由模型决定是否调用）。
- 若有 `tool_calls`，把每条 `tool` 消息按 `tool_call_id` 对应好，再请求一次。
- 若没有 `tool_calls`，当前 `msg.content` 即为最终答案，退出循环。
- `max_rounds` 防止无限递归（例如模型一直重复调用同一工具）。

---

## 六、流式输出时的注意点

若希望「边生成边返回」：

- **只流最后一轮**：前面几轮是「模型要调工具 → 执行工具 → 再调」，通常不需要把中间轮的 token 流给用户；只在「最后一轮、且没有 tool_calls」时，对该轮用 `stream=True`，把 `delta.content` 推给前端。
- **或每轮都流**：若产品希望用户看到「正在调用 search_kb…」之类的中间状态，可以在每轮先推送「调用工具 X」，再在下一轮推送该轮的文字；实现上要区分「当前消息是带 tool_calls 还是纯 content」。

无论哪种，**tool 结果必须完整写入 messages 再发起下一轮**，否则模型拿不到上下文。

---

## 七、与本仓库 RAG 的结合方式

当前 [ai-chat-rag](.) 是「固定三步 RAG」：Condense → Retrieve → Generate，没有工具选择。若要在现有系统上做多工具编排，可以：

1. 把「知识库检索」做成一个工具 `search_kb(kb_id, query)`，内部调现有 `rag_service` 的检索（或只检索不生成），把检索到的文本作为 tool result 返回。
2. 在对话入口判断：若开启「多工具模式」，则走上面的 `run_tool_loop`，并把 `search_kb` 和 `get_weather`、`calculator` 等一起注册；否则仍走现有 RAG 三步流。

这样既保留现有 RAG 的稳定表现，又能在同一套对话里支持多工具闭环。

---

## 八、小结

| 步骤         | 说明 |
|--------------|------|
| 工具定义     | OpenAI 风格 `type: "function"` + name/description/parameters |
| 工具实现     | 名字 → 可调用对象映射，执行后返回字符串 |
| 消息结构     | assistant 可带 tool_calls；tool 消息带 tool_call_id + content |
| 闭环         | 循环：LLM → 若有 tool_calls 则执行并追加 tool 消息 → 再调 LLM，直到无 tool_calls 或超轮 |
| 安全与鲁棒   | 最大轮数、参数校验、工具内 try/except，避免死循环与注入 |

按上述方式即可实现「Function Calling 多工具编排的闭环」；再结合 [《手搓 ReAct Agent 和 LangChain 的实现对比》](./手搓-ReAct-Agent-和-LangChain-的实现对比.md) 和 [《RAG 全链路落地踩坑记录》](./RAG-全链路落地踩坑记录.md)，可以从 RAG 到 Agent、从单流程到多工具逐步扩展。
