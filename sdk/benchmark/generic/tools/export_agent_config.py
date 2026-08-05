#!/usr/bin/env python3
"""
Export Nexent Agent configuration from PostgreSQL database to YAML file.

This script reads agent configuration from the Nexent database and exports it
to a YAML file that can be used by run_benchmark.py for testing.

Usage:
    # Export by agent_id
    backend/.venv/bin/python sdk/benchmark/generic/tools/export_agent_config.py --agent-id 7 --output sdk/benchmark/generic/configs/agent_7.yaml

    # Export by display_name
    backend/.venv/bin/python sdk/benchmark/generic/tools/export_agent_config.py --name "Math Assistant" --output sdk/benchmark/generic/configs/math_assistant.yaml

    # Export with specific version (default: current_version_no)
    backend/.venv/bin/python sdk/benchmark/generic/tools/export_agent_config.py --agent-id 7 --version 1 --output sdk/benchmark/generic/configs/agent_7_v1.yaml

Environment variables (or use .env file):
    NEXENT_DB_HOST: Database host (default: localhost)
    NEXENT_DB_PORT: Database port (default: 5432)
    NEXENT_DB_NAME: Database name (default: nexent)
    NEXENT_DB_USER: Database user (default: nexent)
    NEXENT_DB_PASSWORD: Database password (default: nexent)
"""

import argparse
import os
import sys
from pathlib import Path

import psycopg2
import yaml
from dotenv import load_dotenv


GENERIC_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(GENERIC_DIR))

try:
    from common.secret_refs import externalize_sensitive_values
except ImportError:  # Package import in tests.
    from ..common.secret_refs import externalize_sensitive_values

# Load environment variables
load_dotenv()


def get_db_connection():
    """Create database connection using environment variables."""
    return psycopg2.connect(
        host=os.getenv("NEXENT_DB_HOST", "localhost"),
        port=int(os.getenv("NEXENT_DB_PORT", "5434")),
        dbname=os.getenv("NEXENT_DB_NAME", "nexent"),
        user=os.getenv("NEXENT_DB_USER", "root"),
        password=os.getenv("NEXENT_DB_PASSWORD", "nexent@4321")
    )


