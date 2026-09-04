# Nexent Tool Development Guidelines

This document summarizes the complete guidelines and best practices for tool development in the Nexent SDK based on analysis of existing tools.

## 📂 Tool Categories

The current SDK includes the following tool types:

### Search Tools
- **ExaSearchTool**: Web search tool based on EXA API
- **TavilySearchTool**: Web search tool based on Tavily API  
- **LinkupSearchTool**: Search tool based on Linkup API
- **KnowledgeBaseSearchTool**: Local knowledge base search tool
- **RAGFlowSearchTool**: RAGFlow knowledge retrieval
- **HaotianSearchTool / IndependentAidpSearchTool / AidpSearchTool / DifySearchTool / DataMateSearchTool / IdataSearchTool**: Enterprise-grade retrieval source integrations

### File Management Tools
- **CreateFileTool**: Create new files with content
- **ReadFileTool**: Read file contents from the filesystem
- **DeleteFileTool**: Delete files from the filesystem
- **MoveItemTool**: Move or rename files and directories
- **CreateDirectoryTool**: Create new directories
- **DeleteDirectoryTool**: Delete directories and their contents
- **ListDirectoryTool**: List directory contents with detailed information

### System Tools
- **TerminalTool**: Execute shell commands and system operations

### Communication Tools
- **GetEmailTool**: Email retrieval tool via IMAP
- **SendEmailTool**: Email sending tool via SMTP

### Multimodal Tools
- **AnalyzeTextFileTool**: A document question-answering tool based on data processing and large language models
- **AnalyzeImageTool**: An image question-answering tool based on visual language models
- **AnalyzeAudioTool**: An audio understanding tool based on speech models
- **AnalyzeVideoTool**: A video understanding tool based on visual language models

### Memory Tools
- **StoreMemoryTool**: Stores important information into the current agent's short-term memory (MemoryLayer.AGENT + SHORT_TERM), up to 3 entries per run
- **SearchMemoryTool**: Retrieves the current agent's memories by natural language query, with top_k defaulting to 5

### Orchestration Tools
- **ParallelExecutorTool**: Executes multiple sub-agents concurrently
- **CreatePlanTool / UpdatePlanStepTool**: Creation and update of plan todos

### Data Tools
- **MySqlTool / PostgreSqlTool / MsSqlTool**: Execute controlled SQL queries against databases
- **UploadToS3Tool / DownloadFromS3Tool**: S3 object upload and download

### Skill and Task Tools (system-managed internally)
- **ReadSkillConfigTool / ReadSkillMdTool**: Read config.yaml and SKILL.md under the skill directory
- **RunSkillScriptTool**: Execute skill scripts
- **WriteSkillFileTool**: Write files into the tenant-isolated skill directory
- **CreateScheduledTaskProposalTool**: Create scheduled task proposals pending user confirmation (only saves the proposal, does not execute business tasks)

> Note: The tools above are managed internally by the system and are not exported uniformly in the `__init__.py` of `nexent.core.tools`.

## 🔧 Common Characteristics

### 1. Basic Architecture
- **Base Class Inheritance**: All tools must inherit from `smolagents.tools.Tool`
- **Parameter Management**: Use `pydantic.Field` for parameter definition and validation
- **Streaming Output**: Integrate `MessageObserver` for real-time message transmission
- **Multi-language Support**: Built-in Chinese and English bilingual prompts

### 2. Core Attributes
Each tool class must include the following class attributes:

```python
class ToolExample(Tool):
    name = "tool_name"                     # Tool unique identifier
    description = "Tool function description"  # Detailed feature description (English)
    description_zh = "工具功能描述"        # Detailed feature description (Chinese)
    inputs = {                             # Input parameter definition
        "param": {
            "type": "string",
            "description": "Parameter description",
            "description_zh": "参数描述"
        }
    }
    init_param_descriptions = {            # Constructor parameter descriptions (corresponding to __init__ parameters)
        "config_param": {"description": "Config parameter description", "description_zh": "配置参数说明"}
    }
    output_type = "string"                 # Output type
    category = "search"                    # Tool category (ToolCategory enum value)
    tool_sign = "b"                        # Tool identifier (ToolSign enum value)
```

