# Nexent 工具开发规范

本文档基于对现有工具的分析，总结了 Nexent SDK 中工具开发的完整规范和最佳实践。

## 📂 工具分类

当前 SDK 包含以下工具类型：

### 搜索工具
- **ExaSearchTool**: 基于 EXA API 的网络搜索工具
- **TavilySearchTool**: 基于 Tavily API 的网络搜索工具
- **LinkupSearchTool**: 基于 Linkup API 的搜索工具
- **KnowledgeBaseSearchTool**: 本地知识库搜索工具
- **RAGFlowSearchTool**: RAGFlow 知识检索
- **HaotianSearchTool / IndependentAidpSearchTool / AidpSearchTool / DifySearchTool / DataMateSearchTool / IdataSearchTool**: 企业级检索源接入

### 文件管理工具
- **CreateFileTool**: 创建包含内容的新文件
- **ReadFileTool**: 从文件系统读取文件内容
- **DeleteFileTool**: 从文件系统删除文件
- **MoveItemTool**: 移动或重命名文件和目录
- **CreateDirectoryTool**: 创建新目录
- **DeleteDirectoryTool**: 删除目录及其内容
- **ListDirectoryTool**: 列出目录内容和详细信息

### 系统工具
- **TerminalTool**: 执行 shell 命令和系统操作

### 通信工具
- **GetEmailTool**: 通过 IMAP 的邮件获取工具
- **SendEmailTool**: 通过 SMTP 的邮件发送工具

### 多模态工具
- **AnalyzeTextFileTool**: 基于数据处理和大语言模型的文档问答工具
- **AnalyzeImageTool**: 基于视觉语言模型的图片问答工具
- **AnalyzeAudioTool**: 基于语音模型的音频理解工具
- **AnalyzeVideoTool**: 基于视觉语言模型的视频理解工具

### 记忆工具
- **StoreMemoryTool**: 将重要信息存入当前 Agent 短期记忆（MemoryLayer.AGENT + SHORT_TERM），每次运行最多存储 3 条
- **SearchMemoryTool**: 按自然语言查询检索当前 Agent 记忆，top_k 默认 5

### 编排工具
- **ParallelExecutorTool**: 并发执行多个子 Agent
- **CreatePlanTool / UpdatePlanStepTool**: 规划待办的创建与更新

### 数据工具
- **MySqlTool / PostgreSqlTool / MsSqlTool**: 对数据库执行受控 SQL 查询
- **UploadToS3Tool / DownloadFromS3Tool**: S3 对象上传与下载

### 技能与任务工具（系统内部管理）
- **ReadSkillConfigTool / ReadSkillMdTool**: 读取技能目录下的 config.yaml 与 SKILL.md
- **RunSkillScriptTool**: 执行技能脚本
- **WriteSkillFileTool**: 向租户隔离的技能目录写入文件
- **CreateScheduledTaskProposalTool**: 创建待用户确认的定时任务提案（仅保存提案，不执行业务任务）

> 注：以上工具由系统内部管理，未在 `nexent.core.tools` 的 `__init__.py` 中统一导出。

## 🔧 工具共性特征

### 1. 基础架构
- **基类继承**: 所有工具必须继承自 `smolagents.tools.Tool`
- **参数管理**: 使用 `pydantic.Field` 进行参数定义和验证
- **流式输出**: 集成 `MessageObserver` 支持实时消息传递
- **多语言支持**: 内置中英文双语提示信息

### 2. 核心属性
每个工具类必须包含以下类属性：

```python
class ToolExample(Tool):
    name = "tool_name"                     # 工具唯一标识符
    description = "Tool function description"  # 详细功能说明（英文）
    description_zh = "工具功能描述"        # 详细功能说明（中文）
    inputs = {                             # 输入参数定义
        "param": {
            "type": "string",
            "description": "Parameter description",
            "description_zh": "参数描述"
        }
    }
    init_param_descriptions = {            # 构造参数说明（与 __init__ 参数对应）
        "config_param": {"description": "Config parameter description", "description_zh": "配置参数说明"}
    }
    output_type = "string"                 # 输出类型
    category = "search"                    # 工具分类（ToolCategory 枚举值）
    tool_sign = "b"                        # 工具标识符（ToolSign 枚举值）
```

