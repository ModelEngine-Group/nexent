# Prompt Development Guide

This guide provides comprehensive information about the prompt template system used in Nexent for creating different types of agents. The YAML files in the `backend/prompts/` directory define system prompts, planning prompts, and other key prompt components for various agent types.

## File Naming Convention

The naming format follows `{agent_type}_agent.yaml`, where:
- `agent_type`: Describes the main function or purpose of the agent (e.g., manager, search, etc.)

## Prompt Template Structure

Each YAML file contains the following main sections:

### 1. system_prompt

The system prompt is the core component of an agent, defining its role, capabilities, and behavioral guidelines. It typically includes:

- **Core Responsibilities**: Main duties and capabilities description
- **Execution Flow**: Standard process and methods for agent task execution
- **Available Resources**: List of tools and sub-agents the agent can use
- **Resource Usage Requirements**: Priority and strategy for using different tools
- **Python Code Standards**: Code writing standards and constraints
- **Example Templates**: Examples demonstrating agent task execution

### 2. planning

Contains various prompts for task planning:

- **initial_facts**: Initial fact collection prompts
- **initial_plan**: Initial plan formulation prompts
- **update_facts_pre_messages**: Prompts before updating facts
- **update_facts_post_messages**: Prompts after updating facts
- **update_plan_pre_messages**: Prompts before updating plans
- **update_plan_post_messages**: Prompts after updating plans

### 3. managed_agent

Defines prompts for sub-agent interactions:

- **task**: Task assignment prompts for sub-agents
- **report**: Prompts for sub-agent result reporting

### 4. final_answer

Defines prompts for final answer generation:

- **pre_messages**: Prompts before generating final answers
- **post_messages**: Prompts after generating final answers

### 5. tools_requirement

Defines prompts for tool usage standards and priorities.

### 6. few_shots

Provides few-shot learning examples to help agents better understand task execution methods.

## Template Variables

The prompt templates use the following special variables for dynamic replacement:

- `{{tools}}`: Available tools list
- `{{managed_agents}}`: Available sub-agents list
- `{{task}}`: Current task description
- `{{authorized_imports}}`: Authorized Python module imports
- `{{facts_update}}`: Updated facts list
- `{{answer_facts}}`: Known facts list
- `{{remaining_steps}}`: Remaining execution steps

## Available Prompt Templates

### Core Templates

1. **Manager Agent Templates**
   - `manager_system_prompt_template.yaml` - Chinese version
   - `manager_system_prompt_template_en.yaml` - English version
   
   These templates define the core manager agent that coordinates and dispatches various assistants and tools to efficiently solve complex tasks.

2. **Managed Agent Templates**
   - `managed_system_prompt_template.yaml` - Chinese version
   - `managed_system_prompt_template_en.yaml` - English version
   
   These templates define specialized agents that perform specific tasks under the coordination of the manager agent.

3. **Specialized Agent Templates**
   - `knowledge_summary_agent.yaml` - Knowledge summary agent (Chinese)
   - `knowledge_summary_agent_en.yaml` - Knowledge summary agent (English)
   - `analyze_file.yaml` - File analysis agent (Chinese)
   - `analyze_file_en.yaml` - File analysis agent (English)

### Utility Templates

Located in the `utils/` directory:

1. **Prompt Generation Templates**
   - `prompt_generate.yaml` - Chinese version
   - `prompt_generate_en.yaml` - English version
   
   These templates help generate efficient and clear prompts for different agent types.

2. **Title Generation Templates**
   - `generate_title.yaml` - Chinese version
   - `generate_title_en.yaml` - English version
   Templates for generating titles for dialogs. 

## Execution Flow

The standard agent execution flow follows this pattern:

1. **Think**: Analyze current task status and progress
2. **Code**: Write simple Python code following standards
3. **Observe**: View code execution results
4. **Repeat**: Continue the cycle until the task is complete

## Code Standards

When writing Python code in prompts:

1. Use the format `Code: \n```py\n` for executable code
2. Use the format `Code: \n```code:language_type\n` for display-only code
3. Use only defined variables that persist across calls
4. Use `print()` function to make variable information visible
5. Use keyword parameters for tool and agent calls
6. Avoid excessive tool calls in a single round
7. Only import from authorized modules: `{{authorized_imports}}`

## Best Practices

1. **Task Decomposition**: Break complex tasks into manageable sub-tasks
2. **Professional Matching**: Assign tasks based on agent expertise
3. **Information Integration**: Integrate outputs from different agents
4. **Efficiency Optimization**: Avoid redundant work
5. **Result Evaluation**: Assess agent return results and provide additional guidance when needed
