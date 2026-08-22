# 在 LangChain 中自定义工具（Python 指南）

> 本文示例代码部分位于 `backend/mcp_service/langchain/compute_tool.py`
>
> 参考链接：<https://python.langchain.ac.cn/docs/how_to/custom_tools/>

---

## 1. 环境准备

```bash
pip install langchain
```

---

## 2. 使用 `@tool` 装饰器

最简便的方式：直接在普通函数上加 `@tool`。LangChain 会自动把该函数包装成可在 Agent/链中调用的 **Tool**。

```python
@tool
def add(a: int, b: int) -> int:
    """计算两数之和"""
    return a + b
```

### 解析要点
1. **函数签名** 决定了工具的参数。
2. **函数注释/文档字符串** 会成为工具的描述，帮助 LLM 选择合适工具。

---

## 3. 带参数注解与 `parse_docstring`

可以在参数上写注解或让 LangChain 解析 docstring 生成更丰富的提示。

```python
@tool(parse_docstring=True)

def subtraction(a: int, b: int) -> int:
    """计算两数差

    Args:
        a (int): 被减数
        b (int): 减数
    """
    return a - b
```

- `parse_docstring=True` 让 LangChain 读取 `Args:` 中的说明，效果等同于在参数上加 `Annotated`。

---

## 4. 自定义输入模型 (`args_schema`)

当参数较多或需要更复杂的校验时，推荐用 **Pydantic** 定义输入。

```python
class DivisionInput(BaseModel):
    num1: int = Field(description="被除数")
    num2: int = Field(description="除数")

@tool("division", args_schema=DivisionInput)

def division(num1: int, num2: int) -> float:
    """返回 num1 / num2"""
    return num1 / num2
```

好处：
- 自动生成 JSON Schema → 工具调用更精准。
- 自带类型和边界校验。

---

## 5. 使用 `StructuredTool.from_function`

如果想更加细粒度地控制工具（如同步/异步实现、是否直接返回给用户等），可以使用 `StructuredTool`：

```python
def exponentiation_func(num: int, power: int) -> int:
    """计算 num 的 power 次幂"""
    return num ** power

exponentiation = StructuredTool.from_function(
    func=exponentiation_func,
    name="exponentiation",
    description="计算指数",
    args_schema=ExponentiationInput,
    return_direct=True,  # 工具结果是否直接流向最终输出
    # coroutine= ... <- you can specify an async method if desired as well
)
```

参数说明：
- `name` / `description`：用于提示 LLM 选用该工具。
- `args_schema`：同样用 Pydantic 定义输入参数。
- `return_direct=True`：若为 `True`，工具输出将直接返回给用户，而不是再交由 LLM 总结。
- `coroutine`：可指定一个异步函数（`async def`），在异步环境下由 LangChain 调用；如果未提供，则默认调用同步 `func`。

---

## 6. 子类化 `BaseTool`（进阶）

当需要完全自定义同步/异步执行逻辑或返回内容 + 产物（artifact）时，可继承 `BaseTool`。

```python
from langchain_core.tools import BaseTool
from typing import Tuple, List

class GenerateRandomFloats(BaseTool):
    name = "generate_random_floats"
    description = "生成随机浮点数数组"
    response_format = "content_and_artifact"  # 同时返回文本与产物

    ndigits: int = 2  # 自定义属性

    def _run(self, min: float, max: float, size: int) -> Tuple[str, List[float]]:
        import random, math
        arr = [round(random.uniform(min, max), self.ndigits) for _ in range(size)]
        content = f"已生成 {size} 个随机数，在区间 [{min}, {max}] 内。"
        return content, arr

random = GenerateRandomFloats()
```

> **提示**：若想支持异步，额外实现 `_arun` 方法。

---

## 7. 错误处理

LangChain 允许在工具层自定义错误处理逻辑，示例：

```python
def _handle_error(error: ToolException) -> str:
    return f"工具执行出错：{error.args[0]}"

get_weather_tool = StructuredTool.from_function(
    func=get_weather,
    handle_tool_error=_handle_error,
)
```

---

## 8. 返回 **content 与 artifact**（可选）

- **content**：发送给模型的自然语言描述。
- **artifact**：保存在链上下文，可供后续工具调用或展示，但不会被模型直接看到。

只需在工具定义时加入 `response_format="content_and_artifact"` 并返回 `(content, artifact)` 二元组即可。

```python
@tool(response_format="content_and_artifact")

def generate_random_ints(min: int, max: int, size: int):
    import random
    arr = [random.randint(min, max) for _ in range(size)]
    return f"生成了 {size} 个随机整数。", arr
```

---

## 9. 将工具接入 Agent / Chain

```python
from langchain_openai import ChatOpenAI
from langchain.agents import AgentExecutor, create_openai_functions_agent

llm = ChatOpenAI(model_name="gpt-4o-mini")

tools = [add, subtraction, multiply, division, exponentiation]

agent = create_openai_functions_agent(llm, tools)
agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=True)

# 体验
agent_executor.invoke({"input": "帮我计算 3 的 5 次方是多少？"})
```

运行日志中你将看到：
1. LLM 通过工具描述决定调用 `exponentiation`。
2. 工具执行后直接返回 `243`。
3. Agent 将结果展示给用户。

---

## 10. 小结

1. `@tool` → 快速上手。
2. `args_schema` + Pydantic → 精准、可校验的输入。
3. `StructuredTool` / `BaseTool` → 进阶控制，如异步、错误处理、artifact 返回。
4. **清晰的 `name` / `description` / 参数说明** 是让 LLM 正确选用工具的关键。

希望本指南能帮助你快速在自己的 LangChain 应用中，创建并集成自定义工具。祝编程愉快！