### 3. Message Processing Mechanism
- **ProcessType Enumeration**: Use different types to distinguish messages (TOOL, CARD, SEARCH_CONTENT, PICTURE_WEB, etc.)
- **Observer Pattern**: Implement real-time message pushing through MessageObserver
- **JSON Format**: All message content uses JSON format to ensure consistency
- **Unified sending of running status messages**: `ProcessType.TOOL` running status messages are sent uniformly by the `_wrap_tool_for_observer` bridge in `core_agent.py` every time a tool is invoked (with a `tool_call_id` attached for context correlation). Tools no longer send TOOL messages themselves; they only need to send supplementary messages such as `CARD`, `SEARCH_CONTENT`, `PICTURE_WEB`, etc.
- **Legacy**: Some earlier tools (e.g., the SQL tool base classes) still keep the `running_prompt_zh/en` attributes and send TOOL messages inside the tool; new tools should no longer use this pattern

### 4. Exception Handling Strategy
- **Unified Exceptions**: Use Exception to throw error messages
- **Error Logging**: Use logging module to record detailed error information
- **Graceful Degradation**: Provide fallback solutions when possible

## 📝 Naming Conventions

### File Naming
- **Format**: `{function_name}_tool.py`
- **Style**: Lowercase letters, words connected by underscores
- **Examples**: `exa_search_tool.py`, `knowledge_base_search_tool.py`

### Class Naming
- **Format**: `{FunctionName}Tool`
- **Style**: PascalCase
- **Examples**: `ExaSearchTool`, `KnowledgeBaseSearchTool`

### Attribute and Method Naming
- **Format**: Lowercase letters, words connected by underscores
- **Private Methods**: Start with single underscore (e.g., `_filter_images`)
- **Examples**: `max_results`, `description_zh`, `_decode_subject`

### Tool Identifier Conventions
- **tool_sign**: Single letter identifier for distinguishing tool sources (e.g., marking retrieval sources in frontend citation labels like `[b0]`, `[a1]`)
- **How to set it**: Take values from the `ToolSign` enum in `nexent.core.utils.tools_common_message`, e.g., `tool_sign = ToolSign.EXA_SEARCH.value`
- **Assignment Rules** (excerpted from the `ToolSign` enum definition):
  - `a`: Knowledge base search (KNOWLEDGE_BASE, KnowledgeBaseSearchTool)
  - `b`: EXA search (EXA_SEARCH, ExaSearchTool)
  - `c`: Linkup search (LINKUP_SEARCH, LinkupSearchTool)
  - `d`: Tavily search (TAVILY_SEARCH, TavilySearchTool)
  - `e`: DataMate search (DATAMATE_SEARCH)
  - `f`: File operations (FILE_OPERATION)
  - `g` / `h` / `i` / `j` / `k` / `l`: Dify / iData / Haotian / AIDP / RAGFlow / IndependentAIDP search
  - `m` / `n` / `p` / `s` / `t` / `z`: Multimodal / memory / planning / skills / terminal / database operations

## 🏗️ Code Structure Templates

### Basic Template

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
    init_param_descriptions = {          # Constructor parameter descriptions (corresponding to __init__ parameters)
        "config_param": {"description": "Config parameter description", "description_zh": "配置参数说明"},
        "optional_param": {"description": "Optional parameter description", "description_zh": "可选参数说明"}
    }
    output_type = "string"
    category = ToolCategory.FILE.value  # Choose the ToolCategory enum member by tool type
    tool_sign = ToolSign.FILE_OPERATION.value  # Choose the ToolSign enum member by tool type

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
        
        # Record operation sequence (if needed)
        self.record_ops = 0

    def forward(self, param1: str, param2: int = 10) -> str:
        """Main execution method of the tool
        
        Args:
            param1: Parameter 1 description
            param2: Parameter 2 description
            
        Returns:
            JSON format string result
            
        Raises:
            Exception: Detailed error information
        """
        try:
            # Send card information (optional)
            if self.observer:
                card_content = [{"icon": "your_icon", "text": param1}]
                self.observer.add_message("", ProcessType.CARD, 
                                        json.dumps(card_content, ensure_ascii=False))

            # Main business logic
            result = self._execute_main_logic(param1, param2)
            
            # Process result and return
            return self._format_result(result)
            
        except Exception as e:
            logger.error(f"Error in {self.name}: {str(e)}")
            raise Exception(f"Error executing {self.name}: {str(e)}")

    def _execute_main_logic(self, param1: str, param2: int):
        """Private method for executing main business logic"""
        # Implement specific business logic
        pass

    def _format_result(self, result) -> str:
        """Format return result"""
        formatted_result = {
            "status": "success",
            "data": result,
            "tool": self.name
        }
        return json.dumps(formatted_result, ensure_ascii=False)
