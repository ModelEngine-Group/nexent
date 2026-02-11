---
name: prompt-writing
description: Create, refine, and optimize high-quality YAML prompts for AI assistants. Use when working with prompt templates, system prompts, agent prompts, or any prompt engineering tasks. Provides structure guidelines, template patterns, and quality standards for YAML-based prompts.
license: Complete terms in LICENSE.txt
---

# Prompt Writing

Create and optimize YAML-based prompts for AI assistants following industry best practices.

## Quick Start

### Standard YAML Prompt Structure

```yaml
system_prompt: |-
  # Section with ### header
  ## Subsection with ## header
  Content with clear structure.
  
  **Bold key concepts**
  
  - Bullet points for requirements
  - Consistent indentation (2 spaces)
  
  1. Numbered lists for sequences
  2. Use when order matters

user_prompt: |
  Direct instructions with {{ variable placeholders }}
```

### Key Principles

1. **Structure**: Use `|-` for multi-line system prompts, `|` for user prompts
2. **Templating**: Use `{{ variable }}` for dynamic content
3. **Separators**: Use `---` sparingly, only between major sections
4. **Language**: Keep prompts in consistent language (English recommended for templates)

## Quality Checklist

Before finalizing any prompt, verify:

- [ ] No unclosed braces `{{` without `}}`
- [ ] No excessive separators (`---`, `***`)
- [ ] Consistent heading hierarchy (`###` → `##`)
- [ ] Clear variable placeholders with descriptive names
- [ ] Proper YAML indentation preserved
- [ ] No HTML tags in Markdown content
- [ ] Lists have parallel structure

## Common Patterns

### System Prompt with Sections

```yaml
system_prompt: |-
  ### Role Definition
  You are a professional [role name]. Your task is to [core responsibility].
  
  ### Requirements
  1. First requirement
  2. Second requirement
  3. Third requirement
  
  ### Guidelines
  - Do this
  - Don't do that
  - Always do this
  
  ### Output Format
  Respond in plain text without separators.
```

### Jinja2 Template Variables

```yaml
user_prompt: |
  Please analyze the following {{ document_type }}:
  
  Name: {{ filename }}
  Content: {{ content }}
  
  Summary ({{ max_words }} words):
```

## References

- **Best Practices**: See [best-practices.md](best-practices.md) for detailed guidelines
- **Templates**: See [templates.md](templates.md) for reusable patterns
- **Examples**: See [examples.md](examples.md) for real-world samples

## Related Tools

When working with prompts, also consider:

- YAML validation tools
- Jinja2 syntax checkers
- Markdown linters
