# Custom Tools in LangChain (Python Guide)

> Example code can be found in `backend/mcp_service/langchain/compute_tool.py`
>
> Reference: <https://python.langchain.ac.cn/docs/how_to/custom_tools/>

---

## 1. Environment Setup

```bash
pip install langchain
```

---

## 2. Using the `@tool` Decorator

The quickest way to turn a regular Python function into a LangChain **Tool** is to add the `@tool` decorator. LangChain will automatically expose the function to Agents/Chains.

```python
@tool
def add(a: int, b: int) -> int:
    """Return the sum of two integers"""
    return a + b
```

### Key Points

1. The **function signature** determines the tool's parameters.
2. The **docstring** becomes the tool description—critical for the LLM to pick the right tool.

---

## 3. Parameter Annotations & `parse_docstring`

You can add rich descriptions via type annotations or let LangChain parse the docstring.

```python
@tool(parse_docstring=True)

def subtraction(a: int, b: int) -> int:
    """Subtract two numbers.

    Args:
        a (int): minuend
        b (int): subtrahend
    """
    return a - b
```

- With `parse_docstring=True`, LangChain reads the **Args:** section—equivalent to using `Annotated`.

---

## 4. Custom Input Schema (`args_schema`)

For many or complex parameters, define a Pydantic model and attach it via `args_schema`.

```python
class DivisionInput(BaseModel):
    num1: int = Field(description="dividend")
    num2: int = Field(description="divisor")

@tool("division", args_schema=DivisionInput)

def division(num1: int, num2: int) -> float:
    """Return num1 / num2"""
    return num1 / num2
```

Benefits:

- Automatically generates a JSON schema → more accurate tool calls.
- Built-in type validation.

---

## 5. Using `StructuredTool.from_function`

Need finer control (sync/async, direct return, etc.)? Use `StructuredTool` directly.

```python
def exponentiation_func(num: int, power: int) -> int:
    """Return *num* raised to *power*"""
    return num ** power

exponentiation = StructuredTool.from_function(
    func=exponentiation_func,
    name="exponentiation",
    description="Calculate exponentiation",
    args_schema=ExponentiationInput,
    return_direct=True,  # whether the result is returned to the user directly
    coroutine=...,       # specify an async implementation if desired
)
```

Explanation of arguments:

- `name` / `description`: shown to the LLM when deciding which tool to call.
- `args_schema`: same Pydantic model approach as above.
- `return_direct=True`: if `True`, the tool output bypasses the LLM and is returned as-is.
- `coroutine`: supply an **async** version (`async def`) of the tool for async environments; defaults to the sync `func` if omitted.

---

## 6. Subclassing `BaseTool` (Advanced)

For full control over sync/async execution or when you need to return both a user-visible message and an internal artifact, subclass `BaseTool`.

```python
from langchain_core.tools import BaseTool
from typing import Tuple, List

class GenerateRandomFloats(BaseTool):
    name = "generate_random_floats"
    description = "Generate an array of random floats"
    response_format = "content_and_artifact"  # return text + artifact

    ndigits: int = 2  # custom attribute

    def _run(self, min: float, max: float, size: int) -> Tuple[str, List[float]]:
        import random
        arr = [round(random.uniform(min, max), self.ndigits) for _ in range(size)]
        content = f"Generated {size} random floats in the range [{min}, {max}]."
        return content, arr

# instantiate if desired
random_floats_tool = GenerateRandomFloats()
```

> **Tip:** Implement `_arun` for an async version.

---

## 7. Error Handling

You can attach custom error handling logic to a tool.

```python
def _handle_error(error: ToolException) -> str:
    return f"Tool error: {error.args[0]}"

get_weather_tool = StructuredTool.from_function(
    func=get_weather,
    handle_tool_error=_handle_error,
)
```

---

## 8. Returning **content** & **artifact** (Optional)

- **content**: human-readable text sent back to the model.
- **artifact**: kept in the chain context for later tools or UI but hidden from the model itself.

```python
@tool(response_format="content_and_artifact")

def generate_random_ints(min: int, max: int, size: int):
    import random
    arr = [random.randint(min, max) for _ in range(size)]
    return f"Generated {size} random integers.", arr
```

---

## 9. Plugging Tools into an Agent / Chain

```python
from langchain_openai import ChatOpenAI
from langchain.agents import AgentExecutor, create_openai_functions_agent

llm = ChatOpenAI(model_name="gpt-4o-mini")

tools = [add, subtraction, multiply, division, exponentiation]

agent = create_openai_functions_agent(llm, tools)
agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=True)

# Try it out
a gent_executor.invoke({"input": "What is 3 to the power of 5?"})
```

You should see something like:

1. The LLM decides to call `exponentiation` based on tool descriptions.
2. The tool returns `243`.
3. The agent relays the result to the user.

---

## 10. Recap

1. `@tool` → quickest path to a tool.
2. `args_schema` + Pydantic → validated, well-described parameters.
3. `StructuredTool` / `BaseTool` → advanced control (async, error handling, artifacts).
4. Clear `name`, `description`, and parameter docs are key for the LLM to choose the right tool.

Happy building with LangChain! 🎉