```

### Search Tool Template

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
    init_param_descriptions = {          # Constructor parameter descriptions (corresponding to __init__ parameters)
        "api_key": {"description": "API key", "description_zh": "API密钥"}
    }
    output_type = "string"
    category = ToolCategory.SEARCH.value
    tool_sign = ToolSign.EXA_SEARCH.value  # Choose the ToolSign enum member by actual search source

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
        # Citation index starts from 1 (used by SearchResultTextMessage's cite_index)
        self.record_ops = 1

    def forward(self, query: str, max_results: int = None) -> str:
        if max_results is None:
            max_results = self.max_results

        # Send card information (optional; TOOL running status messages are sent uniformly by the core_agent bridge)
        if self.observer:
            card_content = [{"icon": "search", "text": query}]
            self.observer.add_message("", ProcessType.CARD, 
                                    json.dumps(card_content, ensure_ascii=False))

        try:
            # Execute search
            search_results = self._perform_search(query, max_results)
            
            if not search_results:
                raise Exception("No search results found! Please try shorter or broader queries.")

            # Format search results
            formatted_results = self._format_search_results(search_results)
            
            # Record search content
            if self.observer:
                search_results_data = json.dumps(formatted_results["json"], ensure_ascii=False)
                self.observer.add_message("", ProcessType.SEARCH_CONTENT, search_results_data)
            
            return json.dumps(formatted_results["return"], ensure_ascii=False)
            
        except Exception as e:
            logger.error(f"Search error: {str(e)}")
            raise Exception(f"Search failed: {str(e)}")

    def _perform_search(self, query: str, max_results: int):
        """Execute actual search operation"""
        # Implement specific search logic
        pass

    def _format_search_results(self, results):
        """Format search results into unified format"""
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

## 🔄 Development Process Guidelines

### 1. Pre-development Preparation
- Determine tool functionality and applicable scenarios
- Choose appropriate tool category and identifier
- Check for duplication with existing tool functionality

### 2. Implementation Steps
1. **Create Tool File**: Create `{name}_tool.py` according to naming conventions
2. **Define Class Structure**: Inherit from Tool base class, define necessary attributes
3. **Implement Constructor**: Use pydantic Field to define parameters
4. **Implement forward Method**: Core functionality logic
5. **Add Private Methods**: Break down complex logic into private methods
6. **Integrate Message Observer**: Support streaming output and multi-language
7. **Exception Handling**: Comprehensive error handling and logging

### 3. Testing and Integration
1. **Unit Testing**: Test various input scenarios and edge cases
2. **Integration Testing**: Integration testing with CoreAgent
3. **Update Exports**: Add tool exports in `__init__.py`
4. **Documentation Updates**: Update related documentation and examples

## ⭐ Best Practices

### 1. Performance Optimization
- **Async Processing**: Use async processing for time-consuming operations
- **Connection Pooling**: Reuse network connections to reduce latency
- **Caching Mechanisms**: Use caching appropriately to improve response speed
- **Concurrency Control**: Use Semaphore to control concurrent request numbers

### 2. Security
- **Input Validation**: Strictly validate input parameters
- **Sensitive Information**: API keys and other sensitive information should not appear in logs
- **Error Messages**: Avoid leaking sensitive information in error messages
- **Timeout Control**: Set reasonable timeout times to prevent blocking

### 3. Maintainability
- **Modular Design**: Break down complex functionality into multiple methods
- **Clear Comments**: Add detailed comments for complex logic
- **Type Annotations**: Use complete type annotations
- **Documentation Strings**: Add documentation strings for all public methods

### 4. User Experience
- **Multi-language Support**: Provide Chinese and English bilingual prompts
- **Progress Feedback**: Provide real-time feedback through MessageObserver
- **Error Prompts**: Provide clear error messages and solution suggestions
- **Parameter Validation**: Validate parameter validity before execution

## ⚠️ Important Notes

1. **Version Compatibility**: Ensure tools are compatible with different versions of dependency libraries
2. **Resource Cleanup**: Release network connections, file handles and other resources in time
3. **Log Level**: Set log levels reasonably to avoid too much debug information
4. **Configuration Management**: All configuration is passed in through constructor parameters (the SDK does not read environment variables directly; environment variables are read by the service layer and passed in)
5. **Error Recovery**: Provide error recovery mechanisms when possible

By following these guidelines, you can ensure that newly developed tools maintain consistency with existing tools and have good maintainability and extensibility. 