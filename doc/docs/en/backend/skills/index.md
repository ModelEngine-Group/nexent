# Backend Skills Documentation

This section covers Nexent's Skills system in the backend infrastructure, including skill definitions, skill package structures, and system architecture.

## Available Documentation

### Overview and Architecture
- [Skills System Overview](./overview): Skill types, lifecycle, and version management

## Skills vs. Tools

In Nexent, **Tools** and **Skills** are two distinct layers:

- **Tool**: A single atomic operation the agent can call, such as `read_file` or `tavily_search`. When enabled, the LLM searches through the tool list on every turn — meaning even if a tool is completely unnecessary for this conversation, the LLM still consumes context tokens to "see" it.
- **Skill**: A workflow of multiple tools bundled with parameter configuration and usage documentation via `SKILL.md`. The LLM does not need to "see" all tools in advance; it decides whether to activate a skill based on the user's actual needs. The corresponding toolset is only loaded when activated — effectively saving Token consumption.

## Quick Start

1. **Explore capabilities**: Read [Skills System Overview](./overview) to understand the supported skill types
2. **Try creation**: Experience NL-to-Skill creation on the [Skill Management](../../user-guide/skills) page
3. **Create manually**: Upload `SKILL.md` or a ZIP package to create a custom skill
4. **Configure for agents**: Enable skills in the agent's tool configuration

## Related References

- [Skill Management (User Guide)](../../user-guide/skills)
- [Agent Development Guide](../../user-guide/agent-development)
- [Local Tools Overview](../../user-guide/local-tools/index)
- [SDK Tool Development Guide](../../sdk/core/tools)
- [MCP Tool Development](../tools/mcp)
- [FAQ](../../quick-start/faq)

## Getting Help

- Check the [FAQ](../../quick-start/faq) for common skill usage questions
- Ask questions in [GitHub Discussions](https://github.com/ModelEngine-Group/nexent/discussions)
- Review [GitHub Issues](https://github.com/ModelEngine-Group/nexent/issues) for known issues
