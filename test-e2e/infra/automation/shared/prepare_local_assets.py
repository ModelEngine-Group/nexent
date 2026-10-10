"""Prepare explicit asset families for local targets; never run test cases."""
import argparse
import asyncio
import os
from shared.auth import sign_in
from shared.factories.evaluation import prepare_completed_run, prepare_evaluation_inputs
from shared.factories.skill import prepare_skill
from shared.factories.automation import prepare_automation_task
from shared.factories.sharing import prepare_share_assets


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--family', action='append', required=True,
                        choices=['completed_evaluation', 'evaluation_inputs', 'configurable_skill', 'market_skill', 'automation_task', 'share_assets','tag_resources','basic_agent','tool_agent','relationship_agent','metadata_agent','skill_agent','agent_listing','performance_upload','performance_range'])
    args = parser.parse_args()
    identity = await sign_in('tenant_a_admin')
    for family in dict.fromkeys(args.family):
        if family == 'completed_evaluation':
            await prepare_completed_run(identity)
        elif family == 'evaluation_inputs':
            await prepare_evaluation_inputs(identity)
        elif family == 'configurable_skill':
            await prepare_skill(identity, role='configurable', cleanup_identity='tenant_a_admin', owner='LOCAL-SKILL-PREP')
        elif family == 'market_skill':
            author = os.environ.get('NEXENT_TEST_MARKET_AUTHOR') or 'tenant_a_dev'
            await prepare_skill(await sign_in(author), role='d4_created', cleanup_identity=author, owner='LOCAL-MARKET-SKILL-PREP')
        elif family == 'automation_task':
            await prepare_automation_task(await sign_in('tenant_a_user'))
        elif family == 'share_assets':
            await prepare_share_assets(identity)
        elif family == 'tag_resources':
            from shared.factories.tags import prepare_tag_resources
            await prepare_tag_resources(identity)
        elif family == 'basic_agent':
            from shared.factories.agent import prepare_basic_agent
            await prepare_basic_agent(await sign_in('tenant_a_user'))
        elif family == 'tool_agent':
            from shared.factories.mcp import prepare_tool_agent
            await prepare_tool_agent(await sign_in('tenant_a_user'))
        elif family == 'relationship_agent':
            from shared.factories.agent import prepare_relationship_agent
            await prepare_relationship_agent(await sign_in('tenant_a_user'))
        elif family == 'metadata_agent':
            from shared.factories.agent import prepare_metadata_agent
            await prepare_metadata_agent(await sign_in('tenant_a_user'))
        elif family=='performance_upload':
            from shared.factories.performance import prepare_upload_target
            await prepare_upload_target(identity)
        elif family=='performance_range':
            from shared.factories.performance import prepare_range_attachment
            await prepare_range_attachment(await sign_in('tenant_a_user'))
        elif family=='skill_agent':
            from shared.factories.skill import prepare_skill_agent
            await prepare_skill_agent(identity,await sign_in('tenant_a_user'))
        elif family=='agent_listing':
            from shared.factories.repository import prepare_agent_listing
            await prepare_agent_listing(await sign_in('tenant_a_dev'),identity)


if __name__ == '__main__':
    asyncio.run(main())
