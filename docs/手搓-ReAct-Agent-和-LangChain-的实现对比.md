# 手搓 ReAct Agent 和 LangChain 的实现对比

## 一、ReAct 是什么

ReAct（Reasoning + Acting）是一种让大模型「边推理边行动」的范式：模型先给出**思考（Thought）**，再决定**行动（Action）**（如调用工具），拿到**观察（Observation）**后继续推理，直到得出最终答案。典型流程如下：

```
用户：北京今天天气怎么样？
Thought: 需要查天气
Action: get_weather(city="北京")
Observation: 晴，15-25°C
Thought: 已有足够信息
Answer: 北京今天晴天，气温 15-25°C。
```

手搓一套 ReAct 循环，和直接使用 LangChain 的 `create_react_agent` / `AgentExecutor`，在可控性、流式、定制化上差异很大。下面用精简代码对比两种实现方式。

---

## 二、手搓 ReAct：最小闭环

核心就是一个 **while 循环**：每次把「历史消息 + 当前问题」交给 LLM，解析输出里的 `Thought / Action / Observation`，若有工具调用就执行并把结果拼回消息，再继续下一轮，直到模型输出 `Answer` 或达到最大步数。

### 2.1 约定输出格式

让模型按固定格式输出，便于用正则或简单解析提取：

```python
REACT_PROMPT = """你是一个助手，可以调用工具。请按以下格式回答：

Thought: <你的推理>
Action: <工具名>(<JSON 参数>)
Observation: <工具返回会由系统填充>

当可以给出最终答案时：
Thought: 已有足够信息
Answer: <给用户的最终回答>

可用工具：
- get_weather(city: str): 查询城市天气
- search_kb(query: str): 在知识库中检索
"""
```

### 2.2 手搓循环（伪代码）

```python
def run_react_handcrafted(user_query: str, tools: dict, max_steps: int = 5) -> str:
    messages = [{"role": "user", "content": REACT_PROMPT + "\n\n用户问题：" + user_query}]
    
    for step in range(max_steps):
        response = llm.invoke(messages)
        text = response.content
        
        # 解析 Thought / Action / Answer
        if "Answer:" in text:
            return extract_after(text, "Answer:").strip()
        
        action_name, action_args = parse_action(text)  # 从 "Action: get_weather(...)" 解析
        if not action_name or action_name not in tools:
            return "无法解析或执行工具，请重试。"
        
        observation = tools[action_name](**action_args)
        messages.append({"role": "assistant", "content": text})
        messages.append({"role": "user", "content": f"Observation: {observation}"})
    
    return "达到最大步数，未得到最终答案。"
```

特点：

- **完全掌控**：Prompt 格式、解析逻辑、何时停止、错误处理都可以自己定。
- **流式**：若 LLM 支持流式，可以在每轮把 `response.content` 边收边推给前端。
- **缺点**：依赖模型「听话」地按格式输出，格式不稳定时需要更鲁棒的解析或重试。

---

## 三、LangChain 的 ReAct Agent

LangChain 把「Prompt 设计 + 输出解析 + 工具执行 + 循环」封装成 `create_react_agent` 和 `AgentExecutor`，工具用 `@tool` 或 `StructuredTool` 定义，模型通过 **Function Calling** 或 **ReAct 文本解析** 选择工具。

### 3.1 用 LangChain 写一版

```python
from langchain.agents import create_react_agent, AgentExecutor
from langchain_core.tools import tool
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

@tool
def get_weather(city: str) -> str:
    """查询指定城市的天气。"""
    return f"{city}：晴，15-25°C"

@tool
def search_kb(query: str) -> str:
    """在知识库中检索与 query 相关的内容。"""
    return "检索结果：..."

llm = ChatOpenAI(model="gpt-4", temperature=0)
tools = [get_weather, search_kb]
prompt = ChatPromptTemplate.from_messages([("system", REACT_SYSTEM), ("human", "{input}")])

agent = create_react_agent(llm, tools, prompt)
agent_executor = AgentExecutor(agent=agent, tools=tools, max_iterations=5, verbose=True)
result = agent_executor.invoke({"input": "北京今天天气怎么样？"})
```

特点：

- **开箱即用**：不用自己写解析和循环，只要定义 `tools` 和 Prompt。
- **统一工具接口**：`@tool` 自动生成 schema，和 Function Calling 兼容性好。
- **缺点**：流式支持不如手搓灵活（通常拿到的是整轮输出）；若要把 `chat_history`、自定义中间状态塞进每一步，需要改框架或自己包一层。

---

## 四、对比小结

| 维度         | 手搓 ReAct                         | LangChain ReAct Agent                    |
|--------------|------------------------------------|------------------------------------------|
| 控制力       | 完全可控：格式、解析、终止、流式   | 受限于 AgentExecutor 的循环与接口       |
| 流式         | 可按 token 或按轮流式              | 多为按轮或需自己接底层 LLM 流式          |
| 多轮/历史    | 自己维护 `messages`，想怎么加都行 | 需看是否支持 memory / chat_history 注入 |
| 开发成本     | 需写解析、工具调用、错误处理       | 定义 tools + prompt 即可                  |
| 稳定性       | 依赖模型按格式输出                 | 若用 Function Calling，输出更结构化     |

---

## 五、和「固定 RAG 三步」的关系

在 [本仓库](.) 的 RAG 实现里，我们**没有**用完整的 ReAct Agent，而是采用了**固定的三步链路**（问题浓缩 → 检索 → 生成），等价于 LangChain 的 `ConversationalRetrievalChain` 内部逻辑，但全部手写以实现：

- 在最终 QA 的 Prompt 里同时注入 `context` 和 `chat_history`（ConversationalRetrievalChain 默认不支持把历史传给最后一步）；
- 全链路 **async + 流式**，方便 SSE 逐 token 推给前端。

也就是说：**我们把「检索」当成唯一且固定的“工具”，不交给模型做“选不选、选哪个”的决策**。这样实现简单、行为可预期，适合「纯知识库问答」场景。若你希望模型在「检索 / 算数 / 查天气 / 调 API」之间自由选择，再考虑上 ReAct 或 Function Calling 多工具编排会更合适。

---

## 六、总结

- **手搓 ReAct**：适合对控制力、流式、多轮和 Prompt 格式有强需求的场景，代价是解析与循环都要自己写。
- **LangChain ReAct Agent**：适合快速搭一个可用的工具调用 Agent，工具多、希望少写样板代码时用。
- **固定 RAG 三步**：不做「选工具」的 Agent，只做「固定流程的检索 + 生成」，是当前仓库的选择，简单且易维护。

如果你打算在现有 RAG 上增加「多工具编排」，可以再结合 [《Function Calling 多工具编排的闭环实现》](./Function-Calling-多工具编排的闭环实现.md) 一起看。