def export_agent_config(agent_id: int = None, agent_name: str = None,
                        version: int = None, output_path: str = None):
    """
    Export agent configuration from database to YAML file.

    Args:
        agent_id: Agent ID to export
        agent_name: Agent display name to export (alternative to agent_id)
        version: Specific version number (default: current_version_no)
        output_path: Output YAML file path
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # Set search path to nexent schema
    cursor.execute("SET search_path TO nexent")

    try:
        # Find agent by ID or name
        if agent_id:
            cursor.execute("""
                SELECT agent_id, display_name, current_version_no, tenant_id
                FROM ag_tenant_agent_t
                WHERE agent_id = %s AND delete_flag = 'N'
            """, (agent_id,))
        elif agent_name:
            cursor.execute("""
                SELECT agent_id, display_name, current_version_no, tenant_id
                FROM ag_tenant_agent_t
                WHERE display_name = %s AND delete_flag = 'N'
            """, (agent_name,))
        else:
            raise ValueError("Must provide either --agent-id or --name")

        result = cursor.fetchone()
        if not result:
            raise ValueError(f"Agent not found: id={agent_id}, name={agent_name}")

        agent_id, display_name, current_version, tenant_id = result
        target_version = version if version is not None else current_version

        print(f"Exporting agent: {display_name} (ID: {agent_id}, Version: {target_version})")

        # Query agent main config
        cursor.execute("""
            SELECT
                agent_id, name, display_name, description,
                duty_prompt, constraint_prompt, few_shots_prompt,
                max_steps, enable_context_manager, provide_run_summary,
                verification_config, greeting_message, example_questions,
                prompt_template_id, version_no
            FROM ag_tenant_agent_t
            WHERE agent_id = %s AND version_no = %s AND delete_flag = 'N'
        """, (agent_id, target_version))

        agent_row = cursor.fetchone()
        if not agent_row:
            raise ValueError(f"Agent version not found: id={agent_id}, version={target_version}")

        (agent_id, name, display_name, description,
         duty_prompt, constraint_prompt, few_shots_prompt,
         max_steps, enable_context_manager, provide_run_summary,
         verification_config, greeting_message, example_questions,
         prompt_template_id, version_no) = agent_row

        # Query tools
        cursor.execute("""
            SELECT
                t.name, t.class_name, t.source, t.category,
                t.description, t.inputs, t.output_type,
                ti.params, ti.enabled
            FROM ag_tool_instance_t ti
            JOIN ag_tool_info_t t ON ti.tool_id = t.tool_id
            WHERE ti.agent_id = %s AND ti.version_no = %s AND ti.delete_flag = 'N'
            ORDER BY ti.tool_instance_id
        """, (agent_id, target_version))

        tools = []
        required_secret_env_vars = set()
        for row in cursor.fetchall():
            (tool_name, tool_class, tool_source, tool_category,
             tool_desc, tool_inputs, tool_output_type,
             tool_params, enabled) = row
            safe_tool_params, tool_secret_env_vars = externalize_sensitive_values(
                tool_params or {},
                tool_name=tool_name,
            )
            required_secret_env_vars.update(tool_secret_env_vars)
            tools.append({
                "tool_name": tool_name,
                "tool_class": tool_class,
                "tool_source": tool_source,
                "tool_category": tool_category,
                "tool_description": tool_desc,
                "tool_inputs": tool_inputs,
                "tool_output_type": tool_output_type,
                "tool_params": safe_tool_params,
                "enabled": enabled
            })

        # Query sub-agents
        cursor.execute("""
            SELECT agent_id, name, display_name, version_no
            FROM ag_tenant_agent_t
            WHERE parent_agent_id = %s AND version_no = %s AND delete_flag = 'N'
        """, (agent_id, target_version))

        sub_agents = []
        for row in cursor.fetchall():
            sub_agent_id, sub_name, sub_display_name, sub_version = row
            sub_agents.append({
                "agent_id": sub_agent_id,
                "name": sub_name,
                "display_name": sub_display_name,
                "version_no": sub_version
            })

        # Query skills (if table exists)
        skills = []
        try:
            cursor.execute("""
                SELECT s.skill_name, s.skill_description, s.skill_content
                FROM ag_skill_info_t s
                JOIN ag_skill_tools_rel_t str ON s.skill_id = str.skill_id
                WHERE str.agent_id = %s AND s.delete_flag = 'N'
            """, (agent_id,))

            for row in cursor.fetchall():
                skill_name, skill_desc, skill_content = row
                skills.append({
                    "skill_name": skill_name,
                    "skill_description": skill_desc,
                    "skill_content": skill_content
                })
        except psycopg2.Error:
            # Skills table might not exist in all versions
            conn.rollback()
            pass

        # Build YAML structure
        config = {
            "agent_info": {
                "agent_id": agent_id,
                "tenant_id": tenant_id,
                "name": name,
                "display_name": display_name,
                "description": description,
                "greeting_message": greeting_message,
                "example_questions": example_questions or []
            },
            "agent_config": {
                "max_steps": max_steps,
                "enable_context_manager": enable_context_manager,
                "provide_run_summary": provide_run_summary,
                "prompt_template_id": prompt_template_id,
                "version_no": version_no,
                "verification_config": verification_config or {}
            },
            "prompts": {
                "duty_prompt": duty_prompt or "",
                "constraint_prompt": constraint_prompt or "",
                "few_shots_prompt": few_shots_prompt or ""
            },
            "tools": tools,
            "sub_agents": sub_agents,
            "skills": skills
        }

        # Write to YAML file
        output_file = output_path or f"configs/agent_{agent_id}_v{target_version}.yaml"
        Path(output_file).parent.mkdir(parents=True, exist_ok=True)

        with open(output_file, 'w', encoding='utf-8') as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

        print(f"✓ Exported to: {output_file}")
        print(f"  - Tools: {len(tools)}")
        print(f"  - Sub-agents: {len(sub_agents)}")
        print(f"  - Skills: {len(skills)}")
        if required_secret_env_vars:
            print(
                "  - Required secret environment variables: "
                + ", ".join(sorted(required_secret_env_vars))
            )

        return output_file

    finally:
        cursor.close()
        conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="Export Nexent Agent configuration from database to YAML"
    )
    parser.add_argument("--agent-id", type=int, help="Agent ID to export")
    parser.add_argument("--name", type=str, help="Agent display name to export")
    parser.add_argument("--version", type=int, help="Specific version number (default: current_version_no)")
    parser.add_argument("--output", "-o", type=str, help="Output YAML file path")

    args = parser.parse_args()

    if not args.agent_id and not args.name:
        parser.error("Must provide either --agent-id or --name")

    try:
        export_agent_config(
            agent_id=args.agent_id,
            agent_name=args.name,
            version=args.version,
            output_path=args.output
        )
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
