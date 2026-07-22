"""Cross-type rendering tests for fine-grained context items."""

import hashlib

import pytest

from backend.utils.context_utils import build_context_inputs
from nexent.core.agents.context import ContextManager as RealContextManager
from nexent.core.agents.context import ContextItemRenderer, ContextItemType
from nexent.core.agents.context.models import normalize_context_inputs


def _items(**kwargs):
    return normalize_context_inputs(build_context_inputs(**kwargs))


PHASE_2_FULL_MESSAGE_DIGESTS = {
    "en": [
        ("system", "14fbe96ec66f3c0803a59c501086d0810dd68ff99f6761dcfb489df314e1c0a7"),
        ("system", "8d80ed6ad24312323e245c441bd089a32fa38e7533748099a94b130d03458084"),
        ("system", "e1284982b11b5dfc00c069775e741c6bf32ad4394cb53fafec45596a4845b942"),
        ("system", "80e136c4c3373482a9b1b181d40db1fd1cf6879ef3b17c1bda725be061f9720a"),
        ("system", "408d6cf91329b0569ec09bed74f0dac6f40f1b96b186479e2c41a3c2f499c9a1"),
        ("system", "0b97877b6c0509b4edd33e65a73b9f89c8e0b8bfd6f3874b956279b8e1fead50"),
        ("system", "d8e95e23514ff03a8bfc310e62df00ad344906f027bfc2fab68a4b0f83d50c79"),
        ("system", "88d2c787cc8695b9783f2e84470a282ec4bda338f46ddf72de670818a05dfd1a"),
        ("system", "65315279266bdedb79bc792f1ef900e7e13eaeb17ca7f906229958f561cdf66c"),
        ("system", "134b6f109f7cfa75f11d104200a6c42f2232bfadca0eb53f0266be10f1797b2e"),
        ("system", "a3a411fec12b8f35b4ba272c9421b79929e681ad9b926197b864426eb6e20ea7"),
        ("system", "ca0c6e859049f6d8cbb6e034be76ac9b863fd3340011a439e527829ae059cdbb"),
        ("user", "db11e7720569f56dad5936dabd76253a1b1bacf3d8d6c7c6b8616ff5a9f8a574"),
        ("user", "bdb5f3957f794cd5d8e20bd13e26e0e6bfcb3b6c5b21c82987be84302df7adf6"),
    ],
    "zh": [
        ("system", "23e51d094e4294b85a13d954d7e6f28860e677a36788c375d0e0c4e8a3b13ed3"),
        ("system", "76ec24802341088ac7e18e1b1c7bdb5ec7c99277d47dd60d7a2a4fccfb503925"),
        ("system", "bb6847e449dd75b5afff2eda0762ed9dad272805e30aa8bdfc939f8a0a06b8ba"),
        ("system", "914a30e1073992d116c207ba7312a6a343917be42d553fd56cb281450edddfdd"),
        ("system", "4cb1a3d2001265527ab3382326e88d4f1684a251d0fb4b2d6f32b2421905f00a"),
        ("system", "46795234d63114a3a0d4c9cabf4371c9301f9e59b6d23107f9abc9c6e2bdda55"),
        ("system", "3b26751d90be8be61de545f3af082f44c6a056c24ad5231b2243bbd7c7a0c942"),
        ("system", "f1d1fb9d14fc5ad1024cc1645959d2e2821f6d038c7e03f2928aca3e4aa7f07f"),
        ("system", "eb72f36c8dd78b06c33a7138de905a34bba19174da0dd64a2f19f2673cb157a7"),
        ("system", "96a808a0ea37f24a3408bfc4df3a85dbc572bb1533d63a03189fecdaae1f9bf4"),
        ("system", "bb6cb21988325ee56deac360581b21550b07a719920c509be89f5e33fcc3f239"),
        ("system", "729c5a521c646c1cc9a29dbaf987f9c85e4a35711f9b26ca0771f02f971c8757"),
        ("user", "5d4511550baf4d6cab3eb2c788cd2a79511c0ea00bbeaa570e0fd32eaea2bf0c"),
        ("user", "b8655d442ce90bc68c60e465aa1a3dc8518268b6ea6df4a47d8896575ded95ae"),
    ],
}