### 3. 消息处理机制
- **ProcessType 枚举**: 使用不同类型区分消息（TOOL, CARD, SEARCH_CONTENT, PICTURE_WEB 等）
- **Observer 模式**: 通过 MessageObserver 实现实时消息推送
- **JSON 格式**: 所有消息内容使用 JSON 格式确保一致性
- **运行状态消息统一发送**: `ProcessType.TOOL` 运行状态消息由 `core_agent.py` 中的 `_wrap_tool_for_observer` 桥接器在每次调用工具时统一发送（并附带 `tool_call_id` 关联上下文）。工具内部不再自行发送 TOOL 消息，只需发送 `CARD`、`SEARCH_CONTENT`、`PICTURE_WEB` 等补充消息
- **历史遗留**: 早期部分工具（如 SQL 工具基类）仍保留 `running_prompt_zh/en` 属性并在工具内发送 TOOL 消息，新工具不再采用该写法

### 4. 异常处理策略
- **统一异常**: 使用 Exception 抛出错误信息
- **错误日志**: 使用 logging 模块记录详细错误信息
- **优雅降级**: 在可能的情况下提供备选方案

## 📝 命名规范

### 文件命名
- **格式**: `{功能名}_tool.py`
- **风格**: 小写字母，单词间用下划线连接
- **示例**: `exa_search_tool.py`, `knowledge_base_search_tool.py`

### 类命名
- **格式**: `{功能名}Tool`
- **风格**: 大驼峰命名法（PascalCase）
- **示例**: `ExaSearchTool`, `KnowledgeBaseSearchTool`

### 属性和方法命名
- **格式**: 小写字母，单词间用下划线连接
- **私有方法**: 以单下划线开头（如 `_filter_images`）
- **示例**: `max_results`, `description_zh`, `_decode_subject`

### 工具标识符规范
- **tool_sign**: 单字母标识符，用于区分工具来源（如在前端引用标注 `[b0]`、`[a1]` 中标识检索来源）
- **取值方式**: 从 `nexent.core.utils.tools_common_message` 中的 `ToolSign` 枚举取值，例如 `tool_sign = ToolSign.EXA_SEARCH.value`
- **分配规则**（摘自 `ToolSign` 枚举定义）:
  - `a`: 知识库搜索 (KNOWLEDGE_BASE, KnowledgeBaseSearchTool)
  - `b`: EXA 搜索 (EXA_SEARCH, ExaSearchTool)
  - `c`: Linkup 搜索 (LINKUP_SEARCH, LinkupSearchTool)
  - `d`: Tavily 搜索 (TAVILY_SEARCH, TavilySearchTool)
  - `e`: DataMate 搜索 (DATAMATE_SEARCH)
  - `f`: 文件操作 (FILE_OPERATION)
  - `g` / `h` / `i` / `j` / `k` / `l`: Dify / iData / Haotian / AIDP / RAGFlow / IndependentAIDP 搜索
  - `m` / `n` / `p` / `s` / `t` / `z`: 多模态 / 记忆 / 规划 / 技能 / 终端 / 数据库操作

## 🏗️ 代码结构模板

### 基础模板