@pytest.mark.parametrize("language", ["zh", "en"])
def test_every_backend_item_payload_serializes_and_renders(language):
    items = _items(
        duty="duty",
        constraint="constraint",
        few_shots="example",
        app_name="app",
        app_description="description",
        user_id="user",
        language=language,
        tools={"tool": {"description": "desc", "inputs": {"q": "str"}, "output_type": "str"}},
        skills=[{"name": "skill", "description": "desc"}],
        memory_list=[{"memory": "fact", "memory_level": "user", "score": 0.9}],
        knowledge_base_summary="kb summary",
        kb_ids=["kb"],
        managed_agents={"worker": {"description": "worker", "tools": []}},
        external_a2a_agents={"external": {"agent_id": "external", "name": "external", "description": "desc"}},
    )

    messages = ContextItemRenderer().render(items)

    assert messages
    assert {item.type for item in items} == {
        ContextItemType.SYSTEM, ContextItemType.TOOL, ContextItemType.SKILL,
        ContextItemType.MEMORY, ContextItemType.KNOWLEDGE_BASE,
        ContextItemType.MANAGED_AGENT, ContextItemType.EXTERNAL_AGENT,
    }
    assert all(item.model_dump(mode="json") for item in items)
    system_composition_types = {
        ContextItemType.SYSTEM,
        ContextItemType.TOOL,
        ContextItemType.SKILL,
        ContextItemType.MANAGED_AGENT,
        ContextItemType.EXTERNAL_AGENT,
    }
    assert all(item.required for item in items if item.type in system_composition_types)
    assert all(
        not item.required
        for item in items
        if item.type in {ContextItemType.MEMORY, ContextItemType.KNOWLEDGE_BASE}
    )


@pytest.mark.parametrize(
    ("item_type", "expected_role"),
    [
        (ContextItemType.SYSTEM, "system"),
        (ContextItemType.TOOL, "system"),
        (ContextItemType.SKILL, "system"),
        (ContextItemType.MEMORY, "user"),
        (ContextItemType.KNOWLEDGE_BASE, "user"),
        (ContextItemType.MANAGED_AGENT, "system"),
        (ContextItemType.EXTERNAL_AGENT, "system"),
    ],
)
def test_each_item_type_has_explicit_role(item_type, expected_role):
    items = _items(
        duty="duty",
        tools={"tool": {"description": "desc"}},
        skills=[{"name": "skill", "description": "desc"}],
        memory_list=[{"memory": "fact", "memory_level": "user", "score": 1.0}],
        knowledge_base_summary="kb",
        managed_agents={"worker": {"description": "worker"}},
        external_a2a_agents={"external": {"name": "external", "description": "desc"}},
    )
    selected = [item for item in items if item.type == item_type]

    messages = ContextItemRenderer().render(selected)

    assert messages and all(message["role"] == expected_role for message in messages)


def test_group_handler_failure_has_stable_error_payload():
    items = _items(tools={"tool": {"description": "desc"}})
    tool = next(item for item in items if item.type == ContextItemType.TOOL)
    broken = tool.model_copy(update={"content": {}})

    with pytest.raises(RuntimeError, match="handler failed for item group tools"):
        ContextItemRenderer().render([broken])


@pytest.mark.parametrize("language", ["zh", "en"])
def test_default_rendering_has_deterministic_class_defined_order(language):
    items = build_context_inputs(
        duty="Duty <&> 职责",
        constraint="Constraint\n第二行",
        few_shots="User: {x}\nAssistant: ✓",
        app_name="Nexent",
        app_description="Desc & <tag>",
        user_id="user-1",
        language=language,
        is_manager=True,
        tools={
            "search": {"description": "Search <docs> & data", "inputs": '{"q":"string"}', "output_type": "string", "source": "local"},
            "run_skill_script": {"description": "Run skill script", "inputs": '{"path":"string"}', "output_type": "string", "source": "local"},
        },
        skills=[{"name": "analysis-skill", "description": "Analyze <input> & report"}],
        managed_agents={"analyst": {"description": "Internal analyst ✓"}},
        external_a2a_agents={"ext-1": {"agent_id": "ext-1", "name": "remote_helper", "description": "External & safe"}},
        memory_list=[{"memory": "Prefers concise answers <3", "memory_level": "user", "score": 0.91}],
        memory_search_query="special <query>",
        knowledge_base_summary="**KB**: facts & <evidence>",
        kb_ids=["kb-1"],
    )
    manager = RealContextManager()
    manager.replace_items(items)

    actual = []
    for message in manager.build_context_messages():
        text = "".join(part.get("text", "") for part in message["content"])
        actual.append((message["role"], hashlib.sha256(text.encode()).hexdigest()))

    second = RealContextManager()
    second.replace_items(list(reversed(items)))
    repeated = []
    for message in second.build_context_messages():
        text = "".join(part.get("text", "") for part in message["content"])
        repeated.append((message["role"], hashlib.sha256(text.encode()).hexdigest()))
    assert actual == repeated
    first_user = next(index for index, (role, _) in enumerate(actual) if role == "user")
    assert all(role == "system" for role, _ in actual[:first_user])