```python
import json
import logging
from typing import Optional
from smolagents.tools import Tool
from pydantic import Field

from ..utils.observer import MessageObserver, ProcessType
from ..utils.tools_common_message import ToolCategory, ToolSign

logger = logging.getLogger("your_tool_name")

class YourTool(Tool):
    name = "your_tool"
    description = "Detailed description of the tool function, including applicable scenarios and usage"
    description_zh = "工具功能的中文描述，说明适用场景和使用方法"
    inputs = {
        "param1": {
            "type": "string",
            "description": "Detailed description of parameter 1",
            "description_zh": "参数1的中文描述"
        },
        "param2": {
            "type": "integer",
            "description": "Detailed description of parameter 2",
            "description_zh": "参数2的中文描述",
            "default": 10,
            "nullable": True
        }
    }
    init_param_descriptions = {          # 构造参数说明（与 __init__ 参数对应）
        "config_param": {"description": "Config parameter description", "description_zh": "配置参数说明"},
        "optional_param": {"description": "Optional parameter description", "description_zh": "可选参数说明"}
    }
    output_type = "string"
    category = ToolCategory.FILE.value  # 按工具类型选择 ToolCategory 枚举成员
    tool_sign = ToolSign.FILE_OPERATION.value  # 按工具类型选择 ToolSign 枚举成员

    def __init__(
        self,
        config_param: str = Field(description="Config parameter"),
        observer: MessageObserver = Field(description="Message observer", default=None, exclude=True),
        optional_param: int = Field(description="Optional parameter", default=5)
    ):
        super().__init__()
        self.config_param = config_param
        self.observer = observer
        self.optional_param = optional_param
        
        # 记录操作序号（如果需要）
        self.record_ops = 0

    def forward(self, param1: str, param2: int = 10) -> str:
        """工具的主要执行方法
        
        Args:
            param1: 参数1说明
            param2: 参数2说明
            
        Returns:
            JSON格式的字符串结果
            
        Raises:
            Exception: 详细的错误信息
        """
        try:
            # 发送卡片信息（可选）
            if self.observer:
                card_content = [{"icon": "your_icon", "text": param1}]
                self.observer.add_message("", ProcessType.CARD, 
                                        json.dumps(card_content, ensure_ascii=False))

            # 主要业务逻辑
            result = self._execute_main_logic(param1, param2)
            
            # 处理结果并返回
            return self._format_result(result)
            
        except Exception as e:
            logger.error(f"Error in {self.name}: {str(e)}")
            raise Exception(f"执行{self.name}时发生错误: {str(e)}")

    def _execute_main_logic(self, param1: str, param2: int):
        """执行主要业务逻辑的私有方法"""
        # 实现具体的业务逻辑
        pass

    def _format_result(self, result) -> str:
        """格式化返回结果"""
        formatted_result = {
            "status": "success",
            "data": result,
            "tool": self.name
        }
        return json.dumps(formatted_result, ensure_ascii=False)
```

### 搜索工具模板

```python
import json
import logging
from typing import List
from smolagents.tools import Tool
from pydantic import Field

from ..utils.observer import MessageObserver, ProcessType
from ..utils.tools_common_message import SearchResultTextMessage, ToolCategory, ToolSign

logger = logging.getLogger("search_tool_name")

class SearchTool(Tool):
    name = "search_tool"
    description = "Detailed description of the search tool, including search scope and applicable scenarios"
    description_zh = "搜索工具的中文描述，包括搜索范围和适用场景"
    inputs = {
        "query": {"type": "string", "description": "The search query to perform", "description_zh": "搜索查询词"},
        "max_results": {"type": "integer", "description": "Maximum number of results", "description_zh": "最大结果数", "default": 5, "nullable": True}
    }
    init_param_descriptions = {          # 构造参数说明（与 __init__ 参数对应）
        "api_key": {"description": "API key", "description_zh": "API密钥"}
    }
    output_type = "string"
    category = ToolCategory.SEARCH.value
    tool_sign = ToolSign.EXA_SEARCH.value  # 按实际搜索源选择 ToolSign 枚举成员

    def __init__(
        self,
        api_key: str = Field(description="API key"),
        observer: MessageObserver = Field(description="Message observer", default=None, exclude=True),
        max_results: int = Field(description="Maximum number of search results", default=5)
    ):
        super().__init__()
        self.api_key = api_key
        self.observer = observer
        self.max_results = max_results
        # 引用序号从 1 起始（供 SearchResultTextMessage 的 cite_index 使用）
        self.record_ops = 1

    def forward(self, query: str, max_results: int = None) -> str:
        if max_results is None:
            max_results = self.max_results

        # 发送卡片信息（可选；TOOL 运行状态消息由 core_agent 桥接器统一发送）
        if self.observer:
            card_content = [{"icon": "search", "text": query}]
            self.observer.add_message("", ProcessType.CARD, 
                                    json.dumps(card_content, ensure_ascii=False))

        try:
            # 执行搜索
            search_results = self._perform_search(query, max_results)
            
            if not search_results:
                raise Exception("未找到搜索结果！请尝试更短或更宽泛的查询。")

            # 格式化搜索结果
            formatted_results = self._format_search_results(search_results)
            
            # 记录搜索内容
            if self.observer:
                search_results_data = json.dumps(formatted_results["json"], ensure_ascii=False)
                self.observer.add_message("", ProcessType.SEARCH_CONTENT, search_results_data)
            
            return json.dumps(formatted_results["return"], ensure_ascii=False)
            
        except Exception as e:
            logger.error(f"搜索错误: {str(e)}")
            raise Exception(f"搜索失败: {str(e)}")

    def _perform_search(self, query: str, max_results: int):
        """执行实际的搜索操作"""
        # 实现具体的搜索逻辑
        pass

    def _format_search_results(self, results):
        """格式化搜索结果为统一格式"""
        search_results_json = []
        search_results_return = []
        
        for index, result in enumerate(results):
            search_result_message = SearchResultTextMessage(
                title=result.get("title", ""),
                url=result.get("url", ""),
                text=result.get("content", ""),
                published_date=result.get("date", ""),
                source_type="url",
                filename="",
                score=result.get("score", ""),
                score_details=result.get("score_details", {}),
                cite_index=self.record_ops + index,
                search_type=self.name,
                tool_sign=self.tool_sign
            )
            search_results_json.append(search_result_message.to_dict())
            search_results_return.append(search_result_message.to_model_dict())
        
        self.record_ops += len(search_results_return)
        
        return {
            "json": search_results_json,
            "return": search_results_return
        }
```

## 🔄 开发流程规范

### 1. 开发前准备
- 确定工具功能和适用场景
- 选择合适的工具分类和标识符
- 检查是否与现有工具功能重复

### 2. 实现步骤
1. **创建工具文件**: 按命名规范创建 `{name}_tool.py`
2. **定义类结构**: 继承 Tool 基类，定义必要属性
3. **实现构造函数**: 使用 pydantic Field 定义参数
4. **实现 forward 方法**: 核心功能逻辑
5. **添加私有方法**: 将复杂逻辑拆分为私有方法
6. **集成消息观察者**: 支持流式输出和多语言
7. **异常处理**: 完善的错误处理和日志记录

### 3. 测试和集成
1. **单元测试**: 测试各种输入情况和边界条件
2. **集成测试**: 与 CoreAgent 集成测试
3. **更新导出**: 在 `__init__.py` 中添加工具导出
4. **文档更新**: 更新相关文档和示例

## ⭐ 最佳实践

### 1. 性能优化
- **异步处理**: 对于耗时操作使用异步处理
- **连接池**: 复用网络连接减少延迟
- **缓存机制**: 适当使用缓存提升响应速度
- **并发控制**: 使用 Semaphore 控制并发请求数

### 2. 安全性
- **输入验证**: 严格验证输入参数
- **敏感信息**: API密钥等敏感信息不应出现在日志中
- **错误信息**: 避免在错误信息中泄露敏感信息
- **超时控制**: 设置合理的超时时间防止阻塞

### 3. 可维护性
- **模块化设计**: 将复杂功能拆分为多个方法
- **清晰注释**: 为复杂逻辑添加详细注释
- **类型注解**: 使用完整的类型注解
- **文档字符串**: 为所有公共方法添加文档字符串

### 4. 用户体验
- **多语言支持**: 提供中英文双语提示
- **进度反馈**: 通过 MessageObserver 提供实时反馈
- **错误提示**: 提供清晰的错误信息和解决建议
- **参数验证**: 在执行前验证参数有效性

## ⚠️ 注意事项

1. **版本兼容**: 确保工具与不同版本的依赖库兼容
2. **资源清理**: 及时释放网络连接、文件句柄等资源
3. **日志级别**: 合理设置日志级别，避免过多调试信息
4. **配置管理**: 所有配置通过构造函数参数传入（SDK 内不直接读取环境变量，环境变量由服务层读取后传入）
5. **错误恢复**: 在可能的情况下提供错误恢复机制

通过遵循这些规范，可以确保新开发的工具与现有工具保持一致性，并具备良好的可维护性和可扩展性。
